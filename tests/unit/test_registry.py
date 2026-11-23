from pathlib import Path

import pytest
from pydantic import ValidationError

from blurb_gen.models import Decision
from blurb_gen.templates.registry import LengthBounds, Template, TemplateRegistry


class TestSelection:
    def test_specific_reason_match_beats_generic(self, registry):
        chosen = registry.select(Decision.REJECT, reason="missing_docs on file", category="")
        assert chosen.id == "reject_missing_docs"

    def test_falls_back_to_generic_when_reason_unknown(self, registry):
        chosen = registry.select(Decision.REJECT, reason="something else entirely", category="")
        assert chosen.id == "reject_generic"

    def test_category_match_beats_bare_decision(self, registry):
        chosen = registry.select(Decision.APPROVE, reason="", category="toys")
        assert chosen.id == "approve_toys"

    def test_wrong_category_falls_back(self, registry):
        chosen = registry.select(Decision.APPROVE, reason="", category="batteries")
        assert chosen.id == "approve_standard"

    def test_category_match_is_case_insensitive(self, registry):
        assert registry.select(Decision.APPROVE, category="TOYS").id == "approve_toys"

    def test_reason_match_is_case_insensitive(self, registry):
        chosen = registry.select(Decision.REJECT, reason="MISSING_DOCS present")
        assert chosen.id == "reject_missing_docs"

    def test_no_template_for_unrepresented_decision(self, registry):
        assert registry.select(Decision.ESCALATE) is None

    def test_get_by_id(self, registry):
        assert registry.get("reject_generic").version == 2
        assert registry.get("does_not_exist") is None

    def test_version_exposed(self, registry):
        assert registry.version == 2
        assert len(registry.all()) == 4


class TestPlaceholderIntrospection:
    def test_finds_body_placeholders(self, registry):
        template = registry.get("reject_missing_docs")
        assert template.placeholders == {"merchant_name", "product_id", "reason"}

    def test_undeclared_placeholder_detected(self):
        template = Template(
            id="t",
            version=1,
            applies_to={"decision": "reject"},
            required_variables=["merchant_name"],
            body="Hello {merchant_name}, about {product_id}.",
        )
        assert template.undeclared_placeholders() == {"product_id"}

    def test_unused_declaration_detected(self):
        template = Template(
            id="t",
            version=1,
            applies_to={"decision": "reject"},
            required_variables=["merchant_name", "never_used"],
            body="Hello {merchant_name}.",
        )
        assert template.unused_declarations() == {"never_used"}


class TestLengthBounds:
    def test_rejects_inverted_bounds(self):
        with pytest.raises(ValidationError):
            LengthBounds(min_chars=500, max_chars=100)

    def test_rejects_equal_bounds(self):
        with pytest.raises(ValidationError):
            LengthBounds(min_chars=100, max_chars=100)

    def test_accepts_sane_bounds(self):
        assert LengthBounds(min_chars=10, max_chars=20).max_chars == 20


class TestValidation:
    def test_clean_file_has_no_problems(self, registry):
        assert registry.validate() == []

    def test_catches_undeclared_variable(self, tmp_path: Path):
        target = tmp_path / "t.yaml"
        target.write_text(
            """
version: 1
templates:
  - id: bad
    version: 1
    applies_to:
      decision: reject
    required_variables: [merchant_name]
    body: "Hello {merchant_name}, regarding {product_id}."
"""
        )
        problems = TemplateRegistry.load(target).validate()
        assert any("undeclared" in p and "product_id" in p for p in problems)

    def test_catches_unused_declaration(self, tmp_path: Path):
        target = tmp_path / "t.yaml"
        target.write_text(
            """
version: 1
templates:
  - id: bad
    version: 1
    applies_to:
      decision: reject
    required_variables: [merchant_name, orphan]
    body: "Hello {merchant_name}."
"""
        )
        problems = TemplateRegistry.load(target).validate()
        assert any("orphan" in p and "never uses" in p for p in problems)

    def test_catches_version_above_set_version(self, tmp_path: Path):
        target = tmp_path / "t.yaml"
        target.write_text(
            """
version: 1
templates:
  - id: ahead
    version: 9
    applies_to:
      decision: reject
    required_variables: []
    body: "Static text with no variables."
"""
        )
        problems = TemplateRegistry.load(target).validate()
        assert any("exceeds set version" in p for p in problems)

    def test_catches_unreachable_max_chars(self, tmp_path: Path):
        target = tmp_path / "t.yaml"
        target.write_text(
            """
version: 1
templates:
  - id: impossible
    version: 1
    applies_to:
      decision: reject
    required_variables: []
    length:
      min_chars: 1
      max_chars: 5
    body: "This body is far longer than five characters."
"""
        )
        problems = TemplateRegistry.load(target).validate()
        assert any("can never pass" in p for p in problems)


class TestLoading:
    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            TemplateRegistry.load(tmp_path / "nope.yaml")

    def test_repo_template_file_is_valid(self):
        repo_templates = Path(__file__).resolve().parents[2] / "data" / "templates.yaml"
        assert TemplateRegistry.load(repo_templates).validate() == []
