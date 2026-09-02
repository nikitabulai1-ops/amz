// Keepa Product API integration — server-side only, the API key never reaches
// the browser (same pattern as ANTHROPIC_API_KEY). Keepa's API is a separate
// paid subscription from Keepa Pro (the browser extension) — see README.
//
// We deliberately request only `history=1` (no `stats` param) and derive
// current price/rank plus 30/90/180-day averages ourselves from the raw
// history series below. That keeps each lookup to the cheapest possible
// token cost and avoids depending on the exact shape of Keepa's `stats`
// object, which isn't reachable from this sandbox to verify against.

const KEEPA_EPOCH_OFFSET_MIN = 21564000; // Keepa Time (minutes) -> Unix time
const CSV_AMAZON = 0, CSV_NEW = 1, CSV_SALES_RANK = 3, CSV_BUY_BOX = 18;
const DOMAIN_CODES = { US: 1, GB: 3, DE: 4, FR: 5, JP: 6, CA: 7, IT: 8, ES: 9, IN: 10, MX: 11 };

function round2(n) { return Math.round(n * 100) / 100; }

function keepaMinutesToISO(min) {
  return new Date((min + KEEPA_EPOCH_OFFSET_MIN) * 60000).toISOString();
}

function parseSeries(csv, index, { isPrice = true } = {}) {
  const arr = csv && csv[index];
  if (!Array.isArray(arr)) return [];
  const out = [];
  for (let i = 0; i < arr.length; i += 2) {
    const t = arr[i], v = arr[i + 1];
    if (v == null || v === -1) continue;
    out.push({ date: keepaMinutesToISO(t), value: isPrice ? round2(v / 100) : v });
  }
  return out;
}

function avgSince(series, days, { asInt = false } = {}) {
  const cutoff = Date.now() - days * 86400000;
  const pts = series.filter((p) => new Date(p.date).getTime() >= cutoff);
  if (!pts.length) return null;
  const mean = pts.reduce((s, p) => s + p.value, 0) / pts.length;
  return asInt ? Math.round(mean) : round2(mean);
}

export const KEEPA_TOOL = {
  name: "lookup_keepa_product",
  description: "Look up real Amazon price and sales-rank history for a product by ASIN using Keepa. Returns current price, 30/90/180-day price averages, current sales rank and its averages, and recent history points. Use this whenever the user gives an ASIN and wants real historical data instead of an estimate. If Keepa isn't connected on this deployment, this will return an error explaining that plainly — relay it, don't guess numbers instead.",
  input_schema: {
    type: "object",
    properties: {
      asin: { type: "string", description: "10-character Amazon ASIN" },
      domain: { type: "string", description: "Marketplace code, default US. One of US, GB, DE, FR, JP, CA, IT, ES, IN, MX" },
    },
    required: ["asin"],
  },
};

export async function lookupKeepaProduct(asin, apiKey, domain = "US") {
  if (!apiKey) throw new Error("KEEPA_API_KEY is not configured on the server.");
  if (!asin || typeof asin !== "string") throw new Error("A valid ASIN is required.");

  const domainCode = DOMAIN_CODES[(domain || "US").toUpperCase()] || 1;
  const url = `https://api.keepa.com/product?key=${encodeURIComponent(apiKey)}&domain=${domainCode}&asin=${encodeURIComponent(asin)}&history=1`;

  const res = await fetch(url);
  if (!res.ok) throw new Error(`Keepa API error (HTTP ${res.status})`);
  const data = await res.json();
  if (data.error) throw new Error(`Keepa error: ${typeof data.error === "string" ? data.error : JSON.stringify(data.error)}`);

  const product = data.products && data.products[0];
  if (!product) throw new Error(`No Keepa data found for ASIN "${asin}" — check the ASIN and marketplace.`);

  const csv = product.csv || [];
  const amazonPrice = parseSeries(csv, CSV_AMAZON);
  const newPrice = parseSeries(csv, CSV_NEW);
  const priceHistory = amazonPrice.length ? amazonPrice : newPrice;
  const buyBoxHistory = parseSeries(csv, CSV_BUY_BOX);
  const salesRankHistory = parseSeries(csv, CSV_SALES_RANK, { isPrice: false });

  return {
    asin: product.asin,
    title: product.title || null,
    brand: product.brand || null,
    categoryTree: (product.categoryTree || []).map((c) => c.name),
    currentPrice: priceHistory.length ? priceHistory[priceHistory.length - 1].value : null,
    avgPrice30: avgSince(priceHistory, 30),
    avgPrice90: avgSince(priceHistory, 90),
    avgPrice180: avgSince(priceHistory, 180),
    currentBuyBoxPrice: buyBoxHistory.length ? buyBoxHistory[buyBoxHistory.length - 1].value : null,
    currentSalesRank: salesRankHistory.length ? salesRankHistory[salesRankHistory.length - 1].value : null,
    avgSalesRank30: avgSince(salesRankHistory, 30, { asInt: true }),
    avgSalesRank90: avgSince(salesRankHistory, 90, { asInt: true }),
    avgSalesRank180: avgSince(salesRankHistory, 180, { asInt: true }),
    priceHistory,
    salesRankHistory,
    buyBoxHistory,
    tokensLeft: data.tokensLeft ?? null,
  };
}
