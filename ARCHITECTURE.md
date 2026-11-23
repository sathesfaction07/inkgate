# Inkgate — Technical Architecture

## Overview

Inkgate turns a compliance decision into a merchant-facing message. It classifies a case to select a template from a version-controlled YAML set, renders it, scores the result against writing guidelines, and then gates it — nothing is marked ready to send unless it clears both a quality threshold and a set of deterministic defect checks. The default provider is a rule engine that needs no credentials; AWS Bedrock or Google Vertex can be swapped in for classification and scoring.

**Design principle:** An aggregate score is the wrong instrument for a binary compliance requirement. Quality is judged on a weighted average; objective defects — a leaked `{placeholder}`, a banned phrase — hard-gate regardless of score, and are always checked in Python rather than delegated to a model.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            CLI (inkgate)                                │
│                                                                         │
│  ┌────────────┐  ┌────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ generate   │  │ batch      │  │ templates    │  │ providers      │  │
│  │ one case   │  │ CSV/JSON   │  │ list, or     │  │ availability   │  │
│  │ + optional │  │ in -> CSV/ │  │ --validate   │  │ + guidelines   │  │
│  │ criteria   │  │ JSON/xlsx  │  │ (5 checks,   │  │   version      │  │
│  │ breakdown  │  │ + report   │  │  exit 1)     │  │                │  │
│  └─────┬──────┘  └─────┬──────┘  └──────┬───────┘  └────────────────┘  │
└────────┼───────────────┼────────────────┼──────────────────────────────┘
         │               │                │
         └───────┬───────┘                └──> TemplateRegistry.validate()
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        IO LAYER (io.py)                                   │
│                                                                         │
│  load_cases()  CSV or JSON -> list[Case]                                 │
│                unknown columns land in Case.extras and become            │
│                usable template variables with no code change             │
│                                                                         │
│  write_csv / write_json / write_excel  <- fixed ROW_FIELDS order         │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     PIPELINE (core/pipeline.py)                           │
│                                                                         │
│  1. CLASSIFY   provider.classify(case, registry.all())                   │
│                  None and provider is not rules -> RuleProvider retry    │
│                  still None -> FAILED "no template matched"              │
│                                                                         │
│  2. RESOLVE    registry.get(classification.template_id)                  │
│                  unknown id -> FAILED (guards a hallucinating provider)  │
│                                                                         │
│  3. RENDER     render(template, case.variables())                        │
│                  MissingVariablesError -> FAILED, names the variable     │
│                                                                         │
│  4. SCORE      provider.score(text, template, guidelines)                │
│                  None -> RuleProvider scoring                            │
│                                                                         │
│  5. DEFECTS    objective_defects(text, template, guidelines)             │
│                  ALWAYS runs. Never delegated to a provider.             │
│                                                                         │
│  6. GATE       decide_status(...) -> READY | NEEDS_REVIEW                │
└──────┬──────────────────────────────────┬───────────────────────────────┘
       │                                  │
       ▼                                  ▼
┌────────────────────────────┐  ┌────────────────────────────────────────┐
│  TEMPLATES (templates/)     │  │  GATE (core/gate.py)                    │
│                             │  │                                         │
│  registry.py                │  │  objective_defects() - deterministic:   │
│   TemplateSet   version     │  │    leftover {placeholder}               │
│   Template      version     │  │    banned phrase present                │
│                 applies_to  │  │    empty text                           │
│                 required_   │  │    length over template max             │
│                   variables │  │                                         │
│                 length      │  │  decide_status() - pure function:       │
│                             │  │    any defect      -> NEEDS_REVIEW      │
│   select()  specificity:    │  │    confidence low  -> NEEDS_REVIEW      │
│     decision       = 1      │  │    score low       -> NEEDS_REVIEW      │
│     + reason match = +2     │  │    else            -> READY             │
│     + category     = +1     │  └────────────────────────────────────────┘
│     ties break by id        │
│                             │  ┌────────────────────────────────────────┐
│   validate()  5 checks      │  │  GUIDELINES (core/guidelines.py)        │
│                             │  │                                         │
│  render.py                  │  │  banned_phrases                         │
│   substitute + verify all   │  │  required_elements, each with a weight  │
│   required vars present     │  │    and optional applies_to_decisions    │
│   leftover_placeholders()   │  │  tone_notes -> LLM prompt only          │
└────────────────────────────┘  └────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     PROVIDERS (providers/)                                │
│                                                                         │
│  Provider (ABC):  classify() -> Classification | None                    │
│                   score()    -> QualityReport | None                     │
│                   is_available() -> bool                                 │
│                                                                         │
│  ┌──────────────────────┐  ┌────────────────────────────────────────┐  │
│  │ RuleProvider          │  │ BedrockProvider / VertexProvider        │  │
│  │ rules.py              │  │ llm.py                                  │  │
│  │                       │  │                                         │  │
│  │ classify: specificity │  │ classify: CLASSIFY_SYSTEM, 5 rules,     │  │
│  │   scoring, confidence │  │   must pick from the supplied id list   │  │
│  │   60/75/90/95         │  │   or return "none"                      │  │
│  │                       │  │                                         │  │
│  │ score: weighted       │  │ score: SCORE_SYSTEM, review not rewrite │  │
│  │   criteria, per-      │  │                                         │  │
│  │   criterion detail    │  │ temperature 0, 3-tier JSON extraction,  │  │
│  │                       │  │ every failure returns None -> fallback   │  │
│  │ always available      │  │ lazy SDK import                         │  │
│  └──────────────────────┘  └────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Components

