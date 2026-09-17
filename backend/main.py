import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import httpx

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
KEEPA_BASE = "https://api.keepa.com"
SELLERAMP_BASE = "https://api.selleramp.com/sas/lookup/v2"


async def fetch_keepa(asin: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{KEEPA_BASE}/product",
            params={"key": KEEPA_API_KEY, "domain": 1, "asin": asin, "stats": 180},
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("products"):
            return {}
        product = data["products"][0]
        stats = product.get("stats", {})
        return {
            "title": product.get("title", ""),
            "brand": product.get("brand", ""),
            "salesRankCurrent": product.get("salesRankReference", -1),
            "salesRankAvg30": stats.get("salesRankReference", {}).get("avg30", [None])
            if isinstance(stats.get("salesRankReference"), dict)
            else None,
            "currentPrice": _keepa_price(stats, "current", 0),
            "avgPrice30": _keepa_price(stats, "avg30", 0),
            "avgPrice90": _keepa_price(stats, "avg90", 0),
            "monthlySold": product.get("monthlySold", None),
            "numberOfOffers": product.get("numberOfOffers", None),
            "category": product.get("categoryTree", [{}])[-1].get("name", "")
            if product.get("categoryTree")
            else "",
        }


def _keepa_price(stats: dict, key: str, index: int):
    try:
        val = stats.get(key, [])
        if isinstance(val, list) and len(val) > index and val[index] is not None:
            return val[index] / 100
    except (TypeError, IndexError):
        pass
    return None


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
    if not KEEPA_API_KEY or not SELLERAMP_API_KEY:
        raise HTTPException(500, "API keys not configured. Copy .env.example to .env and add your keys.")

    errors = {}
    keepa_data = {}
    selleramp_data = {}

    try:
        keepa_data = await fetch_keepa(asin)
    except httpx.HTTPStatusError as e:
        errors["keepa"] = f"HTTP {e.response.status_code}"
    except Exception as e:
        errors["keepa"] = str(e)

    try:
        selleramp_data = await fetch_selleramp(asin, cost)
    except httpx.HTTPStatusError as e:
        errors["selleramp"] = f"HTTP {e.response.status_code}"
    except Exception as e:
        errors["selleramp"] = str(e)

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
