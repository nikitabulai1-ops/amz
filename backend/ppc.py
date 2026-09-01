"""PPC campaign audit: ACoS, TACoS, CTR, CVR, CPC, and wasted-spend flags."""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/ppc", tags=["ppc"])


class CampaignInput(BaseModel):
    name: str
    spend: float = Field(..., ge=0)
    sales: float = Field(..., ge=0, description="Attributed ad sales for this campaign")
    clicks: int = Field(..., ge=0)
    impressions: int = Field(..., ge=0)
    orders: int = Field(0, ge=0)


class CampaignAudit(BaseModel):
    name: str
    ctr_pct: Optional[float]
    cvr_pct: Optional[float]
    cpc: Optional[float]
    acos_pct: Optional[float]
    roas: Optional[float]
    verdict: str
    flags: list[str]


class PpcAuditRequest(BaseModel):
    campaigns: list[CampaignInput]
    target_acos_pct: float = Field(30, gt=0, description="Your break-even or target ACoS ceiling")
    min_clicks_for_zero_conversion_flag: int = Field(15, ge=1, description="Clicks with 0 orders above this = statistically dead")
    total_account_revenue: Optional[float] = Field(None, gt=0, description="For TACoS: total organic + ad revenue in the period")


class PpcAuditResponse(BaseModel):
    campaigns: list[CampaignAudit]
    total_ad_spend: float
    total_ad_sales: float
    blended_acos_pct: Optional[float]
    tacos_pct: Optional[float]
    wasted_spend_estimate: float
    summary: list[str]


def audit_campaign(c: CampaignInput, target_acos: float, zero_conv_click_floor: int) -> CampaignAudit:
    flags: list[str] = []

    ctr = round((c.clicks / c.impressions) * 100, 2) if c.impressions else None
    cvr = round((c.orders / c.clicks) * 100, 2) if c.clicks else None
    cpc = round(c.spend / c.clicks, 2) if c.clicks else None
    acos = round((c.spend / c.sales) * 100, 2) if c.sales else None
    roas = round(c.sales / c.spend, 2) if c.spend else None

    if c.clicks >= zero_conv_click_floor and c.orders == 0:
        flags.append(
            f"{c.clicks} clicks, 0 orders — statistically dead. Pause the keyword/placement, don't just lower bid."
        )
        verdict = "kill"
    elif acos is not None and acos > target_acos * 1.5:
        flags.append(f"ACoS {acos}% is 1.5x+ over your {target_acos}% target — bleeding margin.")
        verdict = "cut_or_restructure"
    elif acos is not None and acos > target_acos:
        flags.append(f"ACoS {acos}% is over your {target_acos}% target.")
        verdict = "trim_bids"
    elif c.spend == 0:
        flags.append("No spend recorded — check if this campaign is actually enabled.")
        verdict = "check_status"
    else:
        verdict = "healthy"

    if ctr is not None and ctr < 0.3:
        flags.append(f"CTR {ctr}% is weak for Sponsored Products — check main image, price competitiveness, and match type.")
    if cvr is not None and c.clicks >= zero_conv_click_floor and cvr < 5:
        flags.append(f"CVR {cvr}% is low — listing (images, price, reviews) may not convert even when clicked.")

    return CampaignAudit(
        name=c.name,
        ctr_pct=ctr,
        cvr_pct=cvr,
        cpc=cpc,
        acos_pct=acos,
        roas=roas,
        verdict=verdict,
        flags=flags,
    )


@router.post("/audit", response_model=PpcAuditResponse)
def audit(req: PpcAuditRequest) -> PpcAuditResponse:
    audits = [audit_campaign(c, req.target_acos_pct, req.min_clicks_for_zero_conversion_flag) for c in req.campaigns]

    total_spend = round(sum(c.spend for c in req.campaigns), 2)
    total_sales = round(sum(c.sales for c in req.campaigns), 2)
    blended_acos = round((total_spend / total_sales) * 100, 2) if total_sales else None
    tacos = round((total_spend / req.total_account_revenue) * 100, 2) if req.total_account_revenue else None

    wasted = round(
        sum(c.spend for c, a in zip(req.campaigns, audits) if a.verdict in ("kill", "cut_or_restructure")), 2
    )

    summary: list[str] = []
    if blended_acos is not None:
        summary.append(f"Blended ACoS across {len(req.campaigns)} campaigns: {blended_acos}% (target {req.target_acos_pct}%).")
    if tacos is not None:
        summary.append(f"TACoS: {tacos}% of total revenue is going to ads.")
    if wasted:
        summary.append(f"${wasted} in spend is sitting on campaigns flagged kill/restructure — that's the first place to cut.")
    else:
        summary.append("No campaigns hit the kill/restructure threshold this period.")

    return PpcAuditResponse(
        campaigns=audits,
        total_ad_spend=total_spend,
        total_ad_sales=total_sales,
        blended_acos_pct=blended_acos,
        tacos_pct=tacos,
        wasted_spend_estimate=wasted,
        summary=summary,
    )
