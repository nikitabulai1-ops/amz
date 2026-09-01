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
import inventory
import poa
import ppc
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
