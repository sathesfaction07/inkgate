import csv
import json
from pathlib import Path
from typing import Any

from .models import Blurb, Case, Decision

ROW_FIELDS = [
    "case_id",
    "status",
    "decision",
    "template_id",
    "template_version",
    "classification_confidence",
    "classification_source",
    "quality_score",
    "scored_by",
    "issues",
    "error",
    "blurb",
]

KNOWN_CASE_FIELDS = {
    "case_id",
    "merchant_name",
    "product_id",
    "category",
    "marketplace",
    "decision",
    "reason",
    "notes",
}


def load_cases(path: Path) -> list[Case]:
    if not path.exists():
        raise FileNotFoundError(f"input not found: {path}")

    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text())
        rows = raw if isinstance(raw, list) else [raw]
        return [_to_case(r) for r in rows]

    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [_to_case(row) for row in csv.DictReader(handle) if any(row.values())]


def _to_case(row: dict[str, Any]) -> Case:
    cleaned = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}

    decision_raw = str(cleaned.get("decision", "")).strip().lower()
    decision: Decision | None = None
    if decision_raw:
        try:
            decision = Decision(decision_raw)
        except ValueError:
            decision = None

    extras = {
        k: str(v)
        for k, v in cleaned.items()
        if k not in KNOWN_CASE_FIELDS and v not in (None, "")
    }

    return Case(
        case_id=str(cleaned.get("case_id", "")).strip() or "UNKNOWN",
        merchant_name=str(cleaned.get("merchant_name", "") or "Merchant"),
        product_id=str(cleaned.get("product_id", "")),
        category=str(cleaned.get("category", "")),
        marketplace=str(cleaned.get("marketplace", "") or "US"),
        decision=decision,
        reason=str(cleaned.get("reason", "")),
        notes=str(cleaned.get("notes", "")),
        extras=extras,
    )


def write_csv(blurbs: list[Blurb], path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=ROW_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(b.as_row() for b in blurbs)
    return str(path)


def write_json(blurbs: list[Blurb], summary: dict[str, Any], path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"summary": summary, "blurbs": [b.model_dump(mode="json") for b in blurbs]},
            indent=2,
        )
    )
    return str(path)


def write_excel(blurbs: list[Blurb], path: Path) -> str:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
    except ImportError as exc:
        raise RuntimeError(
            "excel output needs openpyxl. Install with: pip install 'inkgate[excel]'"
        ) from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "blurbs"
    sheet.append(ROW_FIELDS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    colours = {"ready": "00A36C", "needs_review": "B8860B", "failed": "C00000"}
    for blurb in blurbs:
        row = blurb.as_row()
        sheet.append([row.get(f, "") for f in ROW_FIELDS])
        colour = colours.get(blurb.status.value)
        if colour:
            sheet.cell(sheet.max_row, ROW_FIELDS.index("status") + 1).font = Font(color=colour)
        sheet.cell(sheet.max_row, ROW_FIELDS.index("blurb") + 1).alignment = Alignment(
            wrap_text=True, vertical="top"
        )

    widths = {"blurb": 80, "issues": 40, "case_id": 14, "template_id": 24}
    for index, field in enumerate(ROW_FIELDS, start=1):
        letter = sheet.cell(1, index).column_letter
        sheet.column_dimensions[letter].width = widths.get(field, 18)

    workbook.save(path)
    return str(path)
