#!/usr/bin/env bash
set -euo pipefail

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'
info() { echo -e "${BLUE}==>${NC} $1"; }
ok()   { echo -e "${GREEN} ok ${NC} $1"; }
warn() { echo -e "${YELLOW}warn${NC} $1"; }
fail() { echo -e "${RED}fail${NC} $1"; exit 1; }

WITH_BEDROCK=0
WITH_VERTEX=0
WITH_EXCEL=0
for arg in "$@"; do
    case "$arg" in
        --bedrock) WITH_BEDROCK=1 ;;
        --vertex)  WITH_VERTEX=1 ;;
        --excel)   WITH_EXCEL=1 ;;
        --all)     WITH_BEDROCK=1; WITH_VERTEX=1; WITH_EXCEL=1 ;;
        -h|--help)
            cat <<'USAGE'
Usage: bash setup.sh [options]

  --bedrock   also install boto3 for the AWS Bedrock provider
  --vertex    also install google-cloud-aiplatform for the Vertex provider
  --excel     also install openpyxl for .xlsx output
  --all       everything
  -h          this message

With no options you get a fully working install. The default provider is the
deterministic rule engine, which needs no credentials of any kind.
USAGE
            exit 0 ;;
        *) fail "unknown option: $arg (try --help)" ;;
    esac
done

info "Checking Python"
command -v python3 >/dev/null 2>&1 || {
    echo "python3 was not found. Install it first:"
    echo "  macOS:         brew install python@3.12"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv"
    echo "  RHEL/Fedora:   sudo dnf install python3"
    fail "python3 missing"
}

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [ "$(python3 -c 'import sys; print(1 if sys.version_info >= (3,11) else 0)')" != "1" ]; then
    echo "Python 3.11 or newer is required. Found $PY_VER."
    echo "  macOS:         brew install python@3.12"
    echo "  Ubuntu/Debian: sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python3.12 python3.12-venv"
    fail "python $PY_VER too old"
fi
ok "Python $PY_VER"

info "Creating virtual environment"
[ -d .venv ] || python3 -m venv .venv || fail "could not create .venv (Debian/Ubuntu: sudo apt install python3-venv)"
ok ".venv ready"

EXTRAS="dev"
[ "$WITH_BEDROCK" = "1" ] && EXTRAS="$EXTRAS,bedrock"
[ "$WITH_VERTEX" = "1" ] && EXTRAS="$EXTRAS,vertex"
[ "$WITH_EXCEL" = "1" ] && EXTRAS="$EXTRAS,excel"

info "Installing dependencies [$EXTRAS]"
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e ".[$EXTRAS]" || fail "pip install failed"
ok "dependencies installed"

info "Verifying imports"
.venv/bin/python - <<'PYCHECK' || fail "core imports failed"
import click, yaml                                     # noqa: F401
from pydantic_settings import BaseSettings             # noqa: F401
from blurb_gen.core import Pipeline, objective_defects  # noqa: F401
from blurb_gen.providers import get_provider            # noqa: F401
from blurb_gen.templates import TemplateRegistry        # noqa: F401
PYCHECK
ok "imports resolve"

info "Validating the shipped template and guideline files"
.venv/bin/python - <<'PYCHECK' || fail "data files are invalid"
from pathlib import Path
from blurb_gen.core.guidelines import Guidelines
from blurb_gen.templates.registry import TemplateRegistry

registry = TemplateRegistry.load(Path("data/templates.yaml"))
problems = registry.validate()
if problems:
    for p in problems:
        print(f"     {p}")
    raise SystemExit(1)

guidelines = Guidelines.load(Path("data/guidelines.yaml"))
print(
    f"     {len(registry.all())} templates (set v{registry.version}), "
    f"guidelines v{guidelines.version}: "
    f"{len(guidelines.banned_phrases)} banned phrases, "
    f"{len(guidelines.required_elements)} required elements"
)
PYCHECK
ok "data files valid"

