import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import httpx

import keepa_client
from agent import router as agent_router
from economics import router as economics_router
from inventory import router as inventory_router
from ppc import router as ppc_router
from research import router as research_router
from sourcing import router as sourcing_router
from poa import router as poa_router

load_dotenv()

app = FastAPI(title="Amazon FBA Operations Manager")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(economics_router)
app.include_router(inventory_router)
app.include_router(ppc_router)
app.include_router(research_router)
app.include_router(sourcing_router)
app.include_router(poa_router)
app.include_router(agent_router)

KEEPA_API_KEY = os.getenv("KEEPA_API_KEY")
SELLERAMP_API_KEY = os.getenv("SELLERAMP_API_KEY")
SELLERAMP_BASE = "https://api.selleramp.com/sas/lookup/v2"


def _keepa_result_to_analyze_shape(r: keepa_client.KeepaProductData) -> dict:
    """Maps the canonical KeepaProductData onto the /analyze response shape.

    Keeps the field names the Chrome extension (extension/content.js)
    already reads (title, brand, category, salesRankCurrent, currentPrice,
    avgPrice30, avgPrice90) so it keeps working unmodified. Drops
    monthlySold/numberOfOffers, which the old implementation read from
    unverified/likely-incorrect Keepa field names (see the Keepa
    integration audit) — the extension already guards both with
    `!= null` checks, so it simply omits those two rows now instead of
    showing wrong data. Adds the richer fields (Buy Box, New price,
    history series, status/warnings) alongside for anything that wants them.
    """
    current_price = r.current_amazon_price if r.current_amazon_price is not None else r.current_new_price
    return {
        "title": r.title,
        "brand": r.brand,
        "category": r.category_tree[-1] if r.category_tree else None,
        "salesRankCurrent": r.current_bsr,
        "currentPrice": current_price,
        "avgPrice30": r.avg_price_30,
        "avgPrice90": r.avg_price_90,
        "avgPrice180": r.avg_price_180,
        "currentNewPrice": r.current_new_price,
        "currentBuyBoxPrice": r.current_buy_box_price,
        "avgSalesRank30": r.avg_bsr_30,
        "avgSalesRank90": r.avg_bsr_90,
        "avgSalesRank180": r.avg_bsr_180,
        "priceHistory": [p.model_dump() for p in r.price_history],
        "salesRankHistory": [p.model_dump() for p in r.bsr_history],
        "buyBoxHistory": [p.model_dump() for p in r.buy_box_history],
        "tokensLeft": r.tokens_left,
        "status": r.status.value,
        "warnings": r.warnings,
    }


async def fetch_selleramp(asin: str, cost: float = 0) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            SELLERAMP_BASE,
            params={"asin": asin, "cost": cost},
            headers={"Authorization": f"Bearer {SELLERAMP_API_KEY}",
                      "Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


@app.get("/analyze/{asin}")
async def analyze(asin: str, cost: float = 0):
    """Keepa and SellerAmp are independent — one being unconfigured or failing
    never prevents the other from running. An unavailable service is marked
    plainly in `errors`, never silently left out or backfilled with a guess."""
    errors: dict[str, str] = {}
    keepa_data: dict = {}
    selleramp_data: dict = {}

    if KEEPA_API_KEY:
        try:
            keepa_result = await keepa_client.fetch_keepa_product(asin, api_key=KEEPA_API_KEY)
            keepa_data = _keepa_result_to_analyze_shape(keepa_result)
            if keepa_result.status != keepa_client.KeepaStatus.SUCCESS:
                errors["keepa"] = keepa_result.error or keepa_result.status.value
        except Exception as e:
            errors["keepa"] = str(e)
    else:
        errors["keepa"] = "KEEPA_API_KEY not configured. Copy .env.example to .env and add your key."

    if SELLERAMP_API_KEY:
        try:
            selleramp_data = await fetch_selleramp(asin, cost)
        except httpx.HTTPStatusError as e:
            errors["selleramp"] = f"HTTP {e.response.status_code}"
        except Exception as e:
            errors["selleramp"] = str(e)
    else:
        errors["selleramp"] = "SELLERAMP_API_KEY not configured. Copy .env.example to .env and add your key."

    return {
        "asin": asin,
        "keepa": keepa_data,
        "selleramp": selleramp_data,
        "errors": errors if errors else None,
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
