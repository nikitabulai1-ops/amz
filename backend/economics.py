"""Unit economics: landed cost, Amazon fees, margin, ROI, and TACoS."""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

import fee_config as fc

router = APIRouter(prefix="/economics", tags=["economics"])


class EconomicsRequest(BaseModel):
    sell_price: float = Field(..., gt=0, description="Current Amazon sell price")
    unit_cost: float = Field(..., ge=0, description="Product cost per unit (COGS)")
    shipping_to_fba_per_unit: float = Field(0, ge=0, description="Freight/prep cost to land one unit at FBA")
    other_per_unit_cost: float = Field(0, ge=0, description="Any other per-unit cost (poly bag, labels, inspection, etc.)")

    category: str = Field("default", description="Category key from fee_config.REFERRAL_FEE_TABLE")
    referral_fee_pct_override: Optional[float] = Field(None, ge=0, le=1, description="Override referral fee % (0-1)")

    size_tier: str = Field(
        "small_standard",
        description="small_standard | large_standard | small_bulky | large_bulky | extra_large",
    )
    weight_oz: Optional[float] = Field(None, gt=0, description="Unit weight in ounces (small_standard)")
    weight_lb: Optional[float] = Field(None, gt=0, description="Unit weight in pounds (large_standard/bulky/extra_large)")
    fulfillment_fee_override: Optional[float] = Field(None, ge=0, description="Override the computed FBA fulfillment fee")

    cubic_feet_per_unit: Optional[float] = Field(None, gt=0, description="Unit volume for storage-fee estimate")
    is_q4: bool = Field(False, description="Use Q4 peak storage rate")
    is_oversize: bool = Field(False, description="Use oversize storage rate instead of standard")
    months_in_storage: float = Field(1, ge=0, description="Months of storage to allocate per unit sold")
    storage_fee_per_cuft_override: Optional[float] = Field(None, ge=0)

    monthly_ad_spend: Optional[float] = Field(None, ge=0, description="For TACoS: total ad spend in the period")
    monthly_revenue: Optional[float] = Field(None, gt=0, description="For TACoS: total revenue in the same period")


class EconomicsResponse(BaseModel):
    sell_price: float
    landed_cost_per_unit: float
    referral_fee: float
    referral_fee_pct_applied: float
    fulfillment_fee: float
    storage_fee_allocated: float
    total_amazon_fees: float
    net_profit_per_unit: float
    margin_pct: float
    roi_pct: float
    breakeven_sell_price: float
    tacos_pct: Optional[float]
    warnings: list[str]


def referral_fee_for(category: str, price: float) -> float:
    rule = fc.REFERRAL_FEE_TABLE.get(category, fc.REFERRAL_FEE_TABLE["default"])
    if isinstance(rule, float):
        rate = rule
    else:
        rate = rule[-1][1]
        for ceiling, pct in rule:
            if ceiling is not None and price <= ceiling:
                rate = pct
                break
    fee = round(price * rate, 2)
    return max(fee, fc.MIN_REFERRAL_FEE), rate


def _price_bracket(price: float) -> str:
    if price < 10:
        return "under_10"
    if price <= 50:
        return "mid_10_50"
    return "over_50"


def small_standard_fee(weight_oz: float, price: float) -> float:
    bracket = _price_bracket(price)
    for max_oz in sorted(fc.SMALL_STANDARD_FEES):
        if weight_oz <= max_oz:
            return fc.SMALL_STANDARD_FEES[max_oz][bracket]
    heaviest = fc.SMALL_STANDARD_FEES[max(fc.SMALL_STANDARD_FEES)]
    return heaviest[bracket]


def large_standard_fee(weight_lb: float, price: float) -> float:
    bracket = "over_50" if price > 50 else "mid_10_50"
    for max_lb in sorted(fc.LARGE_STANDARD_FEES_BY_WEIGHT_LB):
        if weight_lb <= max_lb:
            return fc.LARGE_STANDARD_FEES_BY_WEIGHT_LB[max_lb][bracket]
    heaviest = fc.LARGE_STANDARD_FEES_BY_WEIGHT_LB[max(fc.LARGE_STANDARD_FEES_BY_WEIGHT_LB)]
    return heaviest[bracket]


def bulky_fee(size_tier: str, weight_lb: float) -> float:
    table = fc.BULKY_FEES_BY_WEIGHT_LB[size_tier]
    for max_lb in sorted(table):
        if weight_lb <= max_lb:
            return table[max_lb]
    return table[max(table)]


def extra_large_fee(weight_lb: float) -> float:
    table = fc.EXTRA_LARGE_FEES_BY_WEIGHT_LB
    for max_lb in sorted(table):
        if weight_lb <= max_lb:
            return table[max_lb]
    return table[max(table)]


