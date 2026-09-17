# AMZ-VA Research Layer

How AMZ-VA does live web research, what it can and can't actually do, and how
to extend it to another retailer. Code lives in `backend/research.py`; this
folder holds its output (cache + logs).

## The one thing to understand first

`WebSearch` and `WebFetch` are tools built into a **Claude Code session** —
they belong to Claude, not to this repository's Python backend. A plain
Python process (like `backend/main.py`) has no network path to "search the
web" or "fetch a page" on its own here — no API key, no browser, nothing
installed for it.

So the research layer is split into two halves:

1. **Claude calls its own `WebSearch(query)` or `WebFetch(url, prompt)` tool.**
   This is a normal Claude Code tool call, made by whoever is acting as
   AMZ-VA in a given session — not something `backend/research.py` does.
2. **Claude hands the raw result to `backend/research.py`.** That module
   classifies the outcome into an explicit status, extracts whatever fields
   can be honestly pulled out, labels every field with a confidence tag,
   writes a cache file under `AMZ-VA/research/cache/`, and appends one line
   to `AMZ-VA/research/logs/research.log`.

If step 2 is called without the raw result from step 1, it returns
`NOT_PROVIDED` — it never performs a fake search, never fetches anything
itself, and never invents a value to fill the gap.

## Why not just make Python do the fetching?

Because that would mean either (a) giving the backend its own search-API key
or browser, which you explicitly asked to hold off on, or (b) quietly
building a scraper, which you explicitly ruled out. The two-step design gets
real research done with the capabilities you approved (Claude's own
WebSearch/WebFetch) without adding either.

## What this means for Amazon specifically

**This module refuses to process any `amazon.*` URL at all**, even if you
already have fetched content for one — `is_amazon_domain()` is checked before
anything else, and if it matches, the result comes back
`UNSUPPORTED_SOURCE` with a message pointing at the existing Keepa
integration (`backend/main.py` → `GET /analyze/{asin}`), which will provide
real Amazon price/BSR data once you set `KEEPA_API_KEY`. `WebFetch` cannot
reliably read `amazon.com` anyway (JS-rendered, bot-protected) — this guard
just makes sure nobody (including a future version of this module) is
tempted to treat a lucky-looking fetch of an Amazon page as real data.

Everything else in this layer is for **retailer/source research** —
verifying a listing on a retailer's own site, checking a brand's policy
page, comparing prices across a few stores, etc.

## Status vs. confidence — two different labels

Every operation gets a **`RetrievalStatus`** (what happened when we tried to
get the data):

| Status | Meaning |
|---|---|
| `success` | Raw content/results were supplied and processed |
| `empty` | The search/fetch was performed but returned nothing |
| `not_provided` | No raw content was supplied — nothing was actually searched/fetched yet |
| `invalid_url` | The URL is malformed or not http(s) |
| `unsupported_source` | Refused by design (currently: any amazon.* domain) |
| `blocked` | Content matched a bot-block/CAPTCHA pattern, or the tool call reported a block |
| `timeout` | The underlying WebSearch/WebFetch call timed out |
| `error` | Some other failure |

Every **extracted field** gets a **`ConfidenceLabel`**, per AMZ-VA/CLAUDE.md's
data-honesty rules:

| Label | When it's used |
|---|---|
| `VERIFIED` | Read directly from a fetched page's own content, at the timestamp shown |
| `CALCULATED` | Derived by formula from other known values (reserved for future use here — e.g. an effective price after a coupon) |
| `ASSUMED` | Inferred from a search-result snippet (title/description), not the actual page |
| `ESTIMATED` | A numeric value (e.g. price) pulled from a search snippet rather than a fetched page — snippets can be stale or truncated |
| `CONFLICTING` | Two or more sources disagree — **both values are kept, neither is picked as "the" answer** |
| `UNAVAILABLE` | Requested but not obtainable — never replaced with a guess |

## The five functions (`backend/research.py`)

```python
web_search(query, raw_results=None, error=None)
web_fetch(url, raw_content=None, error=None)
research_product(identifier, search_results=None, fetched_pages=None)
research_retailer_product(url, raw_content=None, error=None)
research_multiple_sources(identifier, sources_in)
```

- **`web_search`** / **`web_fetch`** are the atomic normalizers — pass in
  exactly what Claude's WebSearch/WebFetch tool returned. Good for general
  research that isn't about one specific priced product (e.g. "is Brand X
  Amazon-gated").
- **`research_product`** builds the full PRODUCT/PRICING/SOURCE record (see
  schema below) from one or more search hits and/or fetched pages about the
  same product. It merges fields, and if two sources disagree on price it
  keeps both and adds a note to `conflicts` rather than resolving it.
- **`research_retailer_product`** is `research_product` for exactly one
  retailer URL.
- **`research_multiple_sources`** is for cross-checking a claim across
  several sources at once (mixed search/fetch), useful for policy/gating
  questions as well as prices.

All five are also exposed as FastAPI endpoints under `/research/*` (see
`backend/main.py`) and as tools in the existing local-LLM chat agent's
registry (`backend/agent_tools.py`) — see "Where this plugs in" below.

### Recommended WebFetch prompt

Extraction quality depends on what you ask WebFetch for. For a retailer
product page, ask for JSON:

> "Return a JSON object with keys title, brand, price, sale_price, coupon,
> shipping, availability. Use null for anything not present on the page."

