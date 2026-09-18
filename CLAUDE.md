# AMZ-VA — Project Instructions for Claude Code

This repository is the owner's Amazon Online Arbitrage business and its
personal AI business VA. Before doing any Amazon OA analysis, sourcing,
profitability, or business-administration work anywhere in this repo,
read these three files, in this order:

1. **`AMZ-VA/CLAUDE.md`** — the AI's role, operating rules (never invent
   data, ROI vs. margin distinction, deal-analysis format, no irreversible
   actions without approval, etc.), and the standard deal-analysis
   structure.
2. **`AMZ-VA/business_playbook.md`** — the owner's own, specific business
   rules: preferred retailers, profit-margin target, offer-count and Buy
   Box interpretation, sourcing process, pricing strategy, replenishment
   logic, and what's still genuinely undefined.
3. **`AMZ-VA/reports/tasks.md`** — pending tasks, products needing
   review, and follow-ups carried over from previous sessions. Check this
   before answering "what should I work on today" or similar, and update
   it before ending a session if anything new came up or something got
   resolved.

## Priority order

Where `AMZ-VA/business_playbook.md` states a specific rule (a margin
range, a preferred retailer, how to read offer-count movement, the
pricing approach, etc.), **that rule takes priority over generic Amazon OA
advice** — including generic advice that might otherwise sound reasonable.
`AMZ-VA/CLAUDE.md`'s general operating rules (never invent data, ask when
information is missing, no irreversible actions without approval, FACT/
CALCULATION/ASSUMPTION/ESTIMATE/RISK/RECOMMENDATION separation) still
apply underneath the playbook's specific business facts — the playbook
doesn't override honesty or safety rules, only generic sourcing/pricing
*advice*.

## Using the existing calculators — do not recompute by hand

Real unit-economics, inventory, sourcing-risk, PPC/POA, web-research, and
Keepa calculations already exist in `backend/`. Do not redo this math
manually in a response — call the actual tool through `backend/cli.py`:

    python3 backend/cli.py calculate_unit_economics '{"sell_price": 29.99, "unit_cost": 12}'
    python3 backend/cli.py lookup_keepa_product '{"asin": "B0EXAMPLE1"}'

Run `python3 backend/cli.py --list` to see every available tool name, its
description, and its arguments. See `backend/agent_tools.py` for the
underlying registry, and the individual modules (`economics.py`,
`inventory.py`, `sourcing.py`, `ppc.py`, `poa.py`, `research.py`,
`keepa_client.py`) for what each tool actually computes.

`lookup_keepa_product` requires `KEEPA_API_KEY` to be set in the
environment — without it, it returns `status: missing_api_key`, never a
guess. `web_search`/`web_fetch`/`research_*` tools require raw results
already retrieved by Claude's own WebSearch/WebFetch tools (see
`AMZ-VA/research/README.md`) — they don't fetch anything themselves.

## Where business outputs get saved

Every kind of output this VA produces has one designated place. Save to
these locations by default — don't leave a real work product only in the
chat transcript, and don't invent a new location for something that
already has one below:

| Output | Save to |
|---|---|
| A completed deal analysis (PRODUCT/COST/AMAZON/PROFITABILITY/DEMAND/RISK/FINAL ANALYSIS) | `AMZ-VA/deals/analyzed/` — one file per deal |
| The running summary of every analyzed deal | `AMZ-VA/deals/tracker.md` — one row per deal; add a row whenever a deal in `deals/analyzed/` is created, don't recreate the whole file |
| A business report (P&L, inventory, cash flow, performance, etc.) | `AMZ-VA/reports/` — one dated file per report |
| A drafted business document (an agreement, a letter, anything meant to eventually go external) | `AMZ-VA/documents/` — draft here first; nothing in this folder has been sent or finalized just because it exists as a file. See "Approval before external actions" below. |
| A pending task, a product needing review, or a follow-up | `AMZ-VA/reports/tasks.md` — see maintenance rules below |

This is a local-first design on purpose: Google Drive/Docs/Sheets are a
delivery step layered on top of files that already exist in these
folders — Google is never the thing that generates content, only the
thing that sends an already-drafted local file somewhere else.

## Approval before external actions

A file existing in `AMZ-VA/documents/` (or anywhere else) is a **draft**,
not a sent or finalized document. Per `AMZ-VA/CLAUDE.md` rule 12 (no
irreversible actions without explicit approval), never describe a draft as
sent, delivered, signed, or final — say plainly that it's a draft saved
locally, and only take any external-facing action (uploading it, creating
a Google Doc/Sheet from it, appending or overwriting Sheet data) after the
owner explicitly approves that specific action in the conversation. Never
claim a Google action happened unless the tool actually returned a
`success` status — a `missing_token`, `approval_required`, or `api_error`
result means nothing happened, and that must be reported plainly, not
smoothed over.

## Google Drive/Docs/Sheets

The Google integration (`backend/google_client.py`) is authorization-only
right now — the owner has **not yet connected their Google account** (that
requires them to run `backend/google_auth_setup.py` themselves, from a
terminal, after setting up their own Google Cloud OAuth client; see
`backend/google_auth_setup.py`'s own docstring). Until that's done, every
Google tool below returns `status: missing_token` — that is the honest,
expected answer, never a reason to guess or pretend.

Available tools (via the same registry as everything else —
`python3 backend/cli.py --list` shows them): `upload_file_to_drive`,
`find_drive_files`, `create_google_doc`, `create_google_sheet`,
`append_sheet_rows`, `read_sheet_values`, `update_sheet_values`.

Two rules specific to these tools:

1. **Every write action requires `confirmed: true`** (`upload_file_to_drive`,
   `create_google_doc`, `create_google_sheet`, `append_sheet_rows`,
   `update_sheet_values`) — set it only after the owner has explicitly
   approved that specific action in this conversation. Without it, the
   tool itself refuses and returns `status: approval_required` — this is
   enforced in the code, not just by instruction. `find_drive_files` and
   `read_sheet_values` are read-only and need no approval.
2. **Known limitation — `drive.file` scope:** this app can only see or
   touch files it created itself, or that the owner explicitly opened
   with it. It cannot browse or read the owner's pre-existing Drive files,
   Sheets, or Docs that it has no prior relationship with — `find_drive_files`
   returning nothing, or `read_sheet_values` failing, often means exactly
   that, not that the file doesn't exist. If broader existing-file access
   is ever needed, that's a deliberate, separate scope decision for the
   owner to make (e.g. adding `drive.readonly`) — never silently widened.

## Maintaining `AMZ-VA/reports/tasks.md`

- Only add an item when the owner actually raises it, or when something
  from a real analysis genuinely needs follow-up — never invent a task.
- Mark items done rather than deleting them, so there's a simple history.
- Keep entries short — a line or two each. A full deal analysis belongs in
  `AMZ-VA/deals/analyzed/`; a full report belongs in `AMZ-VA/reports/`.
- Use the "Products Needing Review" section for anything the owner wants
  reviewed or re-checked — this is the review list; it doesn't need a
  separate file.