info "End-to-end check: generate, gate, and write"
.venv/bin/python - <<'PYCHECK' || fail "end-to-end check failed"
import csv, shutil, tempfile
from pathlib import Path

from blurb_gen.config import Settings
from blurb_gen.core.pipeline import Pipeline, summarise
from blurb_gen.io import write_csv
from blurb_gen.models import Case, Decision, Status

work = Path(tempfile.mkdtemp(prefix="blurb-gen-verify-"))
try:
    cfg = Settings(
        templates_path=Path("data/templates.yaml"),
        guidelines_path=Path("data/guidelines.yaml"),
        provider="rules",
    )
    pipeline = Pipeline(cfg)

    clean = pipeline.generate(
        Case(
            case_id="V-1",
            merchant_name="Verify Co",
            product_id="SKU-V1",
            decision=Decision.REJECT,
            reason="missing_docs: nothing attached",
        )
    )
    assert clean.status is Status.READY, f"clean case was {clean.status}: {clean.issues}"
    assert clean.template_version > 0, "template version was not recorded"
    assert "{" not in clean.text, "rendered text still contains a placeholder"

    banned = pipeline.generate(
        Case(
            case_id="V-2",
            merchant_name="Verify Co",
            product_id="SKU-V2",
            decision=Decision.REJECT,
            reason="missing_docs and we guarantee a fix",
        )
    )
    assert banned.status is Status.NEEDS_REVIEW, "banned phrase was not gated"
    assert banned.quality_score > cfg.quality_threshold, (
        "the gate test is not meaningful unless the score passes the threshold"
    )

    broken = pipeline.generate(Case(case_id="V-3", decision=Decision.ESCALATE))
    assert broken.status is Status.FAILED, "unmatched case should fail"

    blurbs = [clean, banned, broken]
    target = work / "out" / "blurbs.csv"
    write_csv(blurbs, target)
    with target.open(encoding="utf-8-sig") as handle:
        assert len(list(csv.DictReader(handle))) == 3, "csv row count wrong"

    summary = summarise(blurbs)
    assert (summary["ready"], summary["needs_review"], summary["failed"]) == (1, 1, 1)

    print(
        f"     ready=1 needs_review=1 failed=1; "
        f"gate held a score of {banned.quality_score:.0f} "
        f"against a threshold of {cfg.quality_threshold:.0f}"
    )
finally:
    shutil.rmtree(work, ignore_errors=True)
PYCHECK
ok "end-to-end verified"

info "Running the test suite"
.venv/bin/python -m pytest -q || fail "tests failed"
ok "tests pass"

if [ "$WITH_BEDROCK" = "1" ]; then
    info "Checking AWS credentials for the bedrock provider"
    if .venv/bin/python -c "import boto3; boto3.client('sts').get_caller_identity()" >/dev/null 2>&1; then
        ok "AWS credentials resolve"
    else
        warn "boto3 installed but no usable AWS credentials found."
        warn "  Configure with: aws configure   (or set AWS_PROFILE)"
        warn "  The rules provider works without this."
    fi
fi

if [ "$WITH_VERTEX" = "1" ]; then
    info "Checking Google credentials for the vertex provider"
    if [ -z "${BG_GCP_PROJECT:-}" ]; then
        warn "BG_GCP_PROJECT is not set, so the vertex provider will report unavailable."
        warn "  Set it and run: gcloud auth application-default login"
    else
        ok "BG_GCP_PROJECT=$BG_GCP_PROJECT"
    fi
fi

cat <<'DONE'

Setup complete.

  source .venv/bin/activate

  blurb-gen providers                  # what can this machine use
  blurb-gen templates --validate       # are the templates sound
  blurb-gen batch data/sample_cases.csv --output out/

Nothing is ever auto-sent. Every blurb comes back ready, needs_review, or failed.
DONE