### 1. CLI (`src/blurb_gen/cli.py`)

Four Click commands. Entry point `inkgate`.

| Command | Purpose |
|:--|:--|
| `generate` | One case from flags. Prints status, template + version, both scores, every issue, and the rendered text. `--show-criteria` adds the per-criterion pass/fail breakdown |
| `batch INPUT_PATH` | CSV or JSON in. Writes `blurbs.{csv,json,xlsx}` plus `full_report.json`. `--ready-only` trims the main output but never the report |
| `templates` | Lists templates with versions, conditions, variables and bounds. `--validate` runs the structural checks and exits 1 on any problem |
| `providers` | Availability per provider, plus loaded guidelines version and counts |

CLI flags are gathered into a dict, `None` entries dropped, and the rest handed to `Settings(**overrides)` so environment variables remain in force for anything not passed. `_configure_logging` pushes `botocore`, `boto3`, `urllib3` and `google` down to WARNING.

### 2. Models (`src/blurb_gen/models.py`)

Pydantic throughout. Two enums (`Decision`, `Status`) and five models:

- **`Case`** — input. `variables()` merges the known fields with `extras` and drops empties, so an unset field is absent rather than blank. That is what lets `render()` distinguish "not supplied" from "supplied as empty string" — both are treated as missing.
- **`Classification`** — chosen `template_id`, `decision`, `confidence` (0–100, validated), `rationale`, and `source` naming who decided.
- **`CriterionScore`** / **`QualityReport`** — per-criterion result with weight and detail; the report carries the score, the criteria, free-text issues, and `scored_by`.
- **`Blurb`** — output. Carries the text plus full provenance: template id and version, both scores, both sources, issues, error.

`Blurb.as_row()` produces the flat dict used by every writer, so CSV, Excel and JSON cannot drift apart.

### 3. Template Registry (`src/blurb_gen/templates/registry.py`)

**`TemplateSet`** has a version and a list of **`Template`**, each with its own version, an `applies_to` block, `required_variables`, `LengthBounds`, and a `body`.

`LengthBounds` validates `max_chars > min_chars` at load, so an impossible template fails on `TemplateRegistry.load()` rather than silently never passing.

**Selection** — `Template.matches()` returns a specificity score: 1 for a decision match, +2 if a `reasons` keyword appears in the case reason, +1 if the category matches. A zero on any declared condition disqualifies the template entirely. `select()` takes the highest score and breaks ties alphabetically by id.

The +2 for reasons over +1 for category is deliberate: the reason text describes *why* this decision was made, which is closer to what the message needs to say than the product category is.

**Introspection** — `placeholders` parses `{lowercase_snake}` out of the body. `undeclared_placeholders()` and `unused_declarations()` are set differences against `required_variables`, and are what the validator uses.

**`validate()`** returns a list of human-readable problems:

| Check | Catches |
|:--|:--|
| undeclared placeholder | the "Hello {merchant_name}" bug, before it ships |
| unused declaration | a variable required for no reason, blocking valid cases |
| duplicate id | two templates fighting over the same name |
| version above set version | a bookkeeping mistake |
| `max_chars` below unrendered body length | a template that can never pass its own bounds |

### 4. Rendering (`src/blurb_gen/templates/render.py`)

`render()` drops empty values, computes `required_variables - supplied`, and raises `MissingVariablesError` naming the missing set if non-empty. Only then does it substitute. Failing before producing anything is the point — a partially rendered message is worse than no message.

