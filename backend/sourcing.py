"""Product sourcing risk screen: hazmat/meltable/oversize, gating, IP risk, BSR trend."""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

import fee_config as fc

router = APIRouter(prefix="/sourcing", tags=["sourcing"])


class BsrPoint(BaseModel):
    days_ago: int = Field(..., ge=0, description="How many days before today this BSR reading was taken")
    bsr: int = Field(..., gt=0)


class SourcingRequest(BaseModel):
    title: str
    category: str = "default"
    weight_lb: Optional[float] = Field(None, gt=0)
    is_brand_registered: bool = False
    top_competitor_review_counts: list[int] = Field(default_factory=list, description="Review counts of the top ~5 organic results")
    bsr_history: list[BsrPoint] = Field(default_factory=list, description="Oldest-first or any order; sorted internally")


class SourcingResponse(BaseModel):
    hazmat_flags: list[str]
    meltable_flags: list[str]
    gating_flags: list[str]
    ip_risk_flags: list[str]
    competition_flags: list[str]
    bsr_trend: Optional[str]
    bsr_trend_pct: Optional[float]
    overall_risk: str
    notes: list[str]


def _keyword_hits(text: str, keywords: list[str]) -> list[str]:
    text_lower = text.lower()
    return [kw for kw in keywords if kw in text_lower]


@router.post("/evaluate", response_model=SourcingResponse)
def evaluate(req: SourcingRequest) -> SourcingResponse:
    text = f"{req.title} {req.category}"

    hazmat_hits = _keyword_hits(text, fc.HAZMAT_KEYWORDS)
    hazmat_flags = (
        [f"Title/category mentions '{', '.join(hazmat_hits)}' — verify hazmat classification before sourcing. "
         "Undeclared hazmat gets shipments refused at FBA and can trigger account-level restrictions."]
        if hazmat_hits else []
    )

    meltable_hits = _keyword_hits(text, fc.MELTABLE_KEYWORDS)
    meltable_flags = (
        [f"Contains meltable-risk terms ('{', '.join(meltable_hits)}') — Amazon restricts inbound shipping of "
         "meltable inventory roughly May-Sept depending on fulfillment center climate zone."]
        if meltable_hits else []
    )

    gating_hits = _keyword_hits(text, fc.GATED_CATEGORY_KEYWORDS)
    gating_flags = (
        [f"Category/title matches gated terms ('{', '.join(gating_hits)}') — confirm ungating requirements "
         "(invoices, brand approval, etc.) before you commit to a PO."]
        if gating_hits else []
    )

    ip_risk_flags: list[str] = []
    if not req.is_brand_registered:
        ip_risk_flags.append(
            "Not Brand Registered — you have no Brand Registry protection (no A+ content gate, weaker counterfeit "
            "reporting, no Project Zero/Transparency access) and you're exposed if a private-label competitor "
            "files an IP complaint against your listing."
        )

    competition_flags: list[str] = []
    if req.top_competitor_review_counts:
        avg_reviews = sum(req.top_competitor_review_counts) / len(req.top_competitor_review_counts)
        if avg_reviews > 1000:
            competition_flags.append(
                f"Top competitors average {avg_reviews:.0f} reviews — saturated listing. Expect to buy your way in "
                "with PPC for 6-12 months before organic rank moves; budget for it or pick a different niche."
            )
        elif avg_reviews > 300:
            competition_flags.append(
                f"Top competitors average {avg_reviews:.0f} reviews — moderate barrier, winnable with a real "
                "differentiation angle and a launch ad budget."
            )

    bsr_trend = None
    bsr_trend_pct = None
    if len(req.bsr_history) >= 2:
        ordered = sorted(req.bsr_history, key=lambda p: p.days_ago, reverse=True)
        oldest, newest = ordered[0], ordered[-1]
        bsr_trend_pct = round(((oldest.bsr - newest.bsr) / oldest.bsr) * 100, 1)
        if bsr_trend_pct > 10:
            bsr_trend = "improving"
        elif bsr_trend_pct < -10:
            bsr_trend = "declining"
        else:
            bsr_trend = "flat"

    notes: list[str] = []
    if bsr_trend == "declining":
        notes.append(
            f"BSR worsened {abs(bsr_trend_pct)}% over the tracked window — check if the whole category is "
            "seasonal/declining or if a specific competitor ate the demand before you commit inventory dollars."
        )

    risk_count = len(hazmat_flags) + len(meltable_flags) + len(gating_flags) + len(ip_risk_flags) + len(competition_flags)
    if hazmat_flags or (bsr_trend == "declining"):
        overall_risk = "high"
    elif risk_count >= 2:
        overall_risk = "medium"
    elif risk_count == 1:
        overall_risk = "low"
    else:
        overall_risk = "minimal"

    return SourcingResponse(
        hazmat_flags=hazmat_flags,
        meltable_flags=meltable_flags,
        gating_flags=gating_flags,
        ip_risk_flags=ip_risk_flags,
        competition_flags=competition_flags,
        bsr_trend=bsr_trend,
        bsr_trend_pct=bsr_trend_pct,
        overall_risk=overall_risk,
        notes=notes,
    )
