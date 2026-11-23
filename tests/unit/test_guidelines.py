from pathlib import Path

import pytest

from blurb_gen.core.guidelines import Guidelines, RequiredElement
from blurb_gen.models import Decision
from blurb_gen.providers.rules import RuleProvider
from blurb_gen.templates.registry import TemplateRegistry
from blurb_gen.templates.render import render

REPO_DATA = Path(__file__).resolve().parents[2] / "data"


class TestScoping:
    def test_unscoped_element_applies_everywhere(self):
        element = RequiredElement(id="greeting", any_of=["hello"])
        assert element.applies(Decision.APPROVE)
        assert element.applies(Decision.REJECT)

    def test_scoped_element_applies_only_to_listed_decisions(self):
        element = RequiredElement(
            id="recourse",
            any_of=["reply"],
            applies_to_decisions=[Decision.REJECT, Decision.ESCALATE],
        )
        assert element.applies(Decision.REJECT)
        assert element.applies(Decision.ESCALATE)
        assert not element.applies(Decision.APPROVE)

    def test_elements_for_filters(self):
        guidelines = Guidelines(
            required_elements=[
                RequiredElement(id="always", any_of=["x"]),
                RequiredElement(
                    id="reject_only",
                    any_of=["y"],
                    applies_to_decisions=[Decision.REJECT],
                ),
            ]
        )
        assert [e.id for e in guidelines.elements_for(Decision.APPROVE)] == ["always"]
        assert [e.id for e in guidelines.elements_for(Decision.REJECT)] == [
            "always",
            "reject_only",
        ]


class TestShippedGuidelines:
    @pytest.fixture
    def shipped(self) -> Guidelines:
        return Guidelines.load(REPO_DATA / "guidelines.yaml")

    @pytest.fixture
    def shipped_templates(self) -> TemplateRegistry:
        return TemplateRegistry.load(REPO_DATA / "templates.yaml")

    def test_recourse_is_not_demanded_of_approvals(self, shipped):
        ids = [e.id for e in shipped.elements_for(Decision.APPROVE)]
        assert "recourse" not in ids

    def test_recourse_is_demanded_of_rejections(self, shipped):
        ids = [e.id for e in shipped.elements_for(Decision.REJECT)]
        assert "recourse" in ids

    def test_every_shipped_template_scores_full_marks(self, shipped, shipped_templates):
        variables = {
            "merchant_name": "Acme Supplies",
            "product_id": "SKU-40001",
            "reason": "a plainly worded finding",
        }
        for template in shipped_templates.all():
            text = render(template, variables)
            report = RuleProvider().score(text, template, shipped)
            assert report.score == 100.0, f"{template.id} scored {report.score}: {report.issues}"

    def test_prompt_block_is_scoped_when_a_decision_is_given(self, shipped):
        approve_block = shipped.as_prompt_block(Decision.APPROVE)
        reject_block = shipped.as_prompt_block(Decision.REJECT)
        assert "recourse" not in approve_block
        assert "recourse" in reject_block

    def test_prompt_block_lists_everything_when_unscoped(self, shipped):
        assert "recourse" in shipped.as_prompt_block()


class TestLoading:
    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            Guidelines.load(tmp_path / "nope.yaml")

    def test_empty_file_gives_empty_guidelines(self, tmp_path: Path):
        target = tmp_path / "empty.yaml"
        target.write_text("")
        guidelines = Guidelines.load(target)
        assert guidelines.banned_phrases == []
        assert guidelines.required_elements == []
