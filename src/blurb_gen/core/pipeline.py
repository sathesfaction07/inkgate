import logging

from ..config import Settings
from ..models import Blurb, Case, Status
from ..providers import get_provider
from ..providers.base import Provider
from ..providers.rules import RuleProvider
from ..templates.registry import TemplateRegistry
from ..templates.render import MissingVariablesError, render
from .gate import decide_status, objective_defects
from .guidelines import Guidelines

logger = logging.getLogger("blurb_gen")


class Pipeline:
    def __init__(
        self,
        cfg: Settings,
        registry: TemplateRegistry | None = None,
        guidelines: Guidelines | None = None,
        provider: Provider | None = None,
    ) -> None:
        self.cfg = cfg
        self.registry = registry or TemplateRegistry.load(cfg.templates_path)
        self.guidelines = guidelines or Guidelines.load(cfg.guidelines_path)
        self.provider = provider or get_provider(cfg.provider, cfg)
        self.fallback = RuleProvider()

    def generate(self, case: Case) -> Blurb:
        classification = self.provider.classify(case, self.registry.all())
        used_fallback = False

        if classification is None and self.provider.name != self.fallback.name:
            classification = self.fallback.classify(case, self.registry.all())
            used_fallback = classification is not None

        if classification is None:
            return Blurb(
                case_id=case.case_id,
                status=Status.FAILED,
                error="no template matched this case",
            )

        template = self.registry.get(classification.template_id)
        if template is None:
            return Blurb(
                case_id=case.case_id,
                status=Status.FAILED,
                decision=classification.decision,
                classification_source=classification.source,
                error=f"provider chose unknown template '{classification.template_id}'",
            )

        try:
            text = render(template, case.variables())
        except MissingVariablesError as exc:
            return Blurb(
                case_id=case.case_id,
                status=Status.FAILED,
                template_id=template.id,
                template_version=template.version,
                decision=classification.decision,
                classification_confidence=classification.confidence,
                classification_source=classification.source,
                error=str(exc),
            )

        report = self.provider.score(text, template, self.guidelines)
        if report is None:
            report = self.fallback.score(text, template, self.guidelines)

        defects = objective_defects(text, template, self.guidelines)
        status, issues = decide_status(
            confidence=classification.confidence,
            report=report,
            defects=defects,
            confidence_threshold=self.cfg.confidence_threshold,
            quality_threshold=self.cfg.quality_threshold,
        )

        if used_fallback:
            issues.append(
                f"provider '{self.provider.name}' returned no classification, fell back to rules"
            )

        return Blurb(
            case_id=case.case_id,
            status=status,
            text=text,
            template_id=template.id,
            template_version=template.version,
            decision=classification.decision,
            classification_confidence=classification.confidence,
            classification_source=classification.source,
            quality_score=report.score,
            scored_by=report.scored_by,
            issues=issues,
        )

    def generate_batch(self, cases: list[Case]) -> list[Blurb]:
        results: list[Blurb] = []
        for case in cases:
            try:
                results.append(self.generate(case))
            except Exception as exc:
                logger.error("case %s failed: %s", case.case_id, exc)
                results.append(
                    Blurb(
                        case_id=case.case_id,
                        status=Status.FAILED,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        return results


def summarise(blurbs: list[Blurb]) -> dict[str, object]:
    return {
        "total": len(blurbs),
        "ready": sum(1 for b in blurbs if b.status is Status.READY),
        "needs_review": sum(1 for b in blurbs if b.status is Status.NEEDS_REVIEW),
        "failed": sum(1 for b in blurbs if b.status is Status.FAILED),
        "mean_quality": (
            round(sum(b.quality_score for b in blurbs) / len(blurbs), 1) if blurbs else 0.0
        ),
        "templates_used": sorted({b.template_id for b in blurbs if b.template_id}),
    }
