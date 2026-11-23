from ..models import QualityReport, Status
from ..templates.registry import Template
from ..templates.render import leftover_placeholders
from .guidelines import Guidelines


def objective_defects(text: str, template: Template, guidelines: Guidelines) -> list[str]:
    defects: list[str] = []

    leftover = leftover_placeholders(text)
    if leftover:
        defects.append(f"unfilled placeholders remain: {sorted(leftover)}")

    lowered = text.lower()
    for phrase in guidelines.banned_phrases:
        if phrase.lower() in lowered:
            defects.append(f"banned phrase present: '{phrase}'")

    if not text.strip():
        defects.append("rendered text is empty")

    if len(text) > template.length.max_chars:
        defects.append(
            f"length {len(text)} exceeds template maximum {template.length.max_chars}"
        )

    return defects


def decide_status(
    confidence: float,
    report: QualityReport,
    defects: list[str],
    confidence_threshold: float,
    quality_threshold: float,
) -> tuple[Status, list[str]]:
    issues = list(report.issues)
    status = Status.READY

    for defect in defects:
        if defect not in issues:
            issues.append(defect)

    if defects:
        status = Status.NEEDS_REVIEW

    if confidence < confidence_threshold:
        status = Status.NEEDS_REVIEW
        issues.append(
            f"classification confidence {confidence:.0f} below threshold "
            f"{confidence_threshold:.0f}"
        )

    if report.score < quality_threshold:
        status = Status.NEEDS_REVIEW
        issues.append(
            f"quality score {report.score:.0f} below threshold {quality_threshold:.0f}"
        )

    return status, issues
