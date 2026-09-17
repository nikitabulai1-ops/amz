"""Live web research layer for AMZ-VA.

IMPORTANT — read this before calling anything in this file:

This module does NOT perform web requests itself. `WebSearch` and `WebFetch`
are tools built into a Claude Code session (this repo's "AMZ-VA" agent) — they
are not network APIs a plain Python process can call, and this backend has no
API key or browser of its own to search or fetch pages with (by design — see
AMZ-VA/research/README.md).

The actual flow is:
  1. Claude calls its own WebSearch(query) or WebFetch(url) tool.
  2. Claude passes the raw result into the functions below (as `raw_results`
     / `raw_content`), which classify it into an explicit status, extract
     whatever structured fields can be honestly extracted, label every field
     with a confidence tag, cache the result under AMZ-VA/research/, and
     append an entry to the research log.

If a function is called without raw content, it returns status
NOT_PROVIDED — it never fabricates a search or a fetch, and it never
invents a value. It also refuses to process amazon.* URLs at all (see
AMAZON_DOMAIN_SUFFIXES below): live Amazon price/BSR/seller data is handled
by the existing Keepa integration (see main.py's /analyze endpoint) once
KEEPA_API_KEY is configured, not by this module.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/research", tags=["research"])

REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_DIR = REPO_ROOT / "AMZ-VA" / "research"
DEFAULT_CACHE_DIR = RESEARCH_DIR / "cache"
DEFAULT_LOG_PATH = RESEARCH_DIR / "logs" / "research.log"

AMAZON_DOMAIN_SUFFIXES = (
    "amazon.com", "amazon.co.uk", "amazon.de", "amazon.fr", "amazon.ca",
    "amazon.it", "amazon.es", "amazon.in", "amazon.co.jp", "amazon.com.mx",
    "amazon.com.au", "amazon.nl", "amazon.se", "amazon.pl", "amazon.com.br",
    "amazon.sg", "amazon.ae", "amazon.sa",
)

BLOCKED_PAGE_MARKERS = (
    "403 forbidden", "access denied", "captcha", "are you a human",
    "robot check", "verify you are a human", "request blocked",
    "unusual traffic", "cloudflare", "attention required",
)

PRICE_RE = re.compile(r"\$\s?(\d{1,6}(?:,\d{3})*(?:\.\d{1,2})?)")
ASIN_RE = re.compile(r"\b(B0[0-9A-Z]{8})\b")
UPC_EAN_RE = re.compile(r"\b(\d{12,13})\b")


# ============================================================
# Status / confidence enums
# ============================================================

class RetrievalStatus(str, Enum):
    """Outcome of a single search/fetch operation (not a data-confidence label)."""
    SUCCESS = "success"
    EMPTY = "empty"
    NOT_PROVIDED = "not_provided"
    INVALID_URL = "invalid_url"
    UNSUPPORTED_SOURCE = "unsupported_source"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"
    ERROR = "error"


class ConfidenceLabel(str, Enum):
    """Data-confidence label applied to each extracted field/value."""
    VERIFIED = "VERIFIED"
    CALCULATED = "CALCULATED"
    ASSUMED = "ASSUMED"
    ESTIMATED = "ESTIMATED"
    CONFLICTING = "CONFLICTING"
    UNAVAILABLE = "UNAVAILABLE"


# ============================================================
# Schema (requirement: PRODUCT / PRICING / SOURCE)
# ============================================================

class SourceRecord(BaseModel):
    source_name: str
    domain: Optional[str] = None
    url: Optional[str] = None
    retrieved_at: str
    query_or_input: str
    status: RetrievalStatus
    error: Optional[str] = None


class SearchHit(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None
    snippet: Optional[str] = None
    domain: Optional[str] = None


class WebSearchResult(BaseModel):
    query: str
    status: RetrievalStatus
    hits: list[SearchHit] = Field(default_factory=list)
    source: SourceRecord
    warnings: list[str] = Field(default_factory=list)
    cache_path: Optional[str] = None


class WebFetchResult(BaseModel):
    url: str
    status: RetrievalStatus
    extracted_text: Optional[str] = None
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    field_confidence: dict[str, ConfidenceLabel] = Field(default_factory=dict)
    source: SourceRecord
    warnings: list[str] = Field(default_factory=list)
    cache_path: Optional[str] = None


class ProductInfo(BaseModel):
    title: Optional[str] = None
    brand: Optional[str] = None
    asin: Optional[str] = None
    upc_ean: Optional[str] = None
    model: Optional[str] = None
    category: Optional[str] = None
    size_variation: Optional[str] = None
    field_confidence: dict[str, ConfidenceLabel] = Field(default_factory=dict)
    field_sources: dict[str, list[str]] = Field(default_factory=dict)


class PricingRecord(BaseModel):
    retailer: str
    url: Optional[str] = None
    price: Optional[float] = None
    sale_price: Optional[float] = None
    coupon: Optional[str] = None
    discount: Optional[str] = None
    shipping: Optional[str] = None
    availability: Optional[str] = None
    observed_at: str
    confidence: ConfidenceLabel


class ResearchResult(BaseModel):
    identifier: str
    product: ProductInfo
    pricing: list[PricingRecord] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)
    overall_status: RetrievalStatus
    conflicts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    generated_at: str
    cache_path: Optional[str] = None


class Finding(BaseModel):
    label: str
    value: str
    confidence: ConfidenceLabel
    source_url: Optional[str] = None
    source_name: Optional[str] = None


class MultiSourceResult(BaseModel):
    identifier: str
    findings: list[Finding] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    overall_status: RetrievalStatus
    generated_at: str
    cache_path: Optional[str] = None


# ============================================================
# Storage (cache + logs) — overridable so tests never touch AMZ-VA/research/
# ============================================================

@dataclass
class ResearchStorage:
    cache_dir: Path = DEFAULT_CACHE_DIR
    log_path: Path = DEFAULT_LOG_PATH

    def _slugify(self, text: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
        return slug[:60] or "unknown"

    def write_cache(self, identifier: str, payload: dict) -> Path:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        slug = self._slugify(identifier)
        dir_path = self.cache_dir / slug
        dir_path.mkdir(parents=True, exist_ok=True)
        existing = sorted(dir_path.glob(f"{date}__*.json"))
        seq = len(existing) + 1
        path = dir_path / f"{date}__{seq:02d}.json"
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    def append_log(self, entry: dict) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")


DEFAULT_STORAGE = ResearchStorage()


def _log(storage: ResearchStorage, function: str, input_desc: str, status: RetrievalStatus,
          cache_path: Optional[Path], error: Optional[str]) -> None:
    storage.append_log({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "function": function,
        "input": input_desc,
        "status": status.value,
        "cache_path": str(cache_path) if cache_path else None,
        "error": error,
    })


# ============================================================
# Shared helpers
# ============================================================

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def domain_of(url: str) -> Optional[str]:
    try:
        return urlparse(url).netloc.lower() or None
    except Exception:
        return None


def is_amazon_domain(url_or_domain: str) -> bool:
    d = (domain_of(url_or_domain) or url_or_domain or "").lower()
    d = d.lstrip("www.")
    return any(d == suf or d.endswith("." + suf) for suf in AMAZON_DOMAIN_SUFFIXES)


def validate_url(url: str) -> Optional[str]:
    """Returns an error message if the URL is invalid, else None."""
    if not url or not isinstance(url, str):
        return "URL is empty or not a string."
    try:
        parsed = urlparse(url)
    except Exception as e:
        return f"Malformed URL: {e}"
    if parsed.scheme not in ("http", "https"):
        return f"URL must use http or https (got '{parsed.scheme or 'none'}')."
    if not parsed.netloc:
        return "URL is missing a domain."
    return None


def _classify_tool_error(error: Optional[str]) -> Optional[RetrievalStatus]:
    """Maps a raw tool-call failure message (from Claude's own WebSearch/WebFetch
    call, when that call itself failed) to a RetrievalStatus. Returns None if
    error is falsy."""
    if not error:
        return None
    e = error.lower()
    if "timeout" in e or "timed out" in e:
        return RetrievalStatus.TIMEOUT
    if any(m in e for m in ("403", "forbidden", "blocked", "captcha", "denied")):
        return RetrievalStatus.BLOCKED
    return RetrievalStatus.ERROR


def _looks_blocked(text: str) -> bool:
    t = text.lower()
    return any(marker in t for marker in BLOCKED_PAGE_MARKERS)


def _extract_price(text: str) -> Optional[float]:
    m = PRICE_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _try_parse_json_block(text: str) -> Optional[dict]:
    """Best-effort: if the fetched/summarized content contains a JSON object
    (e.g. because WebFetch was asked to answer in JSON), parse it. Returns
    None on any failure rather than raising."""
    if not text:
        return None
    stripped = text.strip()
    # Strip markdown code fences if present.
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    candidate = fence_match.group(1) if fence_match else stripped
    brace_match = re.search(r"\{.*\}", candidate, re.DOTALL)
    if not brace_match:
        return None
    try:
        parsed = json.loads(brace_match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_fields_from_text(text: str) -> tuple[dict[str, Any], list[str]]:
    """Best-effort structured extraction from a page's fetched/summarized text.
    Returns (fields, warnings). Never guesses a numeric value — only what a
    JSON block or a clear $-amount regex actually contains."""
    warnings: list[str] = []
    parsed = _try_parse_json_block(text)
    if parsed is not None:
        return parsed, warnings

    fields: dict[str, Any] = {}
    price = _extract_price(text)
    if price is not None:
        fields["price"] = price
    else:
        warnings.append("No JSON block and no $-amount found in fetched text — "
                         "pricing fields could not be extracted.")
    asin_match = ASIN_RE.search(text)
    if asin_match:
        fields["asin"] = asin_match.group(1)
    return fields, warnings


# ============================================================
# 1. web_search
# ============================================================

def web_search(
    query: str,
    raw_results: Optional[list[dict]] = None,
    error: Optional[str] = None,
    storage: ResearchStorage = DEFAULT_STORAGE,
) -> WebSearchResult:
    """Normalize the raw output of a Claude WebSearch(query) tool call.

    raw_results: list of dicts as returned by WebSearch, flexibly matched on
      title/url/snippet key variants (title, url|link, snippet|description|text).
    error: pass this if the WebSearch tool call itself failed (e.g. you caught
      an exception) rather than returning results.
    """
    tool_error_status = _classify_tool_error(error)
    if tool_error_status is not None:
        result = WebSearchResult(
            query=query, status=tool_error_status,
            source=SourceRecord(
                source_name="web_search", domain=None, url=None,
                retrieved_at=_now(), query_or_input=query,
                status=tool_error_status, error=error,
            ),
            warnings=[f"WebSearch tool call failed: {error}"],
        )
    elif raw_results is None:
        status = RetrievalStatus.NOT_PROVIDED
        result = WebSearchResult(
            query=query, status=status,
            source=SourceRecord(
                source_name="web_search", domain=None, url=None,
                retrieved_at=_now(), query_or_input=query, status=status,
                error="No raw_results supplied. Call the WebSearch tool for "
                      "this query first, then pass its results here.",
            ),
            warnings=["This function only normalizes results already retrieved "
                      "by Claude's WebSearch tool — it does not search the web itself."],
        )
    elif len(raw_results) == 0:
        status = RetrievalStatus.EMPTY
        result = WebSearchResult(
            query=query, status=status,
            source=SourceRecord(
                source_name="web_search", domain=None, url=None,
                retrieved_at=_now(), query_or_input=query, status=status,
            ),
            warnings=["WebSearch returned zero results for this query."],
        )
    else:
        hits = []
        for r in raw_results:
            url = r.get("url") or r.get("link")
            hits.append(SearchHit(
                title=r.get("title"), url=url,
                snippet=r.get("snippet") or r.get("description") or r.get("text"),
                domain=domain_of(url) if url else None,
            ))
        status = RetrievalStatus.SUCCESS
        result = WebSearchResult(
            query=query, status=status, hits=hits,
            source=SourceRecord(
                source_name="web_search", domain=None, url=None,
                retrieved_at=_now(), query_or_input=query, status=status,
            ),
        )

    path = storage.write_cache(query, result.model_dump())
    result.cache_path = str(path)
    _log(storage, "web_search", query, result.status, path, error)
    return result


# ============================================================
# 2. web_fetch
# ============================================================

def web_fetch(
    url: str,
    raw_content: Optional[str] = None,
    error: Optional[str] = None,
    storage: ResearchStorage = DEFAULT_STORAGE,
) -> WebFetchResult:
    """Normalize the raw output of a Claude WebFetch(url, prompt) tool call.

    raw_content: the text Claude's WebFetch tool returned for this URL. For
      best extraction results, ask WebFetch to answer with a small JSON object
      (title/brand/price/sale_price/coupon/shipping/availability) — see
      AMZ-VA/research/README.md for the recommended prompt.
    error: pass this if the WebFetch tool call itself failed.
    """
    url_error = validate_url(url)
    domain = domain_of(url) if not url_error else None

    if url_error:
        status = RetrievalStatus.INVALID_URL
        result = WebFetchResult(
            url=url, status=status,
            source=SourceRecord(
                source_name=domain or "unknown", domain=domain, url=url,
                retrieved_at=_now(), query_or_input=url, status=status, error=url_error,
            ),
            warnings=[url_error],
        )
    elif is_amazon_domain(url):
        status = RetrievalStatus.UNSUPPORTED_SOURCE
        msg = ("Amazon product pages are not a supported source for this research "
               "layer. WebFetch cannot reliably or legitimately read live Amazon "
               "listing data (JS-rendered, bot-protected), and this tool must never "
               "guess Amazon pricing/BSR/seller data. Use the existing Keepa "
               "integration (backend/main.py GET /analyze/{asin}) once "
               "KEEPA_API_KEY is configured.")
        result = WebFetchResult(
            url=url, status=status,
            source=SourceRecord(
                source_name=domain or "amazon", domain=domain, url=url,
                retrieved_at=_now(), query_or_input=url, status=status, error=msg,
            ),
            warnings=[msg],
        )
    else:
        tool_error_status = _classify_tool_error(error)
        if tool_error_status is not None:
            result = WebFetchResult(
                url=url, status=tool_error_status,
                source=SourceRecord(
                    source_name=domain or "unknown", domain=domain, url=url,
                    retrieved_at=_now(), query_or_input=url,
                    status=tool_error_status, error=error,
                ),
                warnings=[f"WebFetch tool call failed: {error}"],
            )
        elif raw_content is None:
            status = RetrievalStatus.NOT_PROVIDED
            result = WebFetchResult(
                url=url, status=status,
                source=SourceRecord(
                    source_name=domain or "unknown", domain=domain, url=url,
                    retrieved_at=_now(), query_or_input=url, status=status,
                    error="No raw_content supplied. Call the WebFetch tool for "
                          "this URL first, then pass its answer text here.",
                ),
                warnings=["This function only normalizes content already retrieved "
                          "by Claude's WebFetch tool — it does not fetch pages itself."],
            )
        elif _looks_blocked(raw_content):
            status = RetrievalStatus.BLOCKED
            result = WebFetchResult(
                url=url, status=status, extracted_text=raw_content[:2000],
                source=SourceRecord(
                    source_name=domain or "unknown", domain=domain, url=url,
                    retrieved_at=_now(), query_or_input=url, status=status,
                    error="Fetched content looks like a bot-block/CAPTCHA page.",
                ),
                warnings=["Page content matched a known block/CAPTCHA pattern — "
                          "treat as unavailable, do not extract fields from it."],
            )
        else:
            fields, warns = _extract_fields_from_text(raw_content)
            confidence = {k: ConfidenceLabel.VERIFIED for k in fields}
            status = RetrievalStatus.SUCCESS
            result = WebFetchResult(
                url=url, status=status, extracted_text=raw_content[:4000],
                extracted_fields=fields, field_confidence=confidence,
                source=SourceRecord(
                    source_name=domain or "unknown", domain=domain, url=url,
                    retrieved_at=_now(), query_or_input=url, status=status,
                ),
                warnings=warns,
            )

    path = storage.write_cache(domain or url, result.model_dump())
    result.cache_path = str(path)
    _log(storage, "web_fetch", url, result.status, path, error or url_error)
    return result


# ============================================================
# 3 & 4. research_product / research_retailer_product
# ============================================================

def _merge_product_fields(product: ProductInfo, fields: dict, source_label: str,
                           confidence: ConfidenceLabel) -> None:
    field_map = {
        "title": "title", "brand": "brand", "asin": "asin",
        "upc": "upc_ean", "ean": "upc_ean", "upc_ean": "upc_ean",
        "model": "model", "category": "category",
        "size": "size_variation", "variation": "size_variation",
        "size_variation": "size_variation",
    }
    for raw_key, value in fields.items():
        target = field_map.get(raw_key)
        if not target or value in (None, ""):
            continue
        existing = getattr(product, target)
        if existing is None:
            setattr(product, target, value)
            product.field_confidence[target] = confidence
            product.field_sources[target] = [source_label]
        elif str(existing) != str(value):
            product.field_confidence[target] = ConfidenceLabel.CONFLICTING
            product.field_sources.setdefault(target, []).append(source_label)


def _build_pricing_record(retailer: str, url: Optional[str], fields: dict,
                            confidence: ConfidenceLabel) -> PricingRecord:
    return PricingRecord(
        retailer=retailer, url=url,
        price=fields.get("price"), sale_price=fields.get("sale_price"),
        coupon=fields.get("coupon"), discount=fields.get("discount"),
        shipping=fields.get("shipping"), availability=fields.get("availability"),
        observed_at=_now(), confidence=confidence,
    )


def _detect_price_conflicts(pricing: list[PricingRecord]) -> list[str]:
    conflicts = []
    priced = [p for p in pricing if p.price is not None]
    for i in range(len(priced)):
        for j in range(i + 1, len(priced)):
            a, b = priced[i], priced[j]
            if abs(a.price - b.price) > 0.01:
                conflicts.append(
                    f"Price conflict: {a.retailer} reports ${a.price:.2f} "
                    f"but {b.retailer} reports ${b.price:.2f} — both kept, "
                    "not resolved automatically."
                )
    return conflicts


def research_product(
    identifier: str,
    search_results: Optional[list[dict]] = None,
    fetched_pages: Optional[list[dict]] = None,
    storage: ResearchStorage = DEFAULT_STORAGE,
) -> ResearchResult:
    """Build a standardized PRODUCT/PRICING/SOURCE result for one product from
    already-gathered WebSearch hits and/or WebFetch page content.

    fetched_pages: list of {"url": str, "content": Optional[str], "error": Optional[str]}
    search_results: raw WebSearch-shaped hits (see web_search()).
    """
    product = ProductInfo()
    pricing: list[PricingRecord] = []
    sources: list[SourceRecord] = []
    warnings: list[str] = []

    if search_results is None and not fetched_pages:
        status = RetrievalStatus.NOT_PROVIDED
        result = ResearchResult(
            identifier=identifier, product=product, overall_status=status,
            generated_at=_now(),
            warnings=["No search_results or fetched_pages supplied. Run WebSearch "
                      "and/or WebFetch for this product first, then pass the raw "
                      "results in."],
        )
        path = storage.write_cache(identifier, result.model_dump())
        result.cache_path = str(path)
        _log(storage, "research_product", identifier, status, path, None)
        return result

    if search_results:
        sr = web_search(identifier, raw_results=search_results, storage=storage)
        sources.append(sr.source)
        warnings.extend(sr.warnings)
        for hit in sr.hits:
            if hit.snippet:
                price = _extract_price(hit.snippet)
                if price is not None:
                    pricing.append(_build_pricing_record(
                        retailer=hit.domain or "unknown", url=hit.url,
                        fields={"price": price}, confidence=ConfidenceLabel.ESTIMATED,
                    ))
            if hit.title:
                _merge_product_fields(product, {"title": hit.title},
                                       hit.url or "search", ConfidenceLabel.ASSUMED)

    for page in fetched_pages or []:
        url = page.get("url", "")
        fr = web_fetch(url, raw_content=page.get("content"), error=page.get("error"),
                        storage=storage)
        sources.append(fr.source)
        warnings.extend(fr.warnings)
        if fr.status == RetrievalStatus.SUCCESS and fr.extracted_fields:
            _merge_product_fields(product, fr.extracted_fields, url, ConfidenceLabel.VERIFIED)
            pricing.append(_build_pricing_record(
                retailer=fr.source.domain or url, url=url,
                fields=fr.extracted_fields, confidence=ConfidenceLabel.VERIFIED,
            ))

    conflicts = _detect_price_conflicts(pricing)

    if not sources:
        overall_status = RetrievalStatus.EMPTY
    elif all(s.status in (RetrievalStatus.ERROR, RetrievalStatus.BLOCKED,
                          RetrievalStatus.TIMEOUT, RetrievalStatus.INVALID_URL,
                          RetrievalStatus.UNSUPPORTED_SOURCE) for s in sources):
        overall_status = sources[0].status
    elif conflicts:
        overall_status = RetrievalStatus.SUCCESS  # data present, flagged via conflicts[]
    else:
        overall_status = RetrievalStatus.SUCCESS

    if not pricing and not any(product.model_dump(exclude={"field_confidence", "field_sources"}).values()):
        warnings.append("No product or pricing fields could be extracted from the "
                         "supplied sources — treat this product as UNAVAILABLE, "
                         "do not estimate.")

    result = ResearchResult(
        identifier=identifier, product=product, pricing=pricing, sources=sources,
        overall_status=overall_status, conflicts=conflicts, warnings=warnings,
        generated_at=_now(),
    )
    path = storage.write_cache(identifier, result.model_dump())
    result.cache_path = str(path)
    _log(storage, "research_product", identifier, overall_status, path, None)
    return result


def research_retailer_product(
    url: str,
    raw_content: Optional[str] = None,
    error: Optional[str] = None,
    storage: ResearchStorage = DEFAULT_STORAGE,
) -> ResearchResult:
    """Single-URL convenience wrapper around research_product for one retailer's
    product page (the fetched_pages=[...] path with exactly one page)."""
    return research_product(
        identifier=url,
        fetched_pages=[{"url": url, "content": raw_content, "error": error}],
        storage=storage,
    )


# ============================================================
# 5. research_multiple_sources
# ============================================================

def research_multiple_sources(
    identifier: str,
    sources_in: list[dict],
    storage: ResearchStorage = DEFAULT_STORAGE,
) -> MultiSourceResult:
    """Cross-check several already-gathered sources about the same question
    (not necessarily a priced product — e.g. "is Brand X gated on Amazon").

    sources_in: list of
      {"type": "search"|"fetch", "input": "<query or url>",
       "raw": <list[dict] for search, str for fetch>, "error": Optional[str],
       "label": Optional[str]}   # what this source is meant to confirm
    """
    findings: list[Finding] = []
    source_records: list[SourceRecord] = []
    warnings: list[str] = []

    if not sources_in:
        status = RetrievalStatus.NOT_PROVIDED
        result = MultiSourceResult(
            identifier=identifier, overall_status=status, generated_at=_now(),
            warnings=["No sources supplied. Gather WebSearch/WebFetch results "
                      "first, then pass them in as sources_in."],
        )
        path = storage.write_cache(identifier, result.model_dump())
        result.cache_path = str(path)
        _log(storage, "research_multiple_sources", identifier, status, path, None)
        return result

    for src in sources_in:
        kind = src.get("type")
        label = src.get("label", "raw_excerpt")
        if kind == "search":
            sr = web_search(src.get("input", ""), raw_results=src.get("raw"),
                             error=src.get("error"), storage=storage)
            source_records.append(sr.source)
            warnings.extend(sr.warnings)
            for hit in sr.hits:
                if hit.snippet:
                    findings.append(Finding(
                        label=label, value=hit.snippet[:500],
                        confidence=ConfidenceLabel.ASSUMED,
                        source_url=hit.url, source_name=hit.domain,
                    ))
        elif kind == "fetch":
            fr = web_fetch(src.get("input", ""), raw_content=src.get("raw"),
                            error=src.get("error"), storage=storage)
            source_records.append(fr.source)
            warnings.extend(fr.warnings)
            if fr.status == RetrievalStatus.SUCCESS:
                if fr.extracted_fields:
                    for k, v in fr.extracted_fields.items():
                        findings.append(Finding(
                            label=f"{label}:{k}", value=str(v),
                            confidence=ConfidenceLabel.VERIFIED,
                            source_url=fr.url, source_name=fr.source.domain,
                        ))
                elif fr.extracted_text:
                    findings.append(Finding(
                        label=label, value=fr.extracted_text[:500],
                        confidence=ConfidenceLabel.VERIFIED,
                        source_url=fr.url, source_name=fr.source.domain,
                    ))
        else:
            warnings.append(f"Unknown source type '{kind}' — skipped. Use 'search' or 'fetch'.")

    conflicts: list[str] = []
    by_label: dict[str, list[Finding]] = {}
    for f in findings:
        by_label.setdefault(f.label, []).append(f)
    for label, group in by_label.items():
        distinct_values = {g.value for g in group}
        if len(distinct_values) > 1:
            conflicts.append(
                f"Conflicting values for '{label}': " +
                "; ".join(f"{v!r} ({g.source_name or 'unknown'})"
                          for g, v in zip(group, distinct_values))
            )
            for g in group:
                g.confidence = ConfidenceLabel.CONFLICTING

    if not source_records:
        overall_status = RetrievalStatus.EMPTY
    elif all(s.status != RetrievalStatus.SUCCESS for s in source_records):
        overall_status = source_records[0].status
    else:
        overall_status = RetrievalStatus.SUCCESS

    if not findings:
        warnings.append("No findings could be extracted from any source — "
                         "treat this as UNAVAILABLE, do not estimate.")

    result = MultiSourceResult(
        identifier=identifier, findings=findings, sources=source_records,
        conflicts=conflicts, warnings=warnings, overall_status=overall_status,
        generated_at=_now(),
    )
    path = storage.write_cache(identifier, result.model_dump())
    result.cache_path = str(path)
    _log(storage, "research_multiple_sources", identifier, overall_status, path, None)
    return result


# ============================================================
# FastAPI router
# ============================================================

class WebSearchRequest(BaseModel):
    query: str
    raw_results: Optional[list[dict]] = None
    error: Optional[str] = None


class WebFetchRequest(BaseModel):
    url: str
    raw_content: Optional[str] = None
    error: Optional[str] = None


class ResearchProductRequest(BaseModel):
    identifier: str
    search_results: Optional[list[dict]] = None
    fetched_pages: Optional[list[dict]] = None


class ResearchRetailerProductRequest(BaseModel):
    url: str
    raw_content: Optional[str] = None
    error: Optional[str] = None


class ResearchMultipleSourcesRequest(BaseModel):
    identifier: str
    sources: list[dict]


@router.post("/web-search", response_model=WebSearchResult)
def web_search_endpoint(req: WebSearchRequest) -> WebSearchResult:
    return web_search(req.query, raw_results=req.raw_results, error=req.error)


@router.post("/web-fetch", response_model=WebFetchResult)
def web_fetch_endpoint(req: WebFetchRequest) -> WebFetchResult:
    return web_fetch(req.url, raw_content=req.raw_content, error=req.error)


@router.post("/product", response_model=ResearchResult)
def research_product_endpoint(req: ResearchProductRequest) -> ResearchResult:
    return research_product(req.identifier, search_results=req.search_results,
                             fetched_pages=req.fetched_pages)


@router.post("/retailer-product", response_model=ResearchResult)
def research_retailer_product_endpoint(req: ResearchRetailerProductRequest) -> ResearchResult:
    return research_retailer_product(req.url, raw_content=req.raw_content, error=req.error)


@router.post("/multi", response_model=MultiSourceResult)
def research_multiple_sources_endpoint(req: ResearchMultipleSourcesRequest) -> MultiSourceResult:
    return research_multiple_sources(req.identifier, req.sources)


# ============================================================
# CLI — lets Claude invoke this from Bash after calling WebSearch/WebFetch
# ============================================================

def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="AMZ-VA research layer CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("web-search")
    p.add_argument("--query", required=True)
    p.add_argument("--raw-file", help="JSON file: list of {title,url,snippet}")

    p = sub.add_parser("web-fetch")
    p.add_argument("--url", required=True)
    p.add_argument("--content-file", help="Text file with WebFetch's returned answer")

    p = sub.add_parser("research-product")
    p.add_argument("--identifier", required=True)
    p.add_argument("--search-file", help="JSON file: list of {title,url,snippet}")
    p.add_argument("--fetched-file", help="JSON file: list of {url,content,error}")

    p = sub.add_parser("research-retailer-product")
    p.add_argument("--url", required=True)
    p.add_argument("--content-file")

    p = sub.add_parser("research-multi")
    p.add_argument("--identifier", required=True)
    p.add_argument("--sources-file", required=True,
                    help="JSON file: list of {type,input,raw,label,error}")

    args = parser.parse_args()

    if args.command == "web-search":
        raw = json.loads(Path(args.raw_file).read_text()) if args.raw_file else None
        result = web_search(args.query, raw_results=raw)
    elif args.command == "web-fetch":
        content = Path(args.content_file).read_text() if args.content_file else None
        result = web_fetch(args.url, raw_content=content)
    elif args.command == "research-product":
        search = json.loads(Path(args.search_file).read_text()) if args.search_file else None
        fetched = json.loads(Path(args.fetched_file).read_text()) if args.fetched_file else None
        result = research_product(args.identifier, search_results=search, fetched_pages=fetched)
    elif args.command == "research-retailer-product":
        content = Path(args.content_file).read_text() if args.content_file else None
        result = research_retailer_product(args.url, raw_content=content)
    elif args.command == "research-multi":
        sources = json.loads(Path(args.sources_file).read_text())
        result = research_multiple_sources(args.identifier, sources)
    else:
        parser.error("unknown command")
        return

    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    _cli()
