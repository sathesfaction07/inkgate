# BlurbGen

Generates merchant-facing decision messages from version-controlled templates, then scores each one against writing guidelines and refuses to mark it ready if it fails. Runs with no credentials at all using a deterministic rule engine; AWS Bedrock or Google Vertex can be swapped in for classification and scoring.

---

## The Problem

When a compliance decision is made, someone has to write to the merchant explaining it. At volume this is done from templates, and two things go wrong.

**The template becomes untraceable.** Templates live in code, or in a wiki, or in someone's snippets file. Six months later a merchant disputes the wording of a message and nobody can say which version they received. The template has been edited four times since.

**Nothing checks the output.** A template plus a variable substitution feels safe, so nothing verifies the result. Then a message goes out reading *"Hello {merchant_name}"* because a field was empty, or containing a phrase legal asked you to stop using two quarters ago. Template systems fail silently: the substitution "succeeded", it just produced something you would never send.

The second problem has a subtler version that I hit while building this. If you score output on a weighted average and gate on a threshold, a single serious defect can pass. More on that below — it is the most interesting thing in the project.

---

## How It Works

```
case -> classify -> select template -> render -> score -> gate -> ready | needs_review | failed
```

**Classify** decides which template applies. The rule engine matches on decision, then reason keywords, then category, scoring specificity so a targeted template beats a generic one. An LLM provider can do this instead when the case data is messy.

**Render** substitutes variables and refuses to proceed if a declared required variable is missing or empty. A missing variable is a `failed` outcome, not a message with a hole in it.

**Score** judges the rendered text against `guidelines.yaml` — banned phrases, required elements, length bounds — producing a 0–100 score with a per-criterion breakdown.

**Gate** is the part that matters. Two independent checks:

- **Objective defects** are deterministic facts about the text: a leftover `{placeholder}`, a banned phrase, empty output, length over the template maximum. Any one of them forces `needs_review` no matter what the score says.
- **Threshold checks** on the quality score and the classification confidence.

Nothing is ever auto-sent. The output is `ready` (a human can send it as-is), `needs_review` (a human must look), or `failed` (nothing usable was produced).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          CLI (blurb-gen)                             │
│                                                                     │
│   generate        batch            templates         providers      │
│   one case        CSV/JSON in,     list + validate   availability   │
│   + criteria      CSV/JSON/xlsx    the YAML          check          │
│   breakdown       out                                               │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    PIPELINE (core/pipeline.py)                       │
│                                                                     │
│   1. provider.classify(case, templates)                             │
│         └─ falls back to RuleProvider if the provider returns None  │
│   2. registry.get(template_id)                                      │
│   3. render(template, case.variables())                             │
│         └─ MissingVariablesError -> status FAILED                   │
│   4. provider.score(text, template, guidelines)                     │
│         └─ falls back to RuleProvider scoring if None               │
│   5. objective_defects(...)    <- always runs, provider-independent  │
│   6. decide_status(...)        <- pure function, returns the gate    │
└──────┬──────────────────────────────────────────┬───────────────────┘
       │                                          │
       ▼                                          ▼
┌────────────────────────────┐   ┌────────────────────────────────────┐
│  TEMPLATES (templates/)     │   │  PROVIDERS (providers/)             │
│                             │   │                                     │
│  registry.py                │   │  base.py     Provider ABC           │
│   - versioned YAML load     │   │              classify() + score()   │
│   - specificity selection   │   │                                     │
│   - validate(): 5 checks    │   │  rules.py    deterministic,         │
│                             │   │              always available       │
│  render.py                  │   │                                     │
│   - substitute + verify     │   │  llm.py      BedrockProvider        │
│   - leftover detection      │   │              VertexProvider         │
└────────────────────────────┘   └────────────────────────────────────┘
       │                                          │
       ▼                                          ▼
