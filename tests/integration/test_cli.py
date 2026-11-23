import json
from pathlib import Path

from click.testing import CliRunner

from blurb_gen.cli import main

REPO = Path(__file__).resolve().parents[2]
TEMPLATES = REPO / "data" / "templates.yaml"
GUIDELINES = REPO / "data" / "guidelines.yaml"


def _args(*extra: str) -> list[str]:
    return ["--templates", str(TEMPLATES), "--guidelines", str(GUIDELINES), *extra]


class TestTemplatesCommand:
    def test_lists_shipped_templates(self):
        result = CliRunner().invoke(main, ["templates", "--templates", str(TEMPLATES)])
        assert result.exit_code == 0
        assert "set version 3" in result.output
        assert "reject_missing_documentation" in result.output

    def test_validate_passes_on_shipped_file(self):
        result = CliRunner().invoke(
            main, ["templates", "--templates", str(TEMPLATES), "--validate"]
        )
        assert result.exit_code == 0
        assert "no problems" in result.output

    def test_validate_fails_on_broken_file(self, tmp_path: Path):
        broken = tmp_path / "broken.yaml"
        broken.write_text(
            """
version: 1
templates:
  - id: bad
    version: 1
    applies_to:
      decision: reject
    required_variables: [merchant_name]
    body: "Hello {merchant_name}, about {undeclared_var}."
"""
        )
        result = CliRunner().invoke(main, ["templates", "--templates", str(broken), "--validate"])
        assert result.exit_code == 1
        assert "undeclared" in result.output


class TestProvidersCommand:
    def test_rules_is_always_ready(self):
        result = CliRunner().invoke(main, ["providers", "--guidelines", str(GUIDELINES)])
        assert result.exit_code == 0
        assert "rules" in result.output
        assert "ready" in result.output

    def test_reports_guidelines_version(self):
        result = CliRunner().invoke(main, ["providers", "--guidelines", str(GUIDELINES)])
        assert "guidelines v2" in result.output


class TestGenerateCommand:
    def test_generates_a_ready_blurb(self):
        result = CliRunner().invoke(
            main,
            [
                "generate",
                *_args(),
                "--case-id",
                "C-100",
                "--decision",
                "reject",
                "--merchant",
                "Acme Supplies",
                "--product-id",
                "SKU-4242",
                "--reason",
                "missing_docs: no test report attached",
            ],
        )
        assert result.exit_code == 0
        assert "ready" in result.output
        assert "reject_missing_documentation" in result.output
        assert "Acme Supplies" in result.output

    def test_gates_when_reason_contains_banned_phrase(self):
        result = CliRunner().invoke(
            main,
            [
                "generate",
                "--templates",
                str(TEMPLATES),
                "--guidelines",
                str(GUIDELINES),
                "--case-id",
                "C-101",
                "--decision",
                "reject",
                "--product-id",
                "SKU-1",
                "--reason",
                "missing_docs and we guarantee a quick fix",
            ],
        )
        assert result.exit_code == 0
        assert "needs_review" in result.output
        assert "we guarantee" in result.output

    def test_show_criteria_prints_breakdown(self):
        result = CliRunner().invoke(
            main,
            [
                "generate",
                "--templates",
                str(TEMPLATES),
                "--guidelines",
                str(GUIDELINES),
                "--case-id",
                "C-102",
                "--decision",
                "approve",
                "--product-id",
                "SKU-2",
                "--show-criteria",
            ],
        )
        assert result.exit_code == 0
        assert "no_unfilled_placeholders" in result.output
        assert "has_next_steps" in result.output

    def test_missing_variable_reports_failure(self):
        result = CliRunner().invoke(
            main,
            [
                "generate",
                "--templates",
                str(TEMPLATES),
                "--guidelines",
                str(GUIDELINES),
                "--case-id",
                "C-103",
                "--decision",
                "reject",
                "--reason",
                "missing_docs",
            ],
        )
        assert result.exit_code == 0
        assert "failed" in result.output
        assert "product_id" in result.output


