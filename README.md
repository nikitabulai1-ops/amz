# Amazon FBA Operations Manager

Chrome extension + Python (FastAPI) backend + a chat website for running FBA
operations day to day: per-ASIN product analysis (Keepa/SellerAmp), unit
economics, inventory reorder planning, PPC campaign auditing, sourcing risk
screening, Plan of Action drafting, and a personal AI agent (your Operations
Manager persona) that can call all of the above as tools during chat.

## Setup

### 1. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your Keepa + SellerAmp API keys (only needed for /analyze)
uvicorn main:app --reload
```

Backend runs at `http://localhost:8000`. Interactive API docs at
`http://localhost:8000/docs`.

### 2. Chat website (the AI agent)

The chat agent needs a model to talk to. Default setup uses **Ollama** — free,
runs entirely on your machine, no API key or signup:

```bash
# Install Ollama: https://ollama.com/download
ollama pull llama3.1     # or another tool-calling-capable model, e.g. qwen2.5:14b
ollama serve              # usually already running as a background service after install
```

With the backend running (`uvicorn main:app --reload` from `backend/`), open
**http://localhost:8000/** in a browser — that's the chat website, served
directly by the FastAPI app. Ask it about a product idea, your margins, an
inventory reorder, a PPC campaign, or a policy notice; it'll call the
`/economics`, `/inventory`, `/ppc`, `/sourcing`, or `/poa` endpoints as tools
when you give it enough numbers to run them.

Want a different (better, but paid) model later — Groq, OpenAI, or an
Anthropic-compatible proxy? Just change `AGENT_BASE_URL` / `AGENT_API_KEY` /
`AGENT_MODEL` in `.env`; no code changes needed, since the agent talks to any
OpenAI-compatible chat-completions API.

**Known limitation:** a free local model has no live web search. The agent's
persona is instructed to say so plainly instead of presenting a guess as a
verified fee/policy fact — see `backend/persona.py`.

### 3. Chrome Extension

1. Open `chrome://extensions/`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked** and select the `extension/` folder
4. Browse any Amazon product page — the analyzer panel appears on the right

### Usage

- Navigate to any Amazon product page
- Enter your product cost in the panel
- Click **Analyze** to get Keepa + SellerAmp data
- ROI is color-coded: green (30%+), yellow (10-30%), red (<10%)

## Backend API

### `GET /analyze/{asin}?cost=`
Existing per-ASIN Keepa + SellerAmp lookup used by the extension.

### `POST /economics/calculate`
Unit economics: landed cost, referral fee, FBA fulfillment fee (by size
tier/weight), allocated storage fee, net margin, ROI, breakeven sell price,
and TACoS (if ad spend + revenue are supplied). Every fee has an override
field so you can plug in your exact Seller Central numbers.

### `POST /inventory/reorder`
Give it on-hand units, sales velocity, lead time, and safety stock per SKU;
get back days of cover, reorder point, a reorder-by date, stockout risk, and
a suggested PO quantity (respecting MOQ/case-pack rounding).

### `POST /ppc/audit`
Give it campaign-level spend/sales/clicks/impressions/orders; get back CTR,
CVR, CPC, ACoS, ROAS, TACoS, and kill/trim/healthy verdicts with a wasted-spend
total.

### `POST /sourcing/evaluate`
Screens a product idea for hazmat/meltable keywords, gated-category terms,
IP/Brand-Registry risk, competitive saturation (from competitor review
counts), and BSR trend from a historical BSR series.

### `POST /poa/draft`
Fills a standard Root Cause / Corrective Actions / Preventive Actions Plan of
Action from case details, lists the attachments Amazon typically expects for
that violation type, and flags root-cause/preventive-action text that reads
too generic to pass review.

### `POST /agent/chat`
`{"message": "...", "session_id": "optional, defaults to 'default'"}` — sends
a message to the chat agent, which can call any of the five endpoints above
as tools. Returns `{"reply": "...", "tools_used": ["..."]}`. This is what the
chat website (`/`) calls; hit it directly if you want to build another
front end.

### `POST /agent/reset?session_id=`
Clears a chat session's history.

### `GET /health`
Liveness check.

## Fee data sources

`backend/fee_config.py` holds the referral fee, FBA fulfillment fee, and
storage fee constants used by `/economics/calculate`. These were assembled
from public 2026 Amazon fee-change reporting, not pulled directly from Seller
Central (network access to Amazon's own fee pages was unavailable when this
was built). **Verify them against Seller Central > Fulfillment by Amazon >
Fee Schedule (or the Revenue Calculator) before relying on them for a real
purchasing decision**, and use the override fields on the endpoint for any
SKU where precision matters. Re-check after any Amazon fee-change
announcement — referral/fulfillment/storage rates and the low-inventory-level
fee have all changed multiple times in the last two years.
