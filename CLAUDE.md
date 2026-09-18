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

## Maintaining `AMZ-VA/reports/tasks.md`

- Only add an item when the owner actually raises it, or when something
  from a real analysis genuinely needs follow-up — never invent a task.
- Mark items done rather than deleting them, so there's a simple history.
- Keep entries short — a line or two each. A full deal analysis belongs in
  `AMZ-VA/deals/analyzed/`; a full report belongs in `AMZ-VA/reports/`.