┌────────────────────────────┐   ┌────────────────────────────────────┐
│  data/templates.yaml        │   │  GATE (core/gate.py)                │
│   version: 3                │   │                                     │
│   5 templates, each with    │   │  objective_defects()                │
│   its own version           │   │   - leftover placeholders           │
│                             │   │   - banned phrases                  │
│  data/guidelines.yaml       │   │   - empty text                      │
│   version: 2                │   │   - over max length                 │
│   8 banned phrases          │   │                                     │
│   4 required elements,      │   │  decide_status()                    │
│   decision-scoped           │   │   defect -> NEEDS_REVIEW always     │
└────────────────────────────┘   └────────────────────────────────────┘
```

---

## Project Structure

```
blurb-gen/
├── src/blurb_gen/
│   ├── cli.py                 generate / batch / templates / providers
│   ├── config.py              Pydantic Settings, BG_ prefix
│   ├── models.py              Case, Classification, QualityReport, Blurb
│   ├── io.py                  CSV/JSON in, CSV/JSON/Excel out
│   ├── templates/
│   │   ├── registry.py        versioned load, selection, validation
│   │   └── render.py          substitution + leftover detection
│   ├── core/
│   │   ├── guidelines.py      banned phrases, decision-scoped elements
│   │   ├── gate.py            objective_defects + decide_status
│   │   └── pipeline.py        orchestration
│   └── providers/
│       ├── base.py            Provider ABC
│       ├── rules.py           deterministic classify + score
│       └── llm.py             Bedrock + Vertex
├── data/
│   ├── templates.yaml         set version 3, 5 templates
│   ├── guidelines.yaml        version 2
│   └── sample_cases.csv
├── tests/                     120 tests
└── docs/adr/
```

---

## Running

```bash
bash setup.sh
source .venv/bin/activate

# Which providers can this machine actually use?
blurb-gen providers

# Are the templates well-formed?
blurb-gen templates --validate
blurb-gen templates                 # list them with versions and conditions

# One case
blurb-gen generate \
  --case-id BG-2001 --decision reject \
  --merchant "Acme Supplies" --product-id SKU-99001 \
  --reason "missing_docs: no CPC on file"

# Show why it scored what it scored
blurb-gen generate --case-id BG-2001 --decision approve \
  --product-id SKU-1 --show-criteria

# Batch, CSV in and CSV out
blurb-gen batch data/sample_cases.csv --output out/

# Only emit what passed the gate (the full report still contains everything)
blurb-gen batch data/sample_cases.csv --output out/ --ready-only

# Excel, or an LLM provider
blurb-gen batch data/sample_cases.csv --output out/ --format excel
blurb-gen batch data/sample_cases.csv --output out/ --provider bedrock
```

---

## Usage Reference

### `generate`

| Option | Purpose |
|:--|:--|
| `--case-id` | Required |
| `--decision` | Required: `approve`, `reject`, `need_info`, `escalate` |
| `--merchant`, `--product-id`, `--category`, `--reason` | Case fields used for selection and substitution |
| `--provider` | `rules` (default), `bedrock`, `vertex` |
| `--templates`, `--guidelines` | Override the YAML paths |
| `--quality-threshold` | Default 75 |
| `--show-criteria` | Print the per-criterion pass/fail breakdown |

### `batch INPUT_PATH`

CSV or JSON in. Unknown columns are carried into `extras` and become usable template variables, so adding a `missing_items` column to your CSV makes `{missing_items}` available without a code change.

Writes `blurbs.{csv,json,xlsx}` plus `full_report.json`. The report always contains every case including failures, even when `--ready-only` trims the main output.

### `templates`

Lists each template with its version, the conditions it applies under, its required variables and length bounds. `--validate` runs five structural checks and exits non-zero on any problem:

- body uses a variable not declared in `required_variables`
- `required_variables` declares something the body never uses
- duplicate template id
- template version above the set version
- `max_chars` below the unrendered body length, so it could never pass

### `providers`

Availability of each provider plus the loaded guidelines version and counts.

---

## Testing

```bash
pytest                      # 120 tests
pytest tests/unit -v
pytest tests/integration -v # CLI end to end via CliRunner
pytest --cov=blurb_gen --cov-report=term-missing
```

The gate is a pure function, so every combination of score, confidence and defect is a fast direct test. `tests/unit/test_gate.py` includes a test named `test_weighted_average_alone_cannot_catch_a_single_defect` that exists specifically to pin the bug described below.

Both YAML files that ship with the repo are covered: `test_repo_template_file_is_valid` runs the validator against `data/templates.yaml`, and `test_every_shipped_template_scores_full_marks` renders all five and asserts each scores 100 against the shipped guidelines. If someone edits a template and breaks it, the suite fails.

---

## Configuration

```bash
BG_TEMPLATES_PATH=data/templates.yaml
BG_GUIDELINES_PATH=data/guidelines.yaml

BG_PROVIDER=rules              # rules | bedrock | vertex
BG_QUALITY_THRESHOLD=75
BG_CONFIDENCE_THRESHOLD=60

BG_AWS_REGION=us-east-1
BG_BEDROCK_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0