`_tidy()` strips trailing whitespace per line and collapses runs of blank lines, so YAML block scalars do not produce ragged output.

`leftover_placeholders()` is the post-render check, used by both the rule scorer and the gate.

### 5. Guidelines (`src/blurb_gen/core/guidelines.py`)

`banned_phrases`, `required_elements`, `tone_notes`, all versioned.

**`RequiredElement`** has `id`, `any_of` markers, a `weight`, and `applies_to_decisions`. An empty `applies_to_decisions` means it applies to every decision; otherwise only the listed ones. `elements_for(decision)` does the filtering.

That scoping exists because of observed behaviour rather than design foresight — see Quality Gate Design below.

`as_prompt_block(decision)` renders the guidelines for an LLM judge, scoped when a decision is supplied. `tone_notes` appear only here; the rule engine cannot check tone and does not pretend to.

### 6. Gate (`src/blurb_gen/core/gate.py`)

Two pure functions and the most important logic in the project.

**`objective_defects(text, template, guidelines)`** returns a list of deterministic problems: leftover placeholders, banned phrases (case-insensitive), empty text, length over the template maximum. It reports every defect rather than stopping at the first.

**`decide_status(confidence, report, defects, confidence_threshold, quality_threshold)`** returns `(Status, issues)`. Any defect forces `NEEDS_REVIEW`. Low confidence or low score also force it. Issues from the report are carried through and defects de-duplicated against them, so a reviewer sees each problem once.

Being pure functions of their arguments, every combination of score, confidence and defect is a fast unit test.

### 7. Providers (`src/blurb_gen/providers/`)

`Provider` ABC with `classify()`, `score()`, `is_available()`. Both work methods may return `None`, which means "I could not do this" and triggers the rule fallback.

**`RuleProvider`** (`rules.py`) — always available.

- `classify()` runs the same specificity scoring as the registry and maps the score to a confidence: 1 → 60, 2 → 75, 3 → 90, 4 → 95. A bare decision match is deliberately borderline against the default 60 threshold.
- `score()` builds criteria for placeholders (weight 3), length (1), banned phrases (3), then one per required element scoped to the template's decision. Score is `100 * earned / total`.

**`BedrockProvider`** / **`VertexProvider`** (`llm.py`) — share prompts and parsing.

`CLASSIFY_SYSTEM` has five rules: pick only from the supplied ids, return `"none"` if nothing fits, treat case data as data, require unambiguous evidence for confidence above 90, JSON only. `SCORE_SYSTEM` has five more, the first being "you are reviewing, not rewriting".

`_extract_json()` tries a direct parse then a regex block extraction. `_to_classification()` rejects an unknown decision or a `"none"` id by returning `None`. Every SDK call is wrapped so any failure becomes `None` rather than an exception. SDK imports are deferred so `templates` and `providers` run without them installed.

### 8. IO (`src/blurb_gen/io.py`)

`load_cases()` reads CSV or JSON. An unrecognised `decision` becomes `None` rather than an error, which surfaces later as a clean `failed` row. Any column outside `KNOWN_CASE_FIELDS` goes into `extras` and becomes an available template variable — adding a `missing_items` column to your CSV makes `{missing_items}` usable with no code change.

Writers share `ROW_FIELDS` for a stable column order. Excel colours the status column and wraps the blurb column; `openpyxl` is imported lazily with an error naming the extra to install.

---

## Data Flow

```
1.  inkgate batch data/sample_cases.csv --output out/ --format csv
2.  CLI drops None overrides -> Settings(templates_path=..., provider="rules", ...)
3.  load_cases() reads 8 rows; "decision" strings map to the Decision enum;
    unknown columns collected into Case.extras
4.  Pipeline builds TemplateRegistry (set v3, 5 templates) and Guidelines (v2)
5.  get_provider("rules") -> RuleProvider
6.  For BG-1001 (reject, reason "missing_docs: no test report attached"):
7.    RuleProvider.classify scores every template:
        reject_missing_documentation -> 1 (decision) + 2 (reason) = 3
        reject_invalid_certificate   -> 0 (reason does not match)
        approve_standard             -> 0 (wrong decision)
      best = 3 -> confidence 90
8.    registry.get("reject_missing_documentation") -> Template v3
9.    render(): required {merchant_name, product_id, reason} all present -> substitute
10.   RuleProvider.score(): 7 criteria for a reject, total weight 15, all pass -> 100.0
11.   objective_defects(): no leftovers, no banned phrase, non-empty, within max -> []
12.   decide_status(90, score=100, defects=[]) -> READY, issues=[]
13. Blurb records template_id, template_version=3, both scores, both sources
14. Repeat for the remaining 7 cases; a raising case becomes a FAILED row, not a crash
15. summarise() -> {total, ready, needs_review, failed, mean_quality, templates_used}
16. write_csv(emitted, out/blurbs.csv) + write_json(all, out/full_report.json)
17. CLI prints the counts and the paths written
```

