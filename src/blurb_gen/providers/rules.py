from ..core.guidelines import Guidelines
from ..models import Case, Classification, CriterionScore, QualityReport
from ..templates.registry import Template
from ..templates.render import leftover_placeholders
from .base import Provider


class RuleProvider(Provider):
    name = "rules"

    def is_available(self) -> bool:
        return True

    def classify(self, case: Case, templates: list[Template]) -> Classification | None:
        if case.decision is None:
            return None

        scored = [(t.matches(case.decision, case.reason, case.category), t) for t in templates]
        eligible = [(s, t) for s, t in scored if s > 0]
        if not eligible:
            return None

        best_score = max(s for s, _ in eligible)
        best = sorted((t for s, t in eligible if s == best_score), key=lambda t: t.id)[0]

        confidence = {1: 60.0, 2: 75.0, 3: 90.0, 4: 95.0}.get(best_score, 60.0)
        return Classification(
            template_id=best.id,
            decision=case.decision,
            confidence=confidence,
            rationale=(
                f"matched on decision={case.decision.value}"
                + (f", reason contains one of {best.applies_to.reasons}" if best_score >= 3 else "")
            ),
            source=self.name,
        )

    def score(self, text: str, template: Template, guidelines: Guidelines) -> QualityReport:
        criteria: list[CriterionScore] = []
        issues: list[str] = []
        lowered = text.lower()

        leftover = leftover_placeholders(text)
        criteria.append(
            CriterionScore(
                criterion="no_unfilled_placeholders",
                passed=not leftover,
                weight=3.0,
                detail=f"leftover: {sorted(leftover)}" if leftover else "",
            )
        )
        if leftover:
            issues.append(f"unfilled placeholders remain: {sorted(leftover)}")

        length = len(text)
        within = template.length.min_chars <= length <= template.length.max_chars
        criteria.append(
            CriterionScore(
                criterion="length_within_bounds",
                passed=within,
                weight=1.0,
                detail=(
                    f"{length} chars, allowed "
                    f"{template.length.min_chars}-{template.length.max_chars}"
                ),
            )
        )
        if not within:
            issues.append(
                f"length {length} outside "
                f"{template.length.min_chars}-{template.length.max_chars}"
            )

        found_banned = [p for p in guidelines.banned_phrases if p.lower() in lowered]
        criteria.append(
            CriterionScore(
                criterion="no_banned_phrases",
                passed=not found_banned,
                weight=3.0,
                detail=f"found: {found_banned}" if found_banned else "",
            )
        )
        for phrase in found_banned:
            issues.append(f"banned phrase present: '{phrase}'")

        for element in guidelines.elements_for(template.applies_to.decision):
            present = any(marker.lower() in lowered for marker in element.any_of)
            criteria.append(
                CriterionScore(
                    criterion=f"has_{element.id}",
                    passed=present,
                    weight=element.weight,
                    detail=element.detail,
                )
            )
            if not present:
                issues.append(f"missing required element: {element.id}")

        total_weight = sum(c.weight for c in criteria) or 1.0
        earned = sum(c.weight for c in criteria if c.passed)
        return QualityReport(
            score=round(100.0 * earned / total_weight, 1),
            criteria=criteria,
            issues=issues,
            scored_by=self.name,
        )
