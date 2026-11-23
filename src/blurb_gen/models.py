from enum import Enum

from pydantic import BaseModel, Field


class Decision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    NEED_INFO = "need_info"
    ESCALATE = "escalate"


class Status(str, Enum):
    READY = "ready"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class Case(BaseModel):
    case_id: str
    merchant_name: str = "Merchant"
    product_id: str = ""
    category: str = ""
    marketplace: str = "US"
    decision: Decision | None = None
    reason: str = ""
    notes: str = ""
    extras: dict[str, str] = Field(default_factory=dict)

    def variables(self) -> dict[str, str]:
        base = {
            "case_id": self.case_id,
            "merchant_name": self.merchant_name,
            "product_id": self.product_id,
            "category": self.category,
            "marketplace": self.marketplace,
            "reason": self.reason,
            "notes": self.notes,
        }
        base.update(self.extras)
        return {k: v for k, v in base.items() if v}


class Classification(BaseModel):
    template_id: str
    decision: Decision
    confidence: float = Field(ge=0.0, le=100.0)
    rationale: str = ""
    source: str = "rules"


class CriterionScore(BaseModel):
    criterion: str
    passed: bool
    weight: float
    detail: str = ""


class QualityReport(BaseModel):
    score: float = Field(ge=0.0, le=100.0)
    criteria: list[CriterionScore] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    scored_by: str = "rules"

    @property
    def failed_criteria(self) -> list[str]:
        return [c.criterion for c in self.criteria if not c.passed]


class Blurb(BaseModel):
    case_id: str
    status: Status
    text: str = ""
    template_id: str = ""
    template_version: int = 0
    decision: Decision | None = None
    classification_confidence: float = 0.0
    classification_source: str = ""
    quality_score: float = 0.0
    scored_by: str = ""
    issues: list[str] = Field(default_factory=list)
    error: str = ""

    def as_row(self) -> dict[str, str | float]:
        return {
            "case_id": self.case_id,
            "status": self.status.value,
            "decision": self.decision.value if self.decision else "",
            "template_id": self.template_id,
            "template_version": self.template_version,
            "classification_confidence": round(self.classification_confidence, 1),
            "classification_source": self.classification_source,
            "quality_score": round(self.quality_score, 1),
            "scored_by": self.scored_by,
            "issues": " | ".join(self.issues),
            "error": self.error,
            "blurb": self.text,
        }