---

## Quality Gate Design

This is the part of the project worth reading, and it exists because the first design was wrong in a way that testing caught.

### The weighted average could not gate anything

Scoring was a weighted average of criteria with a threshold of 75. For a rejection, seven criteria total weight 15:

| Criterion | Weight | Score if this alone fails |
|:--|:--|:--|
| no_unfilled_placeholders | 3 | 80.0 |
| no_banned_phrases | 3 | 80.0 |
| has_next_steps | 3 | 80.0 |
| has_product_reference | 2 | 86.7 |
| has_recourse | 2 | 86.7 |
| length_within_bounds | 1 | 93.3 |
| has_greeting | 1 | 93.3 |

**No single failure could drop below 80.** With a threshold of 75, every one-defect blurb passed. A test I expected to pass failed instead, and the arithmetic showed the problem was structural rather than a bad threshold: a blurb containing a phrase legal had banned was marked ready, and so was one containing a leaked `{placeholder}` — a message that would reach a merchant reading "Hello {merchant_name}".

Raising the threshold does not fix it. Catching a single weight-3 failure needs a threshold above 80, which then also rejects two weight-1 failures — a strictly less serious condition. One dial was being asked to express two different policies.

The conceptual error: a weighted average models criteria that **trade off** against each other. "Contains a banned phrase" does not trade off against "has a greeting". One is a binary compliance requirement, the other a quality preference. Averaging them asserts that good structure can compensate for a banned phrase, which is false.

### Splitting by kind

Objective defects are facts about the text and are checked deterministically. Quality is a judgement and keeps its score and threshold. Any defect forces `NEEDS_REVIEW` regardless of the score.

Verified against the shipped data:

```
$ inkgate generate --case-id BG-2002 --decision reject \
    --product-id SKU-99002 --reason "missing_docs, we guarantee a fast turnaround"

status          needs_review
quality         80 via rules
issue           banned phrase present: 'we guarantee'
  [FAIL] no_banned_phrases (weight 3)
```

Score 80 against a threshold of 75 — the score says pass, the gate says no. `tests/unit/test_gate.py::TestWhyTheGateExists` pins exactly this so the regression cannot return, and `setup.sh` asserts it too, including an assertion that the score still exceeds the threshold so the test stays meaningful.

### Objective checks never move to the model

`objective_defects()` runs regardless of provider. With Bedrock enabled the LLM produces the quality score, but the placeholder and banned-phrase checks remain Python string operations.

The reasoning: a model may reasonably be wrong about tone. It must not be the only thing checking whether a template variable leaked into merchant-facing text, because that is a fact obtainable with a regex and should not depend on an inference call succeeding, returning parseable JSON, or the model being in a good mood.

This is why banned phrases are checked twice — once as a scored criterion so the number is informative, once as a defect so it gates. The duplication is deliberate and `decide_status` de-duplicates the resulting issue string.

### Generation and judgement are separate calls

Under an LLM provider, classification and scoring are two independent invocations. Combining them would be cheaper and is the obvious optimisation.

It is not done because a model asked to produce and simultaneously judge marks its own homework. `SCORE_SYSTEM` opens with "you are reviewing, not rewriting" for the same reason: a judge permitted to rewrite will quietly fix the problem and report a pass, and the signal that the *template* needed fixing is lost. The point of scoring is to find bad templates, not to patch bad output.

### Decision-scoped elements came from watching output

The first `guidelines.yaml` required a "recourse" element on every message. Running the sample batch, every approval flagged `missing required element: recourse` — nonsense, because an approval has nothing to contest.

Two options: pad the approval template with hollow contest language to satisfy the checker, or let an element declare which decisions it applies to. The first would have corrupted the message to satisfy the tool. `applies_to_decisions` was added instead, and mean quality on the sample set moved from 96.7 to 100 — where the 100 is honest and the 96.7 had been noise.

The general shape of the mistake is worth naming: a global rule applied to a domain where the requirements are not global. Easy to write, and it produces false positives that train reviewers to ignore the tool.

### Limitations

