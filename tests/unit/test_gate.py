from blurb_gen.core.gate import decide_status, objective_defects
from blurb_gen.models import QualityReport, Status
from blurb_gen.templates.render import render

PERFECT = QualityReport(score=100.0, scored_by="stub")


class TestObjectiveDefects:
    def test_clean_text_has_none(self, registry, guidelines):
        template = registry.get("reject_missing_docs")
        text = render(
            template, {"merchant_name": "Acme", "product_id": "SKU-1", "reason": "no report"}
        )
        assert objective_defects(text, template, guidelines) == []

    def test_detects_unfilled_placeholder(self, registry, guidelines):
        template = registry.get("reject_missing_docs")
        defects = objective_defects("Hello {merchant_name}, all done.", template, guidelines)
        assert any("unfilled placeholders" in d for d in defects)

    def test_detects_banned_phrase(self, registry, guidelines):
        template = registry.get("reject_missing_docs")
        defects = objective_defects("Hello Acme, we guarantee a fix.", template, guidelines)
        assert any("we guarantee" in d for d in defects)

    def test_banned_phrase_match_is_case_insensitive(self, registry, guidelines):
        template = registry.get("reject_missing_docs")
        defects = objective_defects("Hello Acme, WE GUARANTEE a fix.", template, guidelines)
        assert any("we guarantee" in d for d in defects)

    def test_detects_empty_text(self, registry, guidelines):
        template = registry.get("reject_missing_docs")
        assert any("empty" in d for d in objective_defects("   ", template, guidelines))

    def test_detects_overlong_text(self, registry, guidelines):
        template = registry.get("approve_toys")
        defects = objective_defects("x" * 5000, template, guidelines)
        assert any("exceeds template maximum" in d for d in defects)

    def test_reports_every_defect_not_just_the_first(self, registry, guidelines):
        template = registry.get("reject_missing_docs")
        defects = objective_defects(
            "Hello {merchant_name}, we guarantee it. Unfortunately.", template, guidelines
        )
        assert len(defects) >= 3


class TestDecideStatus:
    def test_all_clear_is_ready(self):
        status, issues = decide_status(95.0, PERFECT, [], 60.0, 75.0)
        assert status is Status.READY
        assert issues == []

    def test_any_defect_forces_review_regardless_of_score(self):
        status, issues = decide_status(99.0, PERFECT, ["banned phrase present: 'x'"], 60.0, 75.0)
        assert status is Status.NEEDS_REVIEW
        assert "banned phrase present: 'x'" in issues

    def test_low_confidence_forces_review(self):
        status, issues = decide_status(40.0, PERFECT, [], 60.0, 75.0)
        assert status is Status.NEEDS_REVIEW
        assert any("confidence 40" in i for i in issues)

    def test_low_score_forces_review(self):
        status, issues = decide_status(95.0, QualityReport(score=50.0), [], 60.0, 75.0)
        assert status is Status.NEEDS_REVIEW
        assert any("quality score 50" in i for i in issues)

    def test_defect_wins_even_at_a_perfect_score_and_confidence(self):
        status, _ = decide_status(100.0, PERFECT, ["rendered text is empty"], 60.0, 75.0)
        assert status is Status.NEEDS_REVIEW

    def test_score_at_threshold_passes(self):
        status, _ = decide_status(60.0, QualityReport(score=75.0), [], 60.0, 75.0)
        assert status is Status.READY

    def test_report_issues_are_carried_through(self):
        report = QualityReport(score=100.0, issues=["something the judge noticed"])
        _, issues = decide_status(95.0, report, [], 60.0, 75.0)
        assert "something the judge noticed" in issues

    def test_defects_are_not_duplicated_when_the_scorer_also_found_them(self):
        shared = "banned phrase present: 'we guarantee'"
        report = QualityReport(score=80.0, issues=[shared])
        _, issues = decide_status(95.0, report, [shared], 60.0, 75.0)
        assert issues.count(shared) == 1


class TestWhyTheGateExists:
    def test_weighted_average_alone_cannot_catch_a_single_defect(self, registry, guidelines):
        template = registry.get("reject_missing_docs")
        text = render(
            template,
            {"merchant_name": "Acme", "product_id": "SKU-1", "reason": "we guarantee a fix"},
        )

        from blurb_gen.providers.rules import RuleProvider

        report = RuleProvider().score(text, template, guidelines)
        assert report.score > 75.0

        defects = objective_defects(text, template, guidelines)
        status, _ = decide_status(95.0, report, defects, 60.0, 75.0)
        assert status is Status.NEEDS_REVIEW
