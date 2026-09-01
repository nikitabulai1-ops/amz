"""Inventory velocity, reorder point, and purchase-order sizing."""

import math
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/inventory", tags=["inventory"])


class SkuInventory(BaseModel):
    sku: str
    on_hand_units: int = Field(..., ge=0)
    units_incoming: int = Field(0, ge=0, description="Already-placed POs not yet received")
    avg_daily_sales: float = Field(..., gt=0, description="Trailing 30/60-day average units/day")
    lead_time_days: int = Field(..., ge=0, description="Supplier production + freight time to FBA-received")
    safety_stock_days: int = Field(14, ge=0, description="Buffer days on top of lead time")
    review_period_days: int = Field(0, ge=0, description="Days until you'd place the NEXT order after this one")
    supplier_moq: Optional[int] = Field(None, ge=1, description="Supplier minimum order quantity")
    case_pack_qty: Optional[int] = Field(None, ge=1, description="Round PO up to a multiple of this")


class SkuReorderResult(BaseModel):
    sku: str
    days_of_cover: Optional[float]
    reorder_point_units: float
    reorder_now: bool
    stockout_risk: bool
    projected_stockout_date: Optional[date]
    reorder_by_date: date
    suggested_po_qty: int
    notes: list[str]


class InventoryReorderRequest(BaseModel):
    skus: list[SkuInventory]
    as_of: Optional[date] = None


class InventoryReorderResponse(BaseModel):
    as_of: date
    results: list[SkuReorderResult]
    action_needed_now: list[str]


def _round_up(qty: float, multiple: Optional[int]) -> int:
    qty = math.ceil(qty)
    if multiple and multiple > 1:
        qty = math.ceil(qty / multiple) * multiple
    return max(qty, 0)


def evaluate_sku(s: SkuInventory, as_of: date) -> SkuReorderResult:
    notes: list[str] = []

    days_of_cover = s.on_hand_units / s.avg_daily_sales
    reorder_point = s.avg_daily_sales * (s.lead_time_days + s.safety_stock_days)
    reorder_now = s.on_hand_units <= reorder_point
    stockout_risk = days_of_cover < s.lead_time_days

    projected_stockout_date = as_of + timedelta(days=math.floor(days_of_cover))
    days_until_must_order = max(days_of_cover - s.lead_time_days - s.safety_stock_days, 0)
    reorder_by_date = as_of + timedelta(days=math.floor(days_until_must_order))

    horizon_days = s.lead_time_days + s.safety_stock_days + s.review_period_days
    target_units = s.avg_daily_sales * horizon_days
    raw_qty = target_units - s.on_hand_units - s.units_incoming
    suggested_po_qty = _round_up(raw_qty, s.case_pack_qty)

    if s.supplier_moq and 0 < suggested_po_qty < s.supplier_moq:
        notes.append(
            f"Calculated need ({suggested_po_qty}) is below supplier MOQ ({s.supplier_moq}). "
            f"Order the MOQ and eat the extra carrying cost, or push the review period out."
        )
        suggested_po_qty = _round_up(s.supplier_moq, s.case_pack_qty)

    if stockout_risk:
        notes.append(
            f"Days of cover ({days_of_cover:.1f}) is less than lead time ({s.lead_time_days}d) — "
            "you will stock out before a reorder placed today arrives. Expedite freight or air-ship a partial PO."
        )
    elif reorder_now:
        notes.append("At or below reorder point — place the PO now.")
    else:
        notes.append(f"Healthy — {days_of_cover - s.lead_time_days - s.safety_stock_days:.1f} days of slack before you must order.")

    return SkuReorderResult(
        sku=s.sku,
        days_of_cover=round(days_of_cover, 1),
        reorder_point_units=round(reorder_point, 1),
        reorder_now=reorder_now,
        stockout_risk=stockout_risk,
        projected_stockout_date=projected_stockout_date,
        reorder_by_date=reorder_by_date,
        suggested_po_qty=suggested_po_qty,
        notes=notes,
    )


@router.post("/reorder", response_model=InventoryReorderResponse)
def reorder(req: InventoryReorderRequest) -> InventoryReorderResponse:
    as_of = req.as_of or date.today()
    results = [evaluate_sku(s, as_of) for s in req.skus]
    action_needed_now = [r.sku for r in results if r.reorder_now or r.stockout_risk]
    return InventoryReorderResponse(as_of=as_of, results=results, action_needed_now=action_needed_now)