**Banned phrases are substring matches.** "We can assure you of a fast fix" passes cleanly. Catching intent rather than wording is what the LLM judge is for, and that path is advisory rather than gating — so a paraphrased promise gets through the hard gate by construction.

**Confidence from the rule engine is a lookup, not a probability.** 60/75/90/95 map from a specificity score of 1/2/3/4. It orders cases sensibly and means nothing in absolute terms. The default confidence threshold of 60 therefore lets a bare decision match through at exactly the boundary, which is a judgement call about how much a decision-only match should be trusted.

**Length is checked asymmetrically.** Over `max_chars` is an objective defect; under `min_chars` only affects the score. Too long may not fit the destination field, which is a correctness problem; too short is a quality problem.

**Adding a hard check is a code change.** Scored criteria are YAML, defects are Python. The asymmetry is intentional — a hard gate should be harder to add than a soft one — but it means an operator cannot add one without an engineer.

**Nothing regenerates.** A gated blurb is handed to a human, not fed back for another attempt. A retry loop would need a stopping rule and a way to avoid a model rewriting until it happens to pass its own judge, which is the failure mode the review/rewrite separation exists to prevent.

---

## Configuration

Environment variables with the `BG_` prefix, or a `.env` file. No list-typed fields.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BG_",
        env_file=".env",
        extra="ignore",
    )

    templates_path: Path = Path("data/templates.yaml")
    guidelines_path: Path = Path("data/guidelines.yaml")

    provider: str = "rules"
    template_version: int = 0
    quality_threshold: float = 75.0
    confidence_threshold: float = 60.0

    aws_region: str = "us-east-1"
    bedrock_model: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    gcp_project: str = ""
    gcp_location: str = "us-central1"
    gemini_model: str = "gemini-1.5-flash"

    output_format: str = "csv"
    log_level: str = "INFO"
```

---

## Running

```bash
bash setup.sh                 # validates the shipped YAML and asserts the gate holds
bash setup.sh --bedrock       # + boto3, checks AWS credentials resolve
bash setup.sh --vertex        # + Vertex SDK, checks BG_GCP_PROJECT is set
bash setup.sh --excel         # + openpyxl
bash setup.sh --all
source .venv/bin/activate

inkgate providers
inkgate templates
inkgate templates --validate

inkgate generate \
  --case-id BG-2001 --decision reject \
  --merchant "Acme Supplies" --product-id SKU-99001 \
  --reason "missing_docs: no CPC on file"

inkgate generate --case-id BG-2001 --decision approve \
  --product-id SKU-1 --show-criteria

inkgate batch data/sample_cases.csv --output out/
inkgate batch data/sample_cases.csv --output out/ --ready-only
inkgate batch data/sample_cases.csv --output out/ --format excel
inkgate batch data/sample_cases.csv --output out/ --provider bedrock
```

---

## Testing

```bash
pytest                          # 120 tests
pytest tests/unit -v            # registry, render, rules, guidelines, gate, io
pytest tests/integration -v     # all four CLI commands via CliRunner
pytest --cov=blurb_gen --cov-report=term-missing
```

Coverage by file:

- `test_registry.py` — specificity selection and every fallback path, case-insensitive matching, placeholder introspection, `LengthBounds` validation, all five validator checks, and `test_repo_template_file_is_valid` which runs the validator against the shipped `data/templates.yaml`
- `test_render_and_rules.py` — substitution, missing and empty-string variables, blank-line collapsing, leftover detection, rule classification and confidence ordering, and every scoring criterion
- `test_guidelines.py` — decision scoping, and `test_every_shipped_template_scores_full_marks` which renders all five shipped templates and asserts each scores 100 against the shipped guidelines
- `test_gate.py` — every defect type, every gate combination, de-duplication, and `TestWhyTheGateExists` which reproduces the weighted-average hole and asserts the gate closes it
- `test_io.py` — CSV and JSON loading, unknown decisions, extras becoming variables, whitespace trimming, all three writers, stable column order, empty input
- `integration/test_cli.py` — all four commands, `--validate` exit code 1 on a broken file, the banned-phrase gate end to end, `--ready-only` filtering while the full report keeps everything, and template version recorded for audit

The two shipped YAML files are covered by tests, so editing a template and breaking it fails the suite rather than shipping. CI also runs `inkgate templates --validate` as a separate step.

Not covered: the real Bedrock and Vertex calls. Their prompt construction, JSON extraction and `None`-on-failure behaviour are unit-testable and tested; the network path is not exercised.
