// FBA calculators — same verified logic used by the rest of this project
// (see /backend/economics.py etc. and the Luna artifact). Kept in one place
// so the chat backend's tools and the frontend's own calculator UIs agree.

export const FEE = {
  FUEL_SURCHARGE_PCT: 0.035,
  MIN_REFERRAL_FEE: 0.30,
  REFERRAL_FEE_TABLE: {
    default: 0.15,
    amazon_device_accessories: 0.45,
    electronics: 0.08, computers: 0.08, major_appliances: 0.08, video_game_consoles: 0.08,
    automotive_powersports: 0.12, industrial_scientific: 0.12,
    grocery_gourmet: [[15.00, 0.08], [null, 0.15]],
    beauty_personal_care: [[10.00, 0.08], [null, 0.15]],
    furniture: [[200.00, 0.15], [null, 0.10]],
    jewelry: [[250.00, 0.20], [null, 0.05]],
    watches: [[1500.00, 0.16], [null, 0.03]],
    clothing_accessories: [[15.00, 0.05], [20.00, 0.10], [null, 0.17]],
    baby_products: [[10.00, 0.08], [null, 0.15]],
  },
  SMALL_STANDARD_FEES: {
    2: { under_10: 2.88, mid_10_50: 3.06, over_50: 3.57 },
    4: { under_10: 3.00, mid_10_50: 3.19, over_50: 3.70 },
    6: { under_10: 3.13, mid_10_50: 3.33, over_50: 3.84 },
    10: { under_10: 3.33, mid_10_50: 3.53, over_50: 4.04 },
    16: { under_10: 3.60, mid_10_50: 3.81, over_50: 4.32 },
  },
  LARGE_STANDARD_FEES: {
    1: { mid_10_50: 4.20, over_50: 4.51 },
    2: { mid_10_50: 4.75, over_50: 5.06 },
    3: { mid_10_50: 5.42, over_50: 5.73 },
    20: { mid_10_50: 8.42, over_50: 8.73 },
  },
  BULKY_FEES: { small_bulky: { 50: 9.61 }, large_bulky: { 50: 19.66 } },
  EXTRA_LARGE_FEES: { 50: 26.79, 150: 84.16 },
  STORAGE_FEE_PER_CUFT: {
    standard: { jan_sep: 0.78, q4: 2.40 },
    oversize: { jan_sep: 0.56, q4: 1.40 },
  },
};

function round2(n, d = 2) {
  const f = Math.pow(10, d);
  return Math.round((n + Number.EPSILON) * f) / f;
}

function referralFeeFor(category, price) {
  const rule = FEE.REFERRAL_FEE_TABLE[category] ?? FEE.REFERRAL_FEE_TABLE.default;
  let rate;
  if (typeof rule === "number") {
    rate = rule;
  } else {
    rate = rule[rule.length - 1][1];
    for (const [ceiling, pct] of rule) {
      if (ceiling !== null && price <= ceiling) { rate = pct; break; }
    }
  }
  return [Math.max(round2(price * rate), FEE.MIN_REFERRAL_FEE), rate];
}

function priceBracket(price) { return price < 10 ? "under_10" : price <= 50 ? "mid_10_50" : "over_50"; }

function tableLookup(table, weight) {
  const keys = Object.keys(table).map(Number).sort((a, b) => a - b);
  for (const k of keys) if (weight <= k) return table[k];
  return table[keys[keys.length - 1]];
}

function fulfillmentFee(req, notes) {
  const tier = (req.size_tier || "small_standard").toLowerCase();
  let base;
  if (tier === "small_standard") {
    base = tableLookup(FEE.SMALL_STANDARD_FEES, req.weight_oz ?? 4)[priceBracket(req.sell_price)];
  } else if (tier === "large_standard") {
    const bracket = req.sell_price > 50 ? "over_50" : "mid_10_50";
    base = tableLookup(FEE.LARGE_STANDARD_FEES, req.weight_lb ?? 1)[bracket];
  } else if (tier === "small_bulky" || tier === "large_bulky") {
    base = tableLookup(FEE.BULKY_FEES[tier], req.weight_lb ?? 10);
  } else if (tier === "extra_large") {
    base = tableLookup(FEE.EXTRA_LARGE_FEES, req.weight_lb ?? 20);
    notes.push("Extra-Large over 96in/130in length+girth adds a $17-$25 Overmax surcharge, not included here.");
  } else {
    notes.push(`Unknown size_tier '${req.size_tier}', used small_standard 4oz.`);
    base = tableLookup(FEE.SMALL_STANDARD_FEES, 4)[priceBracket(req.sell_price)];
  }
  return round2(base * (1 + FEE.FUEL_SURCHARGE_PCT));
}

function storageFee(req) {
  if (req.cubic_feet_per_unit == null) return 0;
  const rate = FEE.STORAGE_FEE_PER_CUFT[req.is_oversize ? "oversize" : "standard"][req.is_q4 ? "q4" : "jan_sep"];
  return round2(rate * req.cubic_feet_per_unit * (req.months_in_storage ?? 1));
}