BG_GCP_PROJECT=
BG_GCP_LOCATION=us-central1
BG_GEMINI_MODEL=gemini-1.5-flash

BG_OUTPUT_FORMAT=csv
```

---

## Tradeoffs and Decisions I Made Along the Way

**The weighted average had a hole in it, and my own test suite found it.** I scored blurbs by summing criterion weights and gating at 75. Then a test failed that I expected to pass: a blurb containing "we guarantee" — a phrase on the banned list — came back `ready`. I did the arithmetic and it was worse than one bad case. With seven criteria totalling weight 15, a single failure lands between 80 and 93. **No individual criterion failure could ever gate anything.** A leaked `{placeholder}` scored 80 and would have gone to a merchant reading "Hello {merchant_name}".

The fix was to stop treating all failures as fungible. Some things are objective facts about the text rather than quality judgements: a placeholder either leaked or it did not, a banned phrase is either present or absent. Those became `objective_defects()`, and any one of them forces `needs_review` regardless of score. The score still does useful work for the fuzzy stuff — tone, completeness — but it is no longer the only thing standing between a defect and a merchant.

The general lesson I took: an aggregate score is the wrong instrument for a binary compliance requirement. Averaging is for things that trade off against each other.

**Objective checks run regardless of which provider scored.** This follows from the above and it is the load-bearing decision in the codebase. If you enable Bedrock, the LLM produces the quality score, but `objective_defects()` still runs deterministically in Python. A model should never be the thing that decides whether a `{placeholder}` leaked into merchant-facing text — that is a `str` operation, not a judgement call. The model is allowed to be wrong about tone. It is not allowed to be the only check on facts.

**Templates are data with version numbers, not strings in code.** Both the set and each individual template carry a version, and every generated blurb records `template_id` and `template_version`. Six months later you can answer "which wording did this merchant receive" from the output CSV. Keeping them in code would have been less machinery, and would have made that question unanswerable.

The cost is a validator, because YAML lets you write templates that are structurally broken in ways Python would have caught at import time. `templates --validate` covers the five failure modes I could think of. There are certainly more.

**The deterministic provider is the default even though the LLM is better at classification.** Template rendering is deterministic by nature — once you know which template applies, there is no intelligence left to add. So the only place a model genuinely helps is deciding *which* template applies when the case data is ambiguous, and judging subjective tone. That is a narrow enough gap that shipping rule-based as the default was easy to justify: `git clone`, `bash setup.sh`, and it works with no AWS account. The accuracy tradeoff is real and it is documented rather than hidden.

**The scorer and the generator are separate calls, deliberately.** When the LLM provider is active, one call classifies and a second, independent call scores the rendered output. It would be cheaper to do both at once. But a model asked to produce something and simultaneously judge it will mark its own homework, and the scoring prompt explicitly says "you are reviewing, not rewriting" for the same reason — a judge that can rewrite will fix the problem and report a pass, and you lose the signal that the template needed fixing.

**Decision-scoped guidelines came out of watching real output.** My first `guidelines.yaml` demanded a "recourse" element — a route to contest — on every message. Running the sample batch, every approval flagged `missing required element: recourse`, which is nonsense: there is nothing to contest about an approval. Rather than pad the approval template with fake contest language to satisfy the checker, I added `applies_to_decisions` so an element can be scoped. Mean quality on the sample set went from 96.7 to 100, and the 100 is now honest rather than the 96.7 being noise.

**Everything is in memory and batches are sequential.** No checkpointing, no concurrency. Generation is CPU-cheap under the rule provider, so this is fine — but with an LLM provider a batch of 5,000 becomes two serial API calls per case with no resume. AdaptiveFetch in this portfolio solves exactly that problem and I deliberately did not import its machinery here; this project is about the gate, and adding a governor would have buried it.

**One bad case never stops the batch.** `generate_batch` wraps each case, and an exception becomes a `failed` row carrying the exception text. The usual cost applies: a broken `templates.yaml` path produces N failures that look like N bad cases. `templates --validate` and `providers` exist as the pre-flight checks for that.

---

## Stack

| Concern | Choice |
|:--|:--|
| Language | Python 3.11+ |
| Config + models | Pydantic, Pydantic Settings |
| Templates | PyYAML, `str.replace` substitution |
| CLI | Click |
| LLM | boto3 (Bedrock), google-cloud-aiplatform (Vertex) |
| Output | stdlib csv/json, openpyxl |
| Tests | pytest, Click's CliRunner |
| Lint | ruff |