def compute_fulfillment_fee(req: EconomicsRequest, warnings: list[str]) -> float:
    if req.fulfillment_fee_override is not None:
        return req.fulfillment_fee_override

    tier = req.size_tier.lower()
    if tier == "small_standard":
        if req.weight_oz is None:
            warnings.append("weight_oz required for small_standard; assuming 4oz default")
        base = small_standard_fee(req.weight_oz or 4, req.sell_price)
    elif tier == "large_standard":
        if req.weight_lb is None:
            warnings.append("weight_lb required for large_standard; assuming 1lb default")
        base = large_standard_fee(req.weight_lb or 1, req.sell_price)
    elif tier in ("small_bulky", "large_bulky"):
        if req.weight_lb is None:
            warnings.append(f"weight_lb required for {tier}; assuming 10lb default")
        base = bulky_fee(tier, req.weight_lb or 10)
    elif tier == "extra_large":
        if req.weight_lb is None:
            warnings.append("weight_lb required for extra_large; assuming 20lb default")
        base = extra_large_fee(req.weight_lb or 20)
        warnings.append(
            "Extra-Large items over 96in longest side or 130in length+girth incur an additional "
            f"${fc.OVERMAX_SURCHARGE_RANGE[0]:.2f}-${fc.OVERMAX_SURCHARGE_RANGE[1]:.2f} Overmax surcharge, not included here."
        )
    else:
        warnings.append(f"Unknown size_tier '{req.size_tier}', defaulting to small_standard 4oz")
        base = small_standard_fee(4, req.sell_price)

    return round(base * (1 + fc.FUEL_AND_LOGISTICS_SURCHARGE_PCT), 2)


def compute_storage_fee(req: EconomicsRequest) -> float:
    if req.storage_fee_per_cuft_override is not None:
        rate = req.storage_fee_per_cuft_override
    elif req.cubic_feet_per_unit is None:
        return 0.0
    else:
        size_key = "oversize" if req.is_oversize else "standard"
        period_key = "q4" if req.is_q4 else "jan_sep"
        rate = fc.STORAGE_FEE_PER_CUFT[size_key][period_key]

    if req.cubic_feet_per_unit is None:
        return 0.0
    return round(rate * req.cubic_feet_per_unit * req.months_in_storage, 2)


@router.post("/calculate", response_model=EconomicsResponse)
def calculate(req: EconomicsRequest) -> EconomicsResponse:
    warnings: list[str] = []

    landed_cost = round(req.unit_cost + req.shipping_to_fba_per_unit + req.other_per_unit_cost, 2)

    if req.referral_fee_pct_override is not None:
        referral_pct = req.referral_fee_pct_override
        referral_fee = max(round(req.sell_price * referral_pct, 2), fc.MIN_REFERRAL_FEE)
    else:
        referral_fee, referral_pct = referral_fee_for(req.category, req.sell_price)

    fulfillment_fee = compute_fulfillment_fee(req, warnings)
    storage_fee = compute_storage_fee(req)

    total_fees = round(referral_fee + fulfillment_fee + storage_fee, 2)
    net_profit = round(req.sell_price - landed_cost - total_fees, 2)
    margin_pct = round((net_profit / req.sell_price) * 100, 2) if req.sell_price else 0.0
    roi_pct = round((net_profit / landed_cost) * 100, 2) if landed_cost else 0.0
    breakeven_sell_price = round(
        (landed_cost + fulfillment_fee + storage_fee) / (1 - referral_pct), 2
    ) if referral_pct < 1 else None

    tacos_pct = None
    if req.monthly_ad_spend is not None and req.monthly_revenue:
        tacos_pct = round((req.monthly_ad_spend / req.monthly_revenue) * 100, 2)

    if margin_pct < 10:
        warnings.append(
            f"Margin is {margin_pct}% — under the 10% floor most operators use before ad spend eats the rest. "
            "Reprice, cut landed cost, or walk away."
        )
    if roi_pct < 20:
        warnings.append(f"ROI is {roi_pct}% — below the ~20% minimum most sourcing SOPs require to justify cash tied up in inventory.")

    return EconomicsResponse(
        sell_price=req.sell_price,
        landed_cost_per_unit=landed_cost,
        referral_fee=referral_fee,
        referral_fee_pct_applied=referral_pct,
        fulfillment_fee=fulfillment_fee,
        storage_fee_allocated=storage_fee,
        total_amazon_fees=total_fees,
        net_profit_per_unit=net_profit,
        margin_pct=margin_pct,
        roi_pct=roi_pct,
        breakeven_sell_price=breakeven_sell_price,
        tacos_pct=tacos_pct,
        warnings=warnings,
    )
