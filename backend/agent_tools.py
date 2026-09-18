"""Bridges LLM tool-calling to the existing FBA calculator endpoints.

Each entry maps a tool name the model can call to the Pydantic request model
that validates its arguments and the plain function that does the work. The
functions are the same ones FastAPI routes to for the HTTP endpoints — we
call them directly rather than round-tripping through HTTP.
"""

import json
from typing import Any, Callable

from pydantic import BaseModel

import economics
import google_client
import inventory
import keepa_client
import poa
import ppc
import research
import sourcing

_REGISTRY: dict[str, tuple[type[BaseModel], Callable[[BaseModel], BaseModel], str]] = {
    "calculate_unit_economics": (
        economics.EconomicsRequest,
        economics.calculate,
        "Calculate landed cost, Amazon referral/FBA fulfillment/storage fees, net margin, ROI, "
        "breakeven sell price, and TACoS for one SKU/unit.",
    ),
    "plan_inventory_reorder": (
        inventory.InventoryReorderRequest,
        inventory.reorder,
        "Given on-hand units, sales velocity, lead time, and safety stock for one or more SKUs, "
        "compute reorder points, days of cover, stockout risk, and suggested PO quantities.",
    ),
    "audit_ppc_campaigns": (
        ppc.PpcAuditRequest,
        ppc.audit,
        "Audit PPC campaign spend/sales/clicks/impressions/orders and get ACoS, TACoS, CTR, CVR, "
        "CPC, ROAS, and kill/trim/healthy verdicts with a wasted-spend total.",
    ),
    "evaluate_sourcing_risk": (
        sourcing.SourcingRequest,
        sourcing.evaluate,
        "Screen a product idea for hazmat/meltable/gated-category keywords, Brand Registry/IP risk, "
        "competitive saturation, and BSR trend from a historical BSR series.",
    ),
    "draft_poa": (
        poa.PoaRequest,
        poa.draft,
        "Draft a templated Plan of Action (Root Cause / Corrective / Preventive) for an Amazon "
        "policy or account-health notice, with required attachments per violation type.",
    ),
    "web_search": (
        research.WebSearchRequest,
        research.web_search_endpoint,
        "Normalize web search results into a labeled, cached record. This does NOT search the "
        "web itself — it only classifies/caches results already retrieved by a live web-search "
        "tool. If raw_results is omitted, returns status not_provided rather than guessing. "
        "This runtime has no live web access, so calling it without raw_results will always "
        "come back empty — say so plainly rather than presenting a guess as a fact.",
    ),
    "web_fetch": (
        research.WebFetchRequest,
        research.web_fetch_endpoint,
        "Normalize the content of one fetched web page into labeled, cached fields. Does NOT "
        "fetch pages itself — requires raw_content already retrieved by a live web-fetch tool. "
        "Refuses to process amazon.* URLs (use the Keepa integration for Amazon data instead). "
        "This runtime has no live web access, so calling it without raw_content will always "
        "come back empty — say so plainly rather than presenting a guess as a fact.",
    ),
    "research_product": (
        research.ResearchProductRequest,
        research.research_product_endpoint,
        "Build a standardized PRODUCT/PRICING/SOURCE research record for one product from "
        "already-gathered search_results and/or fetched_pages (see web_search/web_fetch). "
        "Flags conflicting prices across sources instead of picking one.",
    ),
    "research_retailer_product": (
        research.ResearchRetailerProductRequest,
        research.research_retailer_product_endpoint,
        "Single-URL version of research_product for one retailer's product page, from "
        "already-fetched raw_content. Refuses amazon.* URLs.",
    ),
    "research_multiple_sources": (
        research.ResearchMultipleSourcesRequest,
        research.research_multiple_sources_endpoint,
        "Cross-check several already-gathered search/fetch sources about the same question "
        "(e.g. a policy or gating check, not necessarily a priced product) and flag disagreements "
        "between sources instead of resolving them silently.",
    ),
    "lookup_keepa_product": (
        keepa_client.KeepaLookupRequest,
        keepa_client.fetch_keepa_product_sync,
        "Look up real Keepa data for one ASIN: current/avg price (30/90/180d), current New price, "
        "current Buy Box price, current/avg BSR, price/BSR/Buy Box history, category, and Keepa "
        "quota remaining. Requires KEEPA_API_KEY configured in the environment — returns "
        "status=missing_api_key (not a guess) if it isn't set. Domain defaults to US.",
    ),
    "upload_file_to_drive": (
        google_client.DriveUploadRequest,
        google_client.upload_file_to_drive,
        "Upload a local file to Google Drive. Requires confirmed=true — the owner must have "
        "explicitly approved this specific upload in this conversation first; otherwise this "
        "returns status=approval_required and uploads nothing. Requires Google authorization "
        "already completed via backend/google_auth_setup.py (returns status=missing_token if not).",
    ),
    "find_drive_files": (
        google_client.DriveFindRequest,
        google_client.find_drive_files,
        "List/search files this app can see in Google Drive. Read-only, no approval needed. Uses "
        "the drive.file scope, so this can only see files this app created or that were explicitly "
        "opened with it — NOT the owner's whole Drive. An empty result may just mean the file "
        "exists but was never shared with this app.",
    ),
    "create_google_doc": (
        google_client.GoogleDocCreateRequest,
        google_client.create_google_doc,
        "Create a Google Doc from an already-drafted local text/Markdown file. Requires "
        "confirmed=true after explicit owner approval; otherwise returns status=approval_required.",
    ),
    "create_google_sheet": (
        google_client.GoogleSheetCreateRequest,
        google_client.create_google_sheet,
        "Create a Google Sheet from an already-existing local CSV file (e.g. an export of the deal "
        "tracker). Requires confirmed=true after explicit owner approval.",
    ),
    "append_sheet_rows": (
        google_client.SheetAppendRequest,
        google_client.append_sheet_rows,
        "Append rows to an existing Google Sheet this app has access to. Requires confirmed=true "
        "after explicit owner approval.",
    ),
    "read_sheet_values": (
        google_client.SheetReadRequest,
        google_client.read_sheet_values,
        "Read values from an existing Google Sheet this app has access to. Read-only, no approval "
        "needed — but only works for sheets created by this app or otherwise explicitly shared "
        "with it (drive.file scope limitation).",
    ),
    "update_sheet_values": (
        google_client.SheetUpdateRequest,
        google_client.update_sheet_values,
        "Overwrite a specific range of values in an existing Google Sheet. Requires confirmed=true "
        "after explicit owner approval.",
    ),
}


def _tool_schema(name: str, model: type[BaseModel], description: str) -> dict:
    schema = model.model_json_schema()
    schema.pop("title", None)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema,
        },
    }


TOOL_SCHEMAS = [_tool_schema(name, model, desc) for name, (model, _, desc) in _REGISTRY.items()]


def dispatch_tool(name: str, arguments: dict[str, Any]) -> dict:
    if name not in _REGISTRY:
        return {"error": f"Unknown tool '{name}'. Available tools: {', '.join(_REGISTRY)}"}

    model_cls, fn, _ = _REGISTRY[name]
    try:
        req = model_cls(**arguments)
    except Exception as e:
        return {"error": f"Invalid arguments for {name}: {e}"}

    try:
        result = fn(req)
    except Exception as e:
        return {"error": f"{name} failed: {e}"}

    return json.loads(result.model_dump_json())