`research.py` looks for a JSON object in the returned text first; if there
isn't one, it falls back to a plain `$` price regex and gives up on
everything else (rather than guessing).

## The standardized schema

```
PRODUCT           (ProductInfo)
  title, brand, asin, upc_ean, model, category, size_variation
  field_confidence: {field_name: ConfidenceLabel}
  field_sources:    {field_name: [source urls/labels]}

PRICING           (one PricingRecord per source)
  retailer, url, price, sale_price, coupon, discount, shipping,
  availability, observed_at, confidence

SOURCE            (one SourceRecord per search/fetch call)
  source_name, domain, url, retrieved_at, query_or_input, status, error
```

This is the shape the AMZ-VA deal analyzer (per `AMZ-VA/CLAUDE.md`'s
PRODUCT/COST/AMAZON/PROFITABILITY/DEMAND/RISK/FINAL ANALYSIS structure) is
meant to read from — retailer-side PRODUCT/PRICING/SOURCE data from here,
Amazon-side data from Keepa once configured, fee math from
`backend/economics.py`.

## Cache layout

```
AMZ-VA/research/cache/<slug-of-identifier>/<YYYY-MM-DD>__<NN>.json
```

`<slug>` is the identifier (product name, ASIN, URL, or query) lowercased
and non-alphanumeric characters collapsed to `-`. `<NN>` increments if you
research the same thing more than once on the same day, so nothing is ever
overwritten — you can see the history of what was checked and when.

Each cache file is the full JSON of whatever result object was produced
(`WebSearchResult`, `WebFetchResult`, `ResearchResult`, or
`MultiSourceResult`) — open it directly to see exactly what was found, with
what confidence, from which source, at what time.

## Logs

`AMZ-VA/research/logs/research.log` is append-only JSONL, one line per
call: `timestamp`, `function`, `input`, `status`, `cache_path`, `error`.
It's a flat audit trail — tail it to see what's been researched recently:

```bash
tail -20 AMZ-VA/research/logs/research.log | python3 -m json.tool
```

## Error handling

| Situation | Behavior |
|---|---|
| Invalid URL (no scheme, bad format) | `INVALID_URL`, checked before anything else |
| amazon.* URL | `UNSUPPORTED_SOURCE`, refused unconditionally |
| Page content matches a CAPTCHA/block pattern | `BLOCKED`, fields not extracted from it |
| WebSearch/WebFetch tool call itself failed | Pass its error string in via `error=`; classified into `TIMEOUT` / `BLOCKED` / `ERROR` |
| Empty search results | `EMPTY` (distinct from `NOT_PROVIDED`, which means "nothing was even attempted") |
| Two sources disagree | `CONFLICTING` on the field, both values kept in `conflicts` / the pricing list — never averaged or silently chosen |
| Nothing supplied at all | `NOT_PROVIDED` — the honest default |

## How another retailer gets added later

There's nothing to "add" per retailer today — `web_fetch` and
`research_retailer_product` work on any non-Amazon URL already, because
extraction is generic (JSON-block-first, then a price regex), not
site-specific. If a particular retailer's pages need custom parsing later
(e.g. their own JSON-LD product schema, a specific coupon-code format),
that would go into `_extract_fields_from_text()` in `backend/research.py`
as an additional, clearly-labeled parsing branch — keyed off `domain_of(url)`
the same way the Amazon guard is — without changing the function signatures
or the schema above.

## Where this plugs into the existing codebase

- **`backend/main.py`** — registers `/research/web-search`,
  `/research/web-fetch`, `/research/product`, `/research/retailer-product`,
  `/research/multi` alongside the existing `/economics`, `/inventory`,
  `/ppc`, `/sourcing`, `/poa` routers.
- **`backend/agent_tools.py`** — registers the same five functions as
  tools the local-LLM chat agent (`backend/agent.py`, normally running on
  Ollama) can call. That agent has no live web access on its own, so if it
  calls one of these tools without `raw_results`/`raw_content`, it gets back
  `not_provided` — the honest answer — not a guess. These tools become
  genuinely useful once something with real web access (this Claude Code
  session, or later, a browser-capable agent) supplies the raw content.
- **`backend/economics.py` / `inventory.py` / `sourcing.py` / `ppc.py` /
  `poa.py`** — untouched. This module doesn't duplicate any fee, inventory,
  or sourcing-risk logic; it only produces the retailer-side PRODUCT/PRICING
  facts those calculators need as input.

## Running it from Claude Code (this session, or a future one)

There's a CLI so you don't need to write Python each time:

```bash
cd backend
python3 research.py web-fetch --url "https://retailer.example.com/p/123" \
  --content-file /tmp/fetched.txt
```

Typical flow in a Claude Code session:
1. Call the `WebFetch` tool on the retailer URL, with the JSON-extraction
   prompt above.
2. Save its answer text to a file (or pass it straight through if scripting).
3. Run `python3 research.py web-fetch --url ... --content-file ...` (or call
   `research.web_fetch(...)` directly if already in a Python context).
4. Read the printed JSON, or open the cache file it just wrote, to see the
   labeled result.

## What still needs your approval/credentials

- **Nothing to run this layer itself** — it works today with zero
  credentials, exactly as scoped (no MCP server, no browser automation, no
  Amazon scraping, no Seller Central, no new API keys).
- **`KEEPA_API_KEY`** — still the open item from the earlier audit, needed
  for real Amazon price/BSR/seller data. This module deliberately does not
  and will not substitute for it.
