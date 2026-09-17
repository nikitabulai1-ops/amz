"""Canonical Keepa Product API client for AMZ-VA.

This ports the CSV-index parsing approach from `rucva/api/_keepa.js` (the
technically correct implementation identified in the Keepa integration
audit) to Python, so both the FastAPI backend and any future AMZ-VA research
tooling share ONE verified implementation instead of two incompatible ones.

Why CSV parsing instead of Keepa's `stats` object: same reasoning as the JS
version — `history=1` plus manual parsing of Keepa's documented CSV type
indices is cheaper in tokens and doesn't depend on getting the exact shape
of Keepa's `stats` object right. The indices used here are Keepa's publicly
documented CSV types:

    0  = Amazon price history
    1  = New (3rd-party) price history
    3  = Sales Rank (BSR) history
    18 = Buy Box price history

Each CSV series is a flat [time, value, time, value, ...] array in "Keepa
Time" minutes. Keepa uses `-1` (and sometimes `null`) as its documented
"no data at this point" sentinel — both are dropped during parsing, and a
genuine `0` is kept as a real value. Missing data becomes Python `None`
everywhere in this module; it is never converted into 0 or any other
placeholder.

The marketplace/domain code table below (DOMAIN_CODES) is ported as-is from
`rucva/api/_keepa.js` rather than re-derived, since this module has no way
to verify Keepa's official domain table independently (no live API access,
and inventing one would be exactly the kind of unverified-field problem the
Keepa audit flagged in backend/main.py's old implementation). If a
marketplace ever returns unexpected data, verify this table against Keepa's
own API documentation before trusting it further.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

import httpx
from pydantic import BaseModel, Field

KEEPA_BASE_URL = "https://api.keepa.com"

# Keepa Time (minutes) -> Unix time: unix_seconds = (keepaMinutes + OFFSET) * 60
KEEPA_EPOCH_OFFSET_MIN = 21564000

CSV_AMAZON = 0
CSV_NEW = 1
CSV_SALES_RANK = 3
CSV_BUY_BOX = 18

MISSING_SENTINEL = -1  # Keepa's documented "no data" marker in CSV series

# Ported as-is from rucva/api/_keepa.js — see module docstring caveat above.
DOMAIN_CODES: dict[str, int] = {
    "US": 1, "GB": 3, "DE": 4, "FR": 5, "JP": 6,
    "CA": 7, "IT": 8, "ES": 9, "IN": 10, "MX": 11,
}


class KeepaStatus(str, Enum):
    SUCCESS = "success"
    MISSING_API_KEY = "missing_api_key"
    INVALID_ASIN = "invalid_asin"
    INVALID_DOMAIN = "invalid_domain"
    HTTP_ERROR = "http_error"
    NETWORK_ERROR = "network_error"
    MALFORMED_RESPONSE = "malformed_response"
    KEEPA_ERROR = "keepa_error"
    NOT_FOUND = "not_found"


class SeriesPoint(BaseModel):
    date: str  # ISO-8601 UTC timestamp
    value: float


class KeepaProductData(BaseModel):
    asin: str
    domain: str
    domain_code: int
    status: KeepaStatus
    error: Optional[str] = None
    fetched_at: str

    title: Optional[str] = None
    brand: Optional[str] = None
    category_tree: Optional[list[str]] = None

    current_amazon_price: Optional[float] = None
    current_new_price: Optional[float] = None
    avg_price_30: Optional[float] = None
    avg_price_90: Optional[float] = None
    avg_price_180: Optional[float] = None

    current_buy_box_price: Optional[float] = None

    current_bsr: Optional[int] = None
    avg_bsr_30: Optional[int] = None
    avg_bsr_90: Optional[int] = None
    avg_bsr_180: Optional[int] = None

    price_history: list[SeriesPoint] = Field(default_factory=list)
    amazon_price_history: list[SeriesPoint] = Field(default_factory=list)
    new_price_history: list[SeriesPoint] = Field(default_factory=list)
    bsr_history: list[SeriesPoint] = Field(default_factory=list)
    buy_box_history: list[SeriesPoint] = Field(default_factory=list)

    tokens_left: Optional[int] = None
    warnings: list[str] = Field(default_factory=list)


def _round2(n: float) -> float:
    return round(n, 2)


def keepa_minutes_to_iso(keepa_minutes: float) -> str:
    unix_seconds = (keepa_minutes + KEEPA_EPOCH_OFFSET_MIN) * 60
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc).isoformat()


def _parse_series(csv_data: Optional[list], index: int, is_price: bool = True) -> list[SeriesPoint]:
    """Parse one Keepa CSV series into (date, value) points, in order.

    Drops Keepa's documented missing-data sentinel (-1) and null entries.
    A genuine 0 is kept — it is a real value, not a missing one.
    """
    if not csv_data or index >= len(csv_data):
        return []
    arr = csv_data[index]
    if not isinstance(arr, list):
        return []

    points: list[SeriesPoint] = []
    for i in range(0, len(arr) - 1, 2):
        t, v = arr[i], arr[i + 1]
        if v is None or v == MISSING_SENTINEL:
            continue
        try:
            value = _round2(v / 100) if is_price else float(v)
        except (TypeError, ValueError):
            continue
        points.append(SeriesPoint(date=keepa_minutes_to_iso(t), value=value))
    return points


def _avg_since(series: list[SeriesPoint], days: int, as_int: bool = False) -> Optional[float]:
    if not series:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    pts = [p for p in series if datetime.fromisoformat(p.date) >= cutoff]
    if not pts:
        return None
    mean = sum(p.value for p in pts) / len(pts)
    return round(mean) if as_int else _round2(mean)


async def fetch_keepa_product(
    asin: str,
    domain: str = "US",
    api_key: Optional[str] = None,
    timeout: float = 15.0,
    client: Optional[httpx.AsyncClient] = None,
) -> KeepaProductData:
    """Fetch and normalize one ASIN's Keepa product data.

    Never raises for an expected failure mode (missing key, bad ASIN, HTTP
    error, malformed response, network failure) — those all come back as a
    KeepaProductData with `status` set accordingly and every data field left
    as None/empty, never guessed. Only a genuinely unexpected exception
    (e.g. a bug in this function) would propagate.
    """
    api_key = api_key if api_key is not None else os.getenv("KEEPA_API_KEY")
    domain_label = (domain or "US").upper()
    domain_code = DOMAIN_CODES.get(domain_label)
    fetched_at = datetime.now(timezone.utc).isoformat()
    # Only used for the `asin` field on a failure result — the ASIN may be
    # invalid (None, wrong type) here, so this exists solely to keep the
    # response model's `asin: str` field satisfiable without crashing.
    asin_for_result = asin if isinstance(asin, str) else ""

    def _fail(status: KeepaStatus, error: str, tokens_left: Optional[int] = None) -> KeepaProductData:
        return KeepaProductData(
            asin=asin_for_result, domain=domain_label, domain_code=domain_code or 0,
            status=status, error=error, fetched_at=fetched_at, tokens_left=tokens_left,
        )

    if not api_key:
        return _fail(KeepaStatus.MISSING_API_KEY, "KEEPA_API_KEY is not configured.")
    if not asin or not isinstance(asin, str):
        return _fail(KeepaStatus.INVALID_ASIN, "A valid ASIN string is required.")
    if domain_code is None:
        return _fail(
            KeepaStatus.INVALID_DOMAIN,
            f"Unknown marketplace domain '{domain}'. Supported: {', '.join(sorted(DOMAIN_CODES))}.",
        )

    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=timeout)
    try:
        try:
            resp = await http_client.get(
                f"{KEEPA_BASE_URL}/product",
                params={"key": api_key, "domain": domain_code, "asin": asin, "history": 1},
            )
        except httpx.TimeoutException as e:
            return _fail(KeepaStatus.NETWORK_ERROR, f"Keepa request timed out: {e}")
        except httpx.RequestError as e:
            return _fail(KeepaStatus.NETWORK_ERROR, f"Network error contacting Keepa: {e}")

        if resp.status_code != 200:
            return _fail(KeepaStatus.HTTP_ERROR, f"Keepa API returned HTTP {resp.status_code}.")

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            return _fail(KeepaStatus.MALFORMED_RESPONSE, f"Keepa response was not valid JSON: {e}")

        if not isinstance(data, dict):
            return _fail(KeepaStatus.MALFORMED_RESPONSE, "Keepa response was not a JSON object.")

        tokens_left_raw = data.get("tokensLeft")
        tokens_left = tokens_left_raw if isinstance(tokens_left_raw, (int, float)) else None
        if tokens_left is not None:
            tokens_left = int(tokens_left)

        if data.get("error"):
            err = data["error"]
            msg = err if isinstance(err, str) else json.dumps(err)
            return _fail(KeepaStatus.KEEPA_ERROR, f"Keepa error: {msg}", tokens_left=tokens_left)

        products = data.get("products")
        if not isinstance(products, list) or not products:
            return _fail(
                KeepaStatus.NOT_FOUND,
                f"No Keepa data found for ASIN '{asin}' in domain '{domain_label}' — "
                "check the ASIN and marketplace.",
                tokens_left=tokens_left,
            )

        product = products[0]
        if not isinstance(product, dict):
            return _fail(KeepaStatus.MALFORMED_RESPONSE, "Keepa product entry was not a JSON object.",
                         tokens_left=tokens_left)

        warnings: list[str] = []
        csv_data = product.get("csv")
        if not isinstance(csv_data, list):
            csv_data = []
            warnings.append("No 'csv' array in Keepa response — price/rank/Buy Box history unavailable.")

        amazon_history = _parse_series(csv_data, CSV_AMAZON, is_price=True)
        new_history = _parse_series(csv_data, CSV_NEW, is_price=True)
        bsr_history = _parse_series(csv_data, CSV_SALES_RANK, is_price=False)
        buy_box_history = _parse_series(csv_data, CSV_BUY_BOX, is_price=True)
        price_history = amazon_history if amazon_history else new_history

        if not amazon_history and not new_history:
            warnings.append("No Amazon or New price history available for this ASIN/marketplace.")
        if not bsr_history:
            warnings.append("No sales-rank (BSR) history available for this ASIN/marketplace.")
        if not buy_box_history:
            warnings.append("No Buy Box price history available for this ASIN/marketplace.")

        category_tree: Optional[list[str]] = None
        raw_tree = product.get("categoryTree")
        if isinstance(raw_tree, list):
            names = [c.get("name") for c in raw_tree if isinstance(c, dict) and c.get("name")]
            category_tree = names or None

        return KeepaProductData(
            asin=product.get("asin") or asin,
            domain=domain_label,
            domain_code=domain_code,
            status=KeepaStatus.SUCCESS,
            fetched_at=fetched_at,
            title=product.get("title") or None,
            brand=product.get("brand") or None,
            category_tree=category_tree,
            current_amazon_price=amazon_history[-1].value if amazon_history else None,
            current_new_price=new_history[-1].value if new_history else None,
            avg_price_30=_avg_since(price_history, 30),
            avg_price_90=_avg_since(price_history, 90),
            avg_price_180=_avg_since(price_history, 180),
            current_buy_box_price=buy_box_history[-1].value if buy_box_history else None,
            current_bsr=int(bsr_history[-1].value) if bsr_history else None,
            avg_bsr_30=(_avg_since(bsr_history, 30, as_int=True)),
            avg_bsr_90=(_avg_since(bsr_history, 90, as_int=True)),
            avg_bsr_180=(_avg_since(bsr_history, 180, as_int=True)),
            price_history=price_history,
            amazon_price_history=amazon_history,
            new_price_history=new_history,
            bsr_history=bsr_history,
            buy_box_history=buy_box_history,
            tokens_left=tokens_left,
            warnings=warnings,
        )
    finally:
        if owns_client:
            await http_client.aclose()
