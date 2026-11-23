import csv
import json
from pathlib import Path

import pytest

from blurb_gen.io import load_cases, write_csv, write_excel, write_json
from blurb_gen.models import Blurb, Decision, Status


@pytest.fixture
def blurbs() -> list[Blurb]:
    return [
        Blurb(
            case_id="C-1",
            status=Status.READY,
            text="Hello Acme, all good.",
            template_id="approve_standard",
            template_version=3,
            decision=Decision.APPROVE,
            classification_confidence=95.0,
            classification_source="rules",
            quality_score=100.0,
            scored_by="rules",
        ),
        Blurb(
            case_id="C-2",
            status=Status.NEEDS_REVIEW,
            text="Hello Bolt, we guarantee something.",
            template_id="reject_generic",
            template_version=3,
            decision=Decision.REJECT,
            classification_confidence=60.0,
            classification_source="rules",
            quality_score=55.0,
            scored_by="rules",
            issues=["banned phrase present: 'we guarantee'"],
        ),
        Blurb(case_id="C-3", status=Status.FAILED, error="no template matched this case"),
    ]


class TestLoadCases:
    def test_reads_csv(self, tmp_path: Path):
        target = tmp_path / "in.csv"
        target.write_text(
            "case_id,merchant_name,product_id,decision,reason\n"
            "C-1,Acme,SKU-1,reject,missing_docs\n"
            "C-2,Bolt,SKU-2,approve,\n"
        )
        cases = load_cases(target)
        assert len(cases) == 2
        assert cases[0].decision is Decision.REJECT
        assert cases[1].decision is Decision.APPROVE

    def test_reads_json_list(self, tmp_path: Path):
        target = tmp_path / "in.json"
        target.write_text(
            json.dumps([{"case_id": "C-1", "decision": "approve", "product_id": "SKU-1"}])
        )
        assert load_cases(target)[0].case_id == "C-1"

    def test_reads_single_json_object(self, tmp_path: Path):
        target = tmp_path / "in.json"
        target.write_text(json.dumps({"case_id": "C-9", "decision": "reject"}))
        assert len(load_cases(target)) == 1

    def test_unknown_decision_becomes_none(self, tmp_path: Path):
        target = tmp_path / "in.csv"
        target.write_text("case_id,decision\nC-1,banana\n")
        assert load_cases(target)[0].decision is None

    def test_unknown_columns_land_in_extras(self, tmp_path: Path):
        target = tmp_path / "in.csv"
        target.write_text("case_id,decision,missing_items\nC-1,reject,test report\n")
        assert load_cases(target)[0].extras["missing_items"] == "test report"

    def test_extras_are_available_as_variables(self, tmp_path: Path):
        target = tmp_path / "in.csv"
        target.write_text("case_id,decision,custom_field\nC-1,reject,value here\n")
        assert load_cases(target)[0].variables()["custom_field"] == "value here"

    def test_blank_rows_skipped(self, tmp_path: Path):
        target = tmp_path / "in.csv"
        target.write_text("case_id,decision\nC-1,reject\n,\n")
        assert len(load_cases(target)) == 1

    def test_missing_case_id_becomes_unknown(self, tmp_path: Path):
        target = tmp_path / "in.csv"
        target.write_text("case_id,decision\n,reject\n")
        assert load_cases(target)[0].case_id == "UNKNOWN"

    def test_whitespace_is_trimmed(self, tmp_path: Path):
        target = tmp_path / "in.csv"
        target.write_text("case_id,merchant_name\n  C-1  ,  Acme  \n")
        case = load_cases(target)[0]
        assert case.case_id == "C-1"
        assert case.merchant_name == "Acme"

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_cases(tmp_path / "nope.csv")


class TestWriters:
    def test_csv_has_all_rows_and_stable_header(self, tmp_path: Path, blurbs):
        path = tmp_path / "out" / "blurbs.csv"
        write_csv(blurbs, path)
        with path.open(encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            assert reader.fieldnames[0] == "case_id"
            assert reader.fieldnames[-1] == "blurb"
        assert len(rows) == 3
        assert rows[1]["status"] == "needs_review"

    def test_csv_joins_issues_readably(self, tmp_path: Path, blurbs):
        path = tmp_path / "blurbs.csv"
        write_csv(blurbs, path)
        assert "we guarantee" in path.read_text()

    def test_json_includes_summary_and_blurbs(self, tmp_path: Path, blurbs):
        path = tmp_path / "blurbs.json"
        write_json(blurbs, {"total": 3, "ready": 1}, path)
        payload = json.loads(path.read_text())
        assert payload["summary"]["total"] == 3
        assert len(payload["blurbs"]) == 3

    def test_excel_written(self, tmp_path: Path, blurbs):
        path = tmp_path / "blurbs.xlsx"
        write_excel(blurbs, path)
        assert path.exists()

    def test_writers_create_parent_directories(self, tmp_path: Path, blurbs):
        path = tmp_path / "deep" / "nested" / "blurbs.csv"
        write_csv(blurbs, path)
        assert path.exists()

    def test_empty_list_is_safe(self, tmp_path: Path):
        write_csv([], tmp_path / "empty.csv")
        write_json([], {"total": 0}, tmp_path / "empty.json")
        assert (tmp_path / "empty.csv").exists()
        assert (tmp_path / "empty.json").exists()
