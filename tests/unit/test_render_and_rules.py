import pytest

from blurb_gen.models import Decision
from blurb_gen.providers.rules import RuleProvider
from blurb_gen.templates.render import MissingVariablesError, leftover_placeholders, render


class TestRender:
    def test_substitutes_all_variables(self, registry):
        template = registry.get("reject_missing_docs")
        text = render(
            template,
            {"merchant_name": "Acme", "product_id": "SKU-1", "reason": "no report"},
        )
        assert "Acme" in text
        assert "SKU-1" in text
        assert "no report" in text
        assert not leftover_placeholders(text)

    def test_missing_required_variable_raises(self, registry):
        template = registry.get("reject_missing_docs")
        with pytest.raises(MissingVariablesError) as exc:
            render(template, {"merchant_name": "Acme", "product_id": "SKU-1"})
        assert exc.value.missing == {"reason"}

    def test_empty_string_counts_as_missing(self, registry):
        template = registry.get("reject_missing_docs")
        with pytest.raises(MissingVariablesError):
            render(template, {"merchant_name": "Acme", "product_id": "SKU-1", "reason": ""})

    def test_extra_variables_are_ignored(self, registry):
        template = registry.get("approve_standard")
        text = render(
            template,
            {"merchant_name": "Acme", "product_id": "SKU-1", "unused": "value"},
        )
        assert "value" not in text

    def test_collapses_repeated_blank_lines(self, registry):
        template = registry.get("approve_standard")
        text = render(template, {"merchant_name": "Acme", "product_id": "SKU-1"})
        assert "\n\n\n" not in text

    def test_strips_leading_and_trailing_whitespace(self, registry):
        template = registry.get("approve_standard")
        text = render(template, {"merchant_name": "Acme", "product_id": "SKU-1"})
        assert text == text.strip()


class TestLeftoverDetection:
    def test_finds_unfilled(self):
        assert leftover_placeholders("Hello {merchant_name}") == {"merchant_name"}

    def test_clean_text_has_none(self):
        assert leftover_placeholders("Hello Acme") == set()

    def test_ignores_uppercase_braces(self):
        assert leftover_placeholders("Hello {NotAVariable}") == set()


class TestRuleClassification:
    def test_picks_specific_template(self, registry, reject_case):
        result = RuleProvider().classify(reject_case, registry.all())
        assert result.template_id == "reject_missing_docs"
        assert result.source == "rules"

    def test_specific_match_scores_higher_confidence(self, registry, reject_case, approve_case):
        specific = RuleProvider().classify(reject_case, registry.all())
        generic = RuleProvider().classify(approve_case, registry.all())
        assert specific.confidence >= generic.confidence

    def test_no_decision_returns_none(self, registry, reject_case):
        reject_case.decision = None
        assert RuleProvider().classify(reject_case, registry.all()) is None

    def test_unmatched_decision_returns_none(self, registry, reject_case):
        reject_case.decision = Decision.ESCALATE
        assert RuleProvider().classify(reject_case, registry.all()) is None

    def test_always_available(self):
        assert RuleProvider().is_available()


class TestRuleScoring:
    def test_clean_blurb_scores_full(self, registry, guidelines):
        template = registry.get("reject_missing_docs")
        text = render(
            template,
            {"merchant_name": "Acme", "product_id": "SKU-1", "reason": "no report"},
        )
        report = RuleProvider().score(text, template, guidelines)
        assert report.score == 100.0
        assert report.issues == []

    def test_unfilled_placeholder_fails(self, registry, guidelines):
        template = registry.get("reject_missing_docs")
        report = RuleProvider().score(
            "Hello {merchant_name}, to resolve this reply to this message.",
            template,
            guidelines,
        )
        assert "no_unfilled_placeholders" in report.failed_criteria
        assert any("unfilled placeholders" in i for i in report.issues)

    def test_banned_phrase_fails(self, registry, guidelines):
        template = registry.get("reject_missing_docs")
        text = render(
            template,
            {"merchant_name": "Acme", "product_id": "SKU-1", "reason": "we guarantee a fix"},
        )
        report = RuleProvider().score(text, template, guidelines)
        assert "no_banned_phrases" in report.failed_criteria
        assert any("we guarantee" in i for i in report.issues)

    def test_too_short_fails_length(self, registry, guidelines):
        template = registry.get("reject_missing_docs")
        report = RuleProvider().score("Hello.", template, guidelines)
        assert "length_within_bounds" in report.failed_criteria

    def test_missing_required_element_fails(self, registry, guidelines):
        template = registry.get("reject_missing_docs")
        filler = "This message has no greeting and no instructions. " * 3
        report = RuleProvider().score(filler, template, guidelines)
        assert "has_greeting" in report.failed_criteria
        assert "has_next_steps" in report.failed_criteria

    def test_score_is_weight_proportional(self, registry, guidelines):
        template = registry.get("reject_missing_docs")
        good = render(
            template,
            {"merchant_name": "Acme", "product_id": "SKU-1", "reason": "no report"},
        )
        bad = render(
            template,
            {"merchant_name": "Acme", "product_id": "SKU-1", "reason": "we guarantee it"},
        )
        assert RuleProvider().score(good, template, guidelines).score > (
            RuleProvider().score(bad, template, guidelines).score
        )

    def test_scored_by_is_recorded(self, registry, guidelines):
        template = registry.get("approve_standard")
        text = render(template, {"merchant_name": "Acme", "product_id": "SKU-1"})
        assert RuleProvider().score(text, template, guidelines).scored_by == "rules"
