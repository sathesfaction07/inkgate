from pathlib import Path

import pytest

from blurb_gen.config import Settings
from blurb_gen.core.guidelines import Guidelines
from blurb_gen.models import Case, Decision
from blurb_gen.templates.registry import TemplateRegistry

REPO_DATA = Path(__file__).resolve().parents[1] / "data"

TEMPLATE_YAML = """
version: 2
templates:
  - id: reject_missing_docs
    version: 2
    applies_to:
      decision: reject
      reasons: [missing_docs, incomplete]
    required_variables: [merchant_name, product_id, reason]
    length:
      min_chars: 60
      max_chars: 600
    body: |
      Hello {merchant_name},
      We reviewed your submission for {product_id} and could not approve it.
      What we found: {reason}
      To resolve this, please provide the missing documents.
      If this looks wrong, reply to this message.

  - id: reject_generic
    version: 2
    applies_to:
      decision: reject
    required_variables: [merchant_name, product_id]
    length:
      min_chars: 40
      max_chars: 600
    body: |
      Hello {merchant_name},
      We reviewed your submission for {product_id} and could not approve it.
      To resolve this, please reply with more detail.
      If this looks wrong, reply to this message.

  - id: approve_toys
    version: 2
    applies_to:
      decision: approve
      categories: [toys]
    required_variables: [merchant_name, product_id]
    length:
      min_chars: 30
      max_chars: 400
    body: |
      Hello {merchant_name},
      Your submission for {product_id} is approved. No further action is needed.

  - id: approve_standard
    version: 2
    applies_to:
      decision: approve
    required_variables: [merchant_name, product_id]
    length:
      min_chars: 30
      max_chars: 400
    body: |
      Hello {merchant_name},
      Your submission for {product_id} is approved. No further action is needed.
"""

GUIDELINES_YAML = """
version: 1
banned_phrases:
  - "we guarantee"
  - "unfortunately"
required_elements:
  - id: greeting
    any_of: ["hello", "dear"]
    weight: 1.0
  - id: next_steps
    any_of: ["to resolve this", "no further action", "please reply"]
    weight: 3.0
  - id: recourse
    any_of: ["reply to this message", "no further action"]
    weight: 2.0
tone_notes:
  - Plain and neutral.
"""


@pytest.fixture
def templates_file(tmp_path: Path) -> Path:
    target = tmp_path / "templates.yaml"
    target.write_text(TEMPLATE_YAML)
    return target


@pytest.fixture
def guidelines_file(tmp_path: Path) -> Path:
    target = tmp_path / "guidelines.yaml"
    target.write_text(GUIDELINES_YAML)
    return target


@pytest.fixture
def registry(templates_file: Path) -> TemplateRegistry:
    return TemplateRegistry.load(templates_file)


@pytest.fixture
def guidelines(guidelines_file: Path) -> Guidelines:
    return Guidelines.load(guidelines_file)


@pytest.fixture
def cfg(tmp_path: Path, templates_file: Path, guidelines_file: Path) -> Settings:
    return Settings(
        templates_path=templates_file,
        guidelines_path=guidelines_file,
        provider="rules",
        quality_threshold=75.0,
        confidence_threshold=60.0,
        output_format="csv",
    )


@pytest.fixture
def reject_case() -> Case:
    return Case(
        case_id="C-001",
        merchant_name="Acme Supplies",
        product_id="SKU-11111",
        category="toys",
        decision=Decision.REJECT,
        reason="missing_docs: no test report attached",
    )


@pytest.fixture
def approve_case() -> Case:
    return Case(
        case_id="C-002",
        merchant_name="Bolt Goods",
        product_id="SKU-22222",
        category="toys",
        decision=Decision.APPROVE,
    )
