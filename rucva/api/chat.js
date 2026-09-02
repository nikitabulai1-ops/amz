// Streaming chat backend for RUCVA. Keeps the Anthropic API key server-side
// (never sent to the browser) and runs a manual tool-use loop so the AI can
// call the real FBA calculators instead of estimating fees in prose.
//
// Protocol: client POSTs {messages: [{role, content}, ...]}. Response is
// newline-delimited JSON (NDJSON), one object per line:
//   {"type":"delta","text":"..."}   — append to the visible reply
//   {"type":"tool","name":"..."}    — a calculator was called (for a UI chip)
//   {"type":"done"}                 — stream finished normally
//   {"type":"error","message":"..."} — something failed; may follow partial deltas

import Anthropic from "@anthropic-ai/sdk";
import { TOOLS, runTool } from "./_calculators.js";

const MODEL = process.env.ANTHROPIC_MODEL || "claude-sonnet-4-6";
const MAX_ITERATIONS = 6;

const SYSTEM_PROMPT = `You are RUCVA, a private virtual assistant and business partner for one Amazon FBA/FBM seller. You are not a generic chatbot — you're a knowledgeable, direct operator who has run FBA businesses for years.

VOICE: Direct, honest, experienced mentor energy. No corporate filler, no "I'd be happy to help", no hedging. If the user is about to make a bad call, say so plainly and explain why using real unit economics or Amazon policy. If something looks good, confirm it clearly and tell them the next concrete step.

EXPERTISE: Amazon FBA and FBM operations, buy box strategy, Keepa chart reading (BSR history, price history, sales rank drops/spikes), SellerAmp number evaluation, sourcing strategy, shipping/packaging decisions, ungating strategy, Q4 and seasonal sourcing, pricing decisions, account health management, FBA shipment prep.

TOOLS: You can call calculate_fba_economics and calculate_fbm_economics to get exact numbers — referral fee, fulfillment fee, margin, ROI, breakeven. Use them whenever the user gives you a cost and a price. Don't estimate fees by hand when you can compute them exactly. If the user wants a fuller workup (multiple products, saved history), point them to the app's Product Analyzer or COGS Tracker sections, which do the same math with more structure.

HONESTY: You have no live internet access. You cannot check today's actual fee schedule, a real listing, or current BSR — if the user needs a number verified against the live Amazon site, tell them plainly and point them to Seller Central, Keepa, or SellerAmp directly rather than guessing and presenting it as fact.

Keep replies tight — lead with the number or the verdict, then the reasoning, then the action.`;

export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.status(405).json({ error: "POST only" });
    return;
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    res.status(500).json({ error: "ANTHROPIC_API_KEY is not configured on the server." });
    return;
  }

  let body;
  try {
    body = typeof req.body === "string" ? JSON.parse(req.body) : req.body;
  } catch {
    res.status(400).json({ error: "Invalid JSON body" });
    return;
  }

  const incoming = Array.isArray(body?.messages) ? body.messages : null;
  if (!incoming || incoming.length === 0) {
    res.status(400).json({ error: "messages must be a non-empty array" });
    return;
  }

  res.writeHead(200, {
    "Content-Type": "application/x-ndjson; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
  });

  const write = (obj) => res.write(JSON.stringify(obj) + "\n");

  const client = new Anthropic({ apiKey });
  let messages = incoming.map((m) => ({ role: m.role, content: m.content }));

  try {
    for (let i = 0; i < MAX_ITERATIONS; i++) {
      const stream = client.messages.stream({
        model: MODEL,
        max_tokens: 4096,
        system: SYSTEM_PROMPT,
        tools: TOOLS,
        thinking: { type: "adaptive" },
        messages,
      });

      stream.on("text", (delta) => write({ type: "delta", text: delta }));

      const message = await stream.finalMessage();

      if (message.stop_reason === "pause_turn") {
        messages.push({ role: "assistant", content: message.content });
        continue;
      }

      const toolUseBlocks = message.content.filter((b) => b.type === "tool_use");

      if (toolUseBlocks.length === 0) {
        write({ type: "done" });
        res.end();
        return;
      }

      messages.push({ role: "assistant", content: message.content });

      const toolResults = [];
      for (const tool of toolUseBlocks) {
        write({ type: "tool", name: tool.name });
        let content;
        try {
          content = JSON.stringify(runTool(tool.name, tool.input));
        } catch (e) {
          content = `Error: ${e.message}`;
        }
        toolResults.push({ type: "tool_result", tool_use_id: tool.id, content });
      }
      messages.push({ role: "user", content: toolResults });
    }

    write({ type: "error", message: "Hit the tool-call round limit for this turn — try breaking the ask into smaller steps." });
    res.end();
  } catch (e) {
    const message =
      e instanceof Anthropic.AuthenticationError ? "Invalid Anthropic API key — check ANTHROPIC_API_KEY on the server." :
      e instanceof Anthropic.RateLimitError ? "Rate limited by Anthropic — wait a bit and try again." :
      e instanceof Anthropic.APIError ? `Anthropic API error (${e.status}): ${e.message}` :
      `Server error: ${e.message}`;
    write({ type: "error", message });
    res.end();
  }
}
