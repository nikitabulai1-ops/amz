"""Templated Plan of Action drafts for common Amazon policy/health notices.

These are deterministic templates, not an LLM call — they fill in the standard
Root Cause / Corrective Actions / Preventive Actions structure Amazon's Account
Health team expects, from the facts you provide. Always review and customize
before submitting; Amazon rejects generic or copy-pasted POAs.
"""

from enum import Enum
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/poa", tags=["poa"])


class ViolationType(str, Enum):
    inauthentic_complaint = "inauthentic_complaint"
    ip_complaint = "ip_complaint"
    product_safety = "product_safety"
    listing_suppressed = "listing_suppressed"
    odr_policy_violation = "odr_policy_violation"
    account_health_warning = "account_health_warning"
    other = "other"


REQUIRED_ATTACHMENTS = {
    ViolationType.inauthentic_complaint: [
        "Supplier/manufacturer invoices for the ASIN, dated within the last 365 days, quantity >= units sold",
        "Supplier's contact info and a signed letter of authorization if you're an authorized reseller",
    ],
    ViolationType.ip_complaint: [
        "Proof of authorization to sell the brand (invoice, distribution agreement, or trademark/license docs)",
        "If the complaint is meritless: evidence the complaint is invalid (your own trademark filing, retraction from rights owner)",
    ],
    ViolationType.product_safety: [
        "Lab test reports / certificates of compliance (CPC, CPSIA, etc. as applicable)",
        "Corrective action records (recall, rework, or inventory removal) for affected units",
    ],
    ViolationType.listing_suppressed: [
        "Corrected listing content (title, bullets, images) meeting the flagged policy",
        "Screenshot or export showing the fix applied",
    ],
    ViolationType.odr_policy_violation: [
        "Order-level data for the flagged defects (order IDs, dates, resolutions)",
        "Evidence of process change (screenshots of new SOP, supplier corrective action, etc.)",
    ],
    ViolationType.account_health_warning: [
        "Relevant performance metric export from Account Health dashboard",
    ],
    ViolationType.other: [],
}


class PoaRequest(BaseModel):
    violation_type: ViolationType
    seller_name: str
    asin_or_sku: Optional[str] = None
    order_ids: list[str] = Field(default_factory=list)
    complaint_summary: str = Field(..., description="What Amazon's notice says the problem is")
    root_cause: str = Field(..., description="The actual reason this happened — be specific, not generic")
    corrective_actions_taken: str = Field(..., description="What you already did to fix the immediate issue")
    preventive_actions: str = Field(..., description="Process/system change that stops recurrence")


class PoaResponse(BaseModel):
    draft: str
    required_attachments: list[str]
    warnings: list[str]


@router.post("/draft", response_model=PoaResponse)
def draft(req: PoaRequest) -> PoaResponse:
    warnings: list[str] = []
    vague_markers = ["will do better", "won't happen again", "made a mistake", "human error"]
    for field_name, value in [
        ("root_cause", req.root_cause),
        ("preventive_actions", req.preventive_actions),
    ]:
        if any(marker in value.lower() for marker in vague_markers) or len(value.split()) < 8:
            warnings.append(
                f"'{field_name}' reads generic/short — Amazon's POA reviewers auto-reject vague causes like "
                "'human error'. Name the specific system failure (e.g. 'supplier changed packaging supplier "
                "without notifying QC, batch #4471-4483 shipped without required choking hazard label')."
            )

    header_lines = [f"Plan of Action — {req.seller_name}"]
    if req.asin_or_sku:
        header_lines.append(f"ASIN/SKU: {req.asin_or_sku}")
    if req.order_ids:
        header_lines.append(f"Order ID(s): {', '.join(req.order_ids)}")

    draft_text = "\n".join(header_lines) + "\n\n"
    draft_text += f"Issue acknowledged:\n{req.complaint_summary}\n\n"
    draft_text += f"Root Cause:\n{req.root_cause}\n\n"
    draft_text += f"Corrective Actions Taken:\n{req.corrective_actions_taken}\n\n"
    draft_text += f"Preventive Actions:\n{req.preventive_actions}\n\n"
    draft_text += (
        "We take full responsibility for this issue and have implemented the above measures to ensure it does "
        "not recur. We respectfully request reinstatement and are available to provide any further documentation."
    )

    return PoaResponse(
        draft=draft_text,
        required_attachments=REQUIRED_ATTACHMENTS[req.violation_type],
        warnings=warnings,
    )
