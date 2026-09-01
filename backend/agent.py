"""Chat endpoint for the FBA Operations Manager agent.

Talks to any OpenAI-compatible chat-completions API. Defaults to a local
Ollama server (free, no API key, nothing leaves your machine). Point it at
Groq, OpenAI, or an Anthropic-compatible proxy later by changing the
AGENT_BASE_URL / AGENT_API_KEY / AGENT_MODEL env vars — no code change needed.
"""

import json
import os

from fastapi import APIRouter, HTTPException
from openai import APIConnectionError, APIStatusError, OpenAI
from pydantic import BaseModel

from agent_tools import TOOL_SCHEMAS, dispatch_tool
from persona import SYSTEM_PROMPT

router = APIRouter(prefix="/agent", tags=["agent"])

AGENT_BASE_URL = os.getenv("AGENT_BASE_URL", "http://localhost:11434/v1")
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "ollama")
AGENT_MODEL = os.getenv("AGENT_MODEL", "llama3.1")

_client = OpenAI(base_url=AGENT_BASE_URL, api_key=AGENT_API_KEY)

MAX_TOOL_ITERATIONS = 5
MAX_HISTORY_MESSAGES = 40  # trim so local context windows don't blow up on long sessions

_sessions: dict[str, list[dict]] = {}


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    reply: str
    tools_used: list[str]


def _history_for(session_id: str) -> list[dict]:
    history = _sessions.setdefault(session_id, [{"role": "system", "content": SYSTEM_PROMPT}])
    if len(history) > MAX_HISTORY_MESSAGES:
        history[:] = [history[0], *history[-(MAX_HISTORY_MESSAGES - 1):]]
    return history


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    history = _history_for(req.session_id)
    history.append({"role": "user", "content": req.message})

    tools_used: list[str] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        try:
            completion = _client.chat.completions.create(
                model=AGENT_MODEL,
                messages=history,
                tools=TOOL_SCHEMAS,
            )
        except APIConnectionError as e:
            raise HTTPException(
                502,
                f"Could not reach the model backend at {AGENT_BASE_URL}. Is Ollama running "
                f"('ollama serve') and is the model pulled ('ollama pull {AGENT_MODEL}')? ({e})",
            )
        except APIStatusError as e:
            raise HTTPException(
                502,
                f"Model backend at {AGENT_BASE_URL} rejected the request (HTTP {e.status_code}). "
                f"Usually means the model name '{AGENT_MODEL}' isn't pulled, or AGENT_BASE_URL/AGENT_API_KEY "
                f"is misconfigured for whatever's running there. Raw error: {e}",
            )

        msg = completion.choices[0].message
        history.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            return ChatResponse(reply=msg.content or "", tools_used=tools_used)

        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError as e:
                args, result = {}, {"error": f"Model sent malformed arguments: {e}"}
            else:
                result = dispatch_tool(name, args)
            tools_used.append(name)
            history.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, default=str),
                }
            )

    return ChatResponse(
        reply="Hit the tool-call loop limit for this turn — try breaking the ask into smaller steps.",
        tools_used=tools_used,
    )


@router.post("/reset")
def reset(session_id: str = "default") -> dict:
    _sessions.pop(session_id, None)
    return {"status": "reset", "session_id": session_id}
