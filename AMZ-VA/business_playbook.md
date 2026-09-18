# AMZ-VA Business Playbook

Personal operating instructions for the owner's Amazon Online Arbitrage
business, for AMZ-VA (this project's AI business VA) to follow permanently.

**Companion document, not a replacement:** `AMZ-VA/CLAUDE.md` holds the AI's
role, analysis format, and 15 operating rules (never invent data, ROI vs.
margin distinction, deal-analysis structure, etc.) — those are general
principles the owner already established for how the AI should behave. This
file is meant to hold the owner's *specific* business facts and preferences
(which retailers, which tools, which thresholds, which day-to-day habits).
Where a requested topic below is really just CLAUDE.md's general principle
applied to a specific case, this file says so and points back to it instead
of duplicating it.

## How to read this document

Every section is labeled with exactly one status:

| Label | Meaning |
|---|---|
| **ESTABLISHED OWNER RULE** | The owner explicitly stated this, in this conversation or in their standing AI instructions. Cited below. |
| **OWNER PREFERENCE** | A softer inclination the owner expressed, not a hard rule. |
| **PARTIALLY ESTABLISHED — CLARIFICATION NEEDED** | Something adjacent was stated, but the specific detail requested isn't confirmed. |
| **NOT YET DEFINED** | Nothing on this topic has been stated. Nothing here is invented to fill the gap. |

Per the owner's explicit instruction: *"Do not invent rules that the owner
has not stated."* Where a section is empty, it stays empty until the owner
fills it in — this file does not guess.

---

## 1. Sourcing Methods

**Status: ESTABLISHED OWNER RULE**

Previously used **SellerAmp Storefront Stalking**: find a product, open
its offer count, go through the sellers on that listing, see what those
sellers are selling, and continue going deeper — seller to seller, product
to product.

Currently transitioning toward **Keepa Product Finder**, Keepa in general,
and **Keepa Seller Lookup**, experimenting with filters.

---

## 2. Preferred Retailers

**Status: ESTABLISHED OWNER RULE**

Walmart, Target, Kohl's, Home Depot, Costco, Macy's.

---

## 3. Use of CardBear

**Status: ESTABLISHED OWNER RULE**

CardBear is used to find discounted gift cards/coupons. It's the tool used
to compare the *effective* cost of buying from different retailers once a
product is found at more than one store — see section 10 (Comparing
Multiple Retailers) for how that comparison works.

---

## 4. Profit-Margin Target

**Status: ESTABLISHED OWNER RULE**

Target is **25–30% profit margin**. Generally do not want to go below that
range.

Also already established generally (from `AMZ-VA/CLAUDE.md` / standing
instructions, not specific to this number): ROI and margin are distinct
metrics and must never be conflated — see CLAUDE.md rule 7 and the
maximum-buy-price formula (rule 8).

---

## 5. Monthly Sales Volume Preference (100+ monthly sold)

**Status: ESTABLISHED OWNER RULE**

Generally do not want products estimated below **100 monthly sold**.
Monthly-sold performance is evaluated over roughly the **past 3 months to
1 year**, not just a single snapshot.

---

## 6. Interpreting Keepa Offer-Count Movement

**Status: ESTABLISHED OWNER RULE**

Offer-count movement is read for two things: **competition** and
**possible IP-complaint risk**.

- **Bad pattern:** offer count steadily *increasing* while the Buy Box
  price is *falling* (e.g. offers going from roughly 15 to 60 while price
  drops). Interpretation: more sellers are entering and competing for the
  Buy Box — a warning sign, not a buy signal.
- **Good/preferred pattern:** offer count that *fluctuates* rather than
  steadily rising (e.g. 15 → 25 → 20 → 30 → 22). Interpretation: sellers
  are selling through inventory and going in/out of stock — a healthier
  sign than a one-directional climb.
- **Also fine:** a relatively steady offer count, with only small drops or
  normal movement.

**Tooling gap (separate from the business rule above, not yet built):**
`backend/keepa_client.py` does not currently fetch live offer-count/seller
data at all — this rule can't be automated in AMZ-VA's tooling until that
capability is added. The business rule itself is fully established; the
Keepa client simply doesn't support checking it yet.

---

## 7. Interpreting Buy Box Movement

**Status: ESTABLISHED OWNER RULE**

Generally fine with small Buy Box price movements of around **$1–$2**. A
large drop — e.g. **$20 → $13** — is a problem.

Also look at the Buy Box chart generally (not just the current price) to
understand pricing behavior and stability over time.

Buy Box *price* history is already available from `backend/keepa_client.py`
(`buy_box_history`, `current_buy_box_price`) once `KEEPA_API_KEY` is
configured — the data plumbing to check this rule automatically exists.

(See section 16 for the separate, post-purchase question of what to do
*when* the Buy Box drops on a listing already owned.)

---

## 8. Process for Finding the Product After It Passes the Charts/Numbers

**Status: ESTABLISHED OWNER RULE**

1. After a product looks good on the charts and numbers, determine the
   **maximum cost** using SellerAmp (see section 9).
2. Use **Google** to find the same product across retailers.
3. If multiple stores carry it, compare **CardBear** discounts to find the
   lowest effective cost (see section 10).
4. For **Walmart** specifically, verify the product is sold by Walmart
   directly, not a third-party Walmart Marketplace seller (see section 11).
5. Once the numbers/charts look good, a good source price is found, the
   retailer is confirmed legitimate, and the product is actually
   purchasable — place the order (see section 12).

---

## 9. Use of SellerAmp Maximum Cost

**Status: ESTABLISHED OWNER RULE**

Once a product passes the charts/numbers check, SellerAmp is used to
determine the maximum cost that can be paid. The sourced price is then
targeted at or below that number.

Example given: sale price $29, SellerAmp says cost should be no more than
$16 → the goal is to find the product for $16 or less.

(This is the practical, tool-specific version of the general Maximum Buy
Price *formula* already in `AMZ-VA/CLAUDE.md` rule 8 — that formula is the
underlying math; SellerAmp is the tool actually used to compute and apply
it day to day.)

---

## 10. Comparing Multiple Retailers

**Status: ESTABLISHED OWNER RULE**

When the same product is available at more than one retailer, compare
CardBear discounts and choose based on the **lowest effective cost**, not
sticker price alone.

Example given: Target gift card = 8% discount, Walmart gift card = 15%
discount → Walmart preferred because the effective cost is lower.

---

## 11. Retailer Verification Rules

**Status: PARTIALLY ESTABLISHED**

**ESTABLISHED OWNER RULE (Walmart-specific):** verify the product is
actually sold by **Walmart** directly, not a third-party Walmart
Marketplace seller, before treating it as a Walmart-sourced buy.

**ESTABLISHED OWNER RULE (general, from standing instructions, applies to
all retailers):** a source should be legitimate, established, an
authorized retailer when relevant, provide proper invoices/receipts, sell
authentic products, and be reliable with shipping/cancellations/returns.
Never source from a questionable supplier just because it's cheap.

**Not yet stated:** an equivalent specific verification check for the
other preferred retailers (Target, Kohl's, Home Depot, Costco, Macy's) —
only Walmart has a named, specific check so far. The general criteria
above apply to all of them until/unless a retailer-specific check is
given.

---

## 12. Purchasing Workflow

**Status: ESTABLISHED OWNER RULE**

Once the numbers/charts look good, a good source price has been found,
the retailer is confirmed legitimate, and the product can actually be
purchased — the order is placed.

**Not yet stated:** granular execution detail beyond that point (payment
method/account used, whether orders are split, order-confirmation habits).

---

## 13. FBA Workflow

**Status: ESTABLISHED OWNER RULE**

Fulfillment model is **FBA**. After the order is received: prep the
inventory, send it to Amazon, and Amazon receives/checks it into the
warehouse.

**Not yet stated:** specific prep requirements (labeling, poly-bagging,
prep center use if any), shipment-splitting rules, or carrier preferences.

---

## 14. Pricing Strategy

**Status: ESTABLISHED OWNER RULE**

Do **not** automatically price at the lowest offer on the listing. Price
around the **middle of the seller market**, weighing how much inventory
the cheaper sellers have against how quickly the product actually sells.

Example given: two sellers at $22 with only two units each, the product
sells ~300/month, and the next seller up is at $28 → price around **$27**,
on the expectation that the $22 sellers will sell out before this
inventory checks in.

---

## 15. Daily Listing-Monitoring Habit

**Status: ESTABLISHED OWNER RULE**

Listings are checked roughly **every day** to confirm they're still
profitable.

**Not yet stated:** the specific checklist/tool used during that daily
check (beyond profitability) — kept as its own open item, not invented.

---

## 16. Response When the Buy Box Drops

**Status: ESTABLISHED OWNER RULE**

When the Buy Box drops on inventory already owned, will often accept
**breaking even** to move the inventory rather than hold it indefinitely.

**Explicitly confirmed as NOT YET DEFINED (do not invent):** there is no
established rule yet for what to do with a product that simply **does not
sell** (distinct from a Buy Box drop on a moving product) — the owner has
stated this directly and asked that no rule be invented here.

---

## 17. Replenishment Logic

**Status: ESTABLISHED OWNER RULE**

Reorder when a product is **moving very quickly** and the point is reached
where more can be bought while still making money. This is a velocity +
profitability judgment call, not a fixed numeric trigger (no specific
unit-count or days-of-cover threshold has been stated, and none is assumed
here).

(General replenishable-product evaluation criteria from standing
instructions — historical price, sales velocity, seller stability, source
availability, quantity availability, repeatability, competition, risk —
still apply as background criteria alongside this specific reorder logic.)

---

## Summary — Open Items Requiring Owner Input

Resolved as of this update: sourcing methods, preferred retailers, CardBear
usage, profit-margin target, monthly-sold threshold, Keepa offer-count
interpretation, Buy Box movement interpretation, the product-finding
process, SellerAmp Max Cost usage, multi-retailer comparison, Walmart
verification, the high-level purchasing workflow, the high-level FBA
workflow, pricing strategy, the daily monitoring habit, the Buy Box-drop
response, and replenishment logic.

Still open:

- [ ] What to do when a product does not sell — **explicitly left
      undefined by the owner; do not invent a rule here.**
- [ ] Retailer-specific verification checks for Target, Kohl's, Home
      Depot, Costco, and Macy's (only Walmart has a named check so far —
      the general legitimacy criteria apply to the rest in the meantime)
- [ ] Granular purchasing execution detail (payment method/account,
      order-splitting habits)
- [ ] Granular FBA prep detail (labeling, prep center use, shipment
      splitting, carrier preferences)
- [ ] Daily monitoring checklist detail beyond "check profitability"
- [ ] A firmer numeric replenishment trigger, if one is ever defined
      (currently a velocity/profitability judgment call — which is itself
      the established rule, not a gap on its own)

Also still open (a tooling gap, not a business rule): `backend/keepa_client.py`
does not yet fetch live offer-count data, so section 6's rule can't be
checked automatically until that capability is built.