class TestBatchCommand:
    def _input(self, tmp_path: Path) -> Path:
        target = tmp_path / "cases.csv"
        target.write_text(
            "case_id,merchant_name,product_id,category,decision,reason\n"
            "C-1,Acme,SKU-1,toys,reject,missing_docs: no report\n"
            "C-2,Bolt,SKU-2,toys,approve,\n"
            "C-3,Cog,SKU-3,batteries,reject,expired certificate\n"
            "C-4,Dyn,SKU-4,toys,need_info,\n"
            "C-5,Eon,SKU-5,toys,reject,missing_docs but we guarantee a fix\n"
            "C-6,Fab,,toys,reject,missing_docs\n"
        )
        return target

    def test_processes_every_case(self, tmp_path: Path):
        result = CliRunner().invoke(
            main,
            [
                "batch",
                str(self._input(tmp_path)),
                "--templates",
                str(TEMPLATES),
                "--guidelines",
                str(GUIDELINES),
                "--output",
                str(tmp_path / "out"),
            ],
        )
        assert result.exit_code == 0
        assert "total         6" in result.output

    def test_mixed_outcomes_are_reported(self, tmp_path: Path):
        out = tmp_path / "out"
        CliRunner().invoke(
            main,
            [
                "batch",
                str(self._input(tmp_path)),
                "--templates",
                str(TEMPLATES),
                "--guidelines",
                str(GUIDELINES),
                "--output",
                str(out),
            ],
        )
        report = json.loads((out / "full_report.json").read_text())
        summary = report["summary"]
        assert summary["total"] == 6
        assert summary["ready"] >= 3
        assert summary["needs_review"] >= 1
        assert summary["failed"] == 1

    def test_ready_only_filters_output(self, tmp_path: Path):
        out = tmp_path / "out"
        CliRunner().invoke(
            main,
            [
                "batch",
                str(self._input(tmp_path)),
                "--templates",
                str(TEMPLATES),
                "--guidelines",
                str(GUIDELINES),
                "--output",
                str(out),
                "--format",
                "json",
                "--ready-only",
            ],
        )
        emitted = json.loads((out / "blurbs.json").read_text())["blurbs"]
        full = json.loads((out / "full_report.json").read_text())["blurbs"]
        assert all(b["status"] == "ready" for b in emitted)
        assert len(emitted) < len(full)

    def test_full_report_always_has_everything(self, tmp_path: Path):
        out = tmp_path / "out"
        CliRunner().invoke(
            main,
            [
                "batch",
                str(self._input(tmp_path)),
                "--templates",
                str(TEMPLATES),
                "--guidelines",
                str(GUIDELINES),
                "--output",
                str(out),
                "--ready-only",
            ],
        )
        assert len(json.loads((out / "full_report.json").read_text())["blurbs"]) == 6

    def test_csv_output_is_importable(self, tmp_path: Path):
        out = tmp_path / "out"
        CliRunner().invoke(
            main,
            [
                "batch",
                str(self._input(tmp_path)),
                "--templates",
                str(TEMPLATES),
                "--guidelines",
                str(GUIDELINES),
                "--output",
                str(out),
                "--format",
                "csv",
            ],
        )
        text = (out / "blurbs.csv").read_text()
        assert "case_id" in text
        assert "template_version" in text

    def test_template_version_is_recorded_for_audit(self, tmp_path: Path):
        out = tmp_path / "out"
        CliRunner().invoke(
            main,
            [
                "batch",
                str(self._input(tmp_path)),
                "--templates",
                str(TEMPLATES),
                "--guidelines",
                str(GUIDELINES),
                "--output",
                str(out),
            ],
        )
        blurbs = json.loads((out / "full_report.json").read_text())["blurbs"]
        rendered = [b for b in blurbs if b["template_id"]]
        assert rendered
        assert all(b["template_version"] == 3 for b in rendered)