export function calculateUnitEconomics(input) {
  const req = Object.assign({ category: "default", size_tier: "small_standard" }, input);
  if (!(req.sell_price > 0)) throw new Error("sell_price must be greater than 0");
  if (!(req.unit_cost >= 0)) throw new Error("unit_cost must be 0 or greater");

  const notes = [];
  const landedCost = round2(req.unit_cost + (req.shipping_to_fba_per_unit ?? 0) + (req.other_per_unit_cost ?? 0));
  const [referralFee, referralPct] = referralFeeFor(req.category, req.sell_price);
  const fFee = fulfillmentFee(req, notes);
  const sFee = storageFee(req);
  const totalFees = round2(referralFee + fFee + sFee);
  const netProfit = round2(req.sell_price - landedCost - totalFees);
  const marginPct = round2((netProfit / req.sell_price) * 100);
  const roiPct = landedCost ? round2((netProfit / landedCost) * 100) : 0;
  const breakeven = referralPct < 1 ? round2((landedCost + fFee + sFee) / (1 - referralPct)) : null;

  let verdict = "BUY";
  if (marginPct < 10 || roiPct < 20) verdict = "SKIP";
  else if (marginPct < 15 || roiPct < 30) verdict = "MARGINAL";

  return {
    landed_cost_per_unit: landedCost, referral_fee: referralFee, referral_fee_pct: referralPct,
    fulfillment_fee: fFee, storage_fee: sFee, total_fees: totalFees, net_profit_per_unit: netProfit,
    margin_pct: marginPct, roi_pct: roiPct, breakeven_sell_price: breakeven, verdict, notes,
  };
}

export function calculateFbmEconomics(input) {
  if (!(input.sell_price > 0)) throw new Error("sell_price must be greater than 0");
  if (!(input.unit_cost >= 0)) throw new Error("unit_cost must be 0 or greater");
  const landedCost = round2(input.unit_cost + (input.other_per_unit_cost ?? 0));
  const [referralFee, referralPct] = referralFeeFor(input.category || "default", input.sell_price);
  const shipCost = input.shipping_cost ?? 0;
  const totalFees = round2(referralFee + shipCost);
  const netProfit = round2(input.sell_price - landedCost - totalFees);
  const marginPct = round2((netProfit / input.sell_price) * 100);
  const roiPct = landedCost ? round2((netProfit / landedCost) * 100) : 0;
  const breakeven = referralPct < 1 ? round2((landedCost + shipCost) / (1 - referralPct)) : null;
  return { landed_cost_per_unit: landedCost, referral_fee: referralFee, referral_fee_pct: referralPct,
    shipping_cost: shipCost, total_fees: totalFees, net_profit_per_unit: netProfit,
    margin_pct: marginPct, roi_pct: roiPct, breakeven_sell_price: breakeven };
}

export const TOOLS = [
  {
    name: "calculate_fba_economics",
    description: "Calculate real FBA profit, referral fee, fulfillment fee, storage fee, margin %, ROI %, and breakeven price for one unit. Use whenever the user gives a sell price and a cost and wants FBA numbers.",
    input_schema: {
      type: "object",
      properties: {
        sell_price: { type: "number" }, unit_cost: { type: "number" },
        shipping_to_fba_per_unit: { type: "number", description: "Freight/prep to land at FBA, default 0" },
        other_per_unit_cost: { type: "number", description: "Default 0" },
        category: { type: "string", description: "default | electronics | computers | grocery_gourmet | beauty_personal_care | furniture | jewelry | watches | clothing_accessories | baby_products | amazon_device_accessories | automotive_powersports | industrial_scientific" },
        size_tier: { type: "string", description: "small_standard | large_standard | small_bulky | large_bulky | extra_large" },
        weight_oz: { type: "number" }, weight_lb: { type: "number" },
        cubic_feet_per_unit: { type: "number" }, is_q4: { type: "boolean" }, is_oversize: { type: "boolean" },
        months_in_storage: { type: "number" },
      },
      required: ["sell_price", "unit_cost"],
    },
  },
  {
    name: "calculate_fbm_economics",
    description: "Calculate real FBM (merchant-fulfilled) profit, referral fee, shipping cost, margin %, ROI %, and breakeven price for one unit.",
    input_schema: {
      type: "object",
      properties: {
        sell_price: { type: "number" }, unit_cost: { type: "number" },
        shipping_cost: { type: "number", description: "Cost to ship this unit to the customer" },
        other_per_unit_cost: { type: "number" },
        category: { type: "string" },
      },
      required: ["sell_price", "unit_cost"],
    },
  },
];

export function runTool(name, input) {
  if (name === "calculate_fba_economics") return calculateUnitEconomics(input);
  if (name === "calculate_fbm_economics") return calculateFbmEconomics(input);
  throw new Error(`Unknown tool: ${name}`);
}
