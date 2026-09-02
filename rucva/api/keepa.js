// Serverless endpoint backing the Sourcing Assistant's "Product History Lookup"
// UI. Keeps KEEPA_API_KEY server-side, same pattern as api/chat.js.

import { lookupKeepaProduct } from "./_keepa.js";

export default async function handler(req, res) {
  if (req.method !== "GET") {
    res.status(405).json({ error: "GET only" });
    return;
  }

  const asin = (req.query.asin || "").toString().trim();
  const domain = (req.query.domain || "US").toString().trim();
  if (!asin) {
    res.status(400).json({ error: "asin query parameter is required" });
    return;
  }

  try {
    const result = await lookupKeepaProduct(asin, process.env.KEEPA_API_KEY, domain);
    res.status(200).json(result);
  } catch (e) {
    const status = /not configured/.test(e.message) ? 500 : /No Keepa data/.test(e.message) ? 404 : 502;
    res.status(status).json({ error: e.message });
  }
}
