from blurb_gen.core.pipeline import Pipeline, summarise
from blurb_gen.models import Case, Classification, Decision, QualityReport, Status
from blurb_gen.providers.base import Provider
from blurb_gen.providers.rules import RuleProvider


class StubProvider(Provider):
    name = "stub"

    def __init__(
        self,
        classification: Classification | None = None,
        report: QualityReport | None = None,
    ) -> None:
        self._classification = classification
        self._report = report

    def is_available(self) -> bool:
        return True

    def classify(self, case, templates):
        return self._classification

    def score(self, text, template, guidelines):
        return self._report


class TestGate:
    def test_clean_case_is_ready(self, cfg, reject_case):
        blurb = Pipeline(cfg).generate(reject_case)
        assert blurb.status is Status.READY
        assert blurb.quality_score == 100.0
        assert blurb.issues == []

    def test_banned_phrase_gates_even_when_score_passes(self, cfg, reject_case):
        reject_case.reason = "missing_docs but we guarantee a resolution"
        blurb = Pipeline(cfg).generate(reject_case)
        assert blurb.status is Status.NEEDS_REVIEW
        assert blurb.quality_score > cfg.quality_threshold
        assert any("we guarantee" in i for i in blurb.issues)

    def test_low_score_alone_gates_with_no_defects(self, cfg, reject_case, registry, guidelines):
        stub = StubProvider(
            classification=Classification(
                template_id="reject_missing_docs",
                decision=Decision.REJECT,
                confidence=99.0,
                source="stub",
            ),
            report=QualityReport(score=50.0, scored_by="stub-judge"),
        )
        blurb = Pipeline(cfg, registry, guidelines, stub).generate(reject_case)
        assert blurb.status is Status.NEEDS_REVIEW
        assert any("quality score 50" in i for i in blurb.issues)

    def test_low_confidence_becomes_needs_review(self, cfg, reject_case, registry, guidelines):
        stub = StubProvider(
            classification=Classification(
                template_id="reject_generic",
                decision=Decision.REJECT,
                confidence=30.0,
                source="stub",
            ),
            report=QualityReport(score=100.0, scored_by="stub"),
        )
        blurb = Pipeline(cfg, registry, guidelines, stub).generate(reject_case)
        assert blurb.status is Status.NEEDS_REVIEW
        assert any("confidence" in i for i in blurb.issues)

    def test_raising_the_threshold_gates_more(self, cfg, reject_case):
        cfg.quality_threshold = 101.0
        blurb = Pipeline(cfg).generate(reject_case)
        assert blurb.status is Status.NEEDS_REVIEW

    def test_gated_blurb_still_carries_its_text(self, cfg, reject_case):
        cfg.quality_threshold = 101.0
        blurb = Pipeline(cfg).generate(reject_case)
        assert blurb.text
        assert "Acme Supplies" in blurb.text


class TestProvenance:
    def test_records_template_id_and_version(self, cfg, reject_case):
        blurb = Pipeline(cfg).generate(reject_case)
        assert blurb.template_id == "reject_missing_docs"
        assert blurb.template_version == 2

    def test_records_who_classified_and_who_scored(self, cfg, reject_case):
        blurb = Pipeline(cfg).generate(reject_case)
        assert blurb.classification_source == "rules"
        assert blurb.scored_by == "rules"

    def test_stub_provenance_is_preserved(self, cfg, reject_case, registry, guidelines):
        stub = StubProvider(
            classification=Classification(
                template_id="reject_generic",
                decision=Decision.REJECT,
                confidence=95.0,
                source="stub",
            ),
            report=QualityReport(score=99.0, scored_by="stub-judge"),
        )
        blurb = Pipeline(cfg, registry, guidelines, stub).generate(reject_case)
        assert blurb.classification_source == "stub"
        assert blurb.scored_by == "stub-judge"


class TestFallback:
    def test_falls_back_to_rules_when_provider_returns_nothing(
        self, cfg, reject_case, registry, guidelines
    ):
        blurb = Pipeline(cfg, registry, guidelines, StubProvider()).generate(reject_case)
        assert blurb.classification_source == "rules"
        assert any("fell back to rules" in i for i in blurb.issues)

    def test_falls_back_to_rule_scoring_when_judge_returns_nothing(
        self, cfg, reject_case, registry, guidelines
    ):
        stub = StubProvider(
            classification=Classification(
                template_id="reject_missing_docs",
                decision=Decision.REJECT,
                confidence=95.0,
                source="stub",
            ),
            report=None,
        )
        blurb = Pipeline(cfg, registry, guidelines, stub).generate(reject_case)
        assert blurb.scored_by == "rules"
        assert blurb.status is Status.READY

    def test_no_fallback_note_when_rules_is_the_provider(self, cfg, reject_case):
        blurb = Pipeline(cfg).generate(reject_case)
        assert not any("fell back" in i for i in blurb.issues)


class TestFailures:
    def test_unmatched_case_fails(self, cfg):
        case = Case(case_id="C-X", decision=Decision.ESCALATE, product_id="SKU-9")
        blurb = Pipeline(cfg).generate(case)
        assert blurb.status is Status.FAILED
        assert "no template matched" in blurb.error

    def test_missing_variable_fails_with_named_variable(self, cfg):
        case = Case(
            case_id="C-Y",
            merchant_name="Acme",
            decision=Decision.REJECT,
            reason="missing_docs",
        )
        blurb = Pipeline(cfg).generate(case)
        assert blurb.status is Status.FAILED
        assert "product_id" in blurb.error

    def test_provider_naming_unknown_template_fails(
        self, cfg, reject_case, registry, guidelines
    ):
        stub = StubProvider(
            classification=Classification(
                template_id="invented_template",
                decision=Decision.REJECT,
                confidence=99.0,
                source="stub",
            )
        )
        blurb = Pipeline(cfg, registry, guidelines, stub).generate(reject_case)
        assert blurb.status is Status.FAILED
        assert "unknown template" in blurb.error

    def test_one_bad_case_does_not_stop_the_batch(self, cfg, reject_case, approve_case):
        broken = Case(case_id="C-BAD", decision=Decision.ESCALATE)
        blurbs = Pipeline(cfg).generate_batch([reject_case, broken, approve_case])
        assert len(blurbs) == 3
        assert [b.status for b in blurbs].count(Status.FAILED) == 1
        assert [b.status for b in blurbs].count(Status.READY) == 2


class TestSummary:
    def test_counts_by_status(self, cfg, reject_case, approve_case):
        broken = Case(case_id="C-BAD", decision=Decision.ESCALATE)
        summary = summarise(Pipeline(cfg).generate_batch([reject_case, approve_case, broken]))
        assert summary["total"] == 3
        assert summary["ready"] == 2
        assert summary["failed"] == 1

    def test_lists_templates_used(self, cfg, reject_case, approve_case):
        summary = summarise(Pipeline(cfg).generate_batch([reject_case, approve_case]))
        assert "reject_missing_docs" in summary["templates_used"]
        assert "approve_toys" in summary["templates_used"]

    def test_empty_batch_is_safe(self):
        summary = summarise([])
        assert summary["total"] == 0
        assert summary["mean_quality"] == 0.0


class TestRuleProviderIsDefault:
    def test_default_provider_needs_no_credentials(self, cfg):
        assert isinstance(Pipeline(cfg).provider, RuleProvider)
