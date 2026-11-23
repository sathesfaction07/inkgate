# ADR 001: Templates are versioned data, not strings in code

## Status

Accepted

## Context

Merchant-facing message templates have to live somewhere. The three usual options:

- **In Python** — a dict of format strings, or a function per template. Simplest thing that works. Any change is a code change, review, and deploy.
- **In a wiki or shared doc** — what actually happens in practice, because the people who own the wording are not the people who own the repo. The copy in the doc and the copy in production drift immediately.
- **In a data file in the repo** — editable without touching code, still version-controlled.

Two requirements pushed against the first option.

**Traceability.** A merchant disputes the wording of a message they received four months ago. To answer, you need to know which template produced it *and which revision of that template*. With format strings in Python you can find the current wording and dig through git history for the rest, if you happen to know the deploy date. There is no field on the output that answers the question directly.

**Ownership.** The wording is owned by compliance and legal, not engineering. If every phrasing tweak requires a pull request, either engineering becomes a bottleneck or the templates stop being maintained and people start editing messages by hand — which defeats the point of having templates.

## Decision

Templates live in `data/templates.yaml`. Two levels of version:

- The **set** has a version, bumped on any change to the file.
- Each **template** has its own version, bumped when that template's body or conditions change.

Every generated blurb records `template_id` and `template_version` in its output row. The CSV a reviewer imports carries the provenance with it.

Each template declares more than its body:

```yaml
- id: reject_missing_documentation
  version: 3
  applies_to:
    decision: reject
    reasons: [missing_docs, incomplete, no_certificate]
  required_variables: [merchant_name, product_id, reason]
  length:
    min_chars: 200
    max_chars: 1100
  body: |
    ...
```

`applies_to` drives selection, `required_variables` is checked before rendering, and `length` feeds the quality scorer.

Because YAML accepts structurally broken content that Python would have rejected at import time, `inkgate templates --validate` runs five checks and exits non-zero on any failure:

1. Body uses a `{variable}` not declared in `required_variables`
2. `required_variables` declares something the body never uses
3. Duplicate template id
4. Template version above the set version
5. `max_chars` below the length of the unrendered body, so the template could never pass its own bounds

Check 1 is the important one. It is exactly the class of bug that produces "Hello {merchant_name}" in a real message, and it is caught by a command rather than by a merchant.

## Consequences

**Good**

- "Which wording did this merchant get" is answerable from the output file, months later, with no git archaeology
- Wording changes are a YAML edit, reviewable by someone who does not read Python
- Selection conditions are declarative and sit next to the text they select, so the relationship between "when does this apply" and "what does it say" is visible in one place
- The validator catches a real failure mode before deploy. `test_repo_template_file_is_valid` runs it against the shipped file in CI
- Length bounds and required variables are data, so the scorer and renderer both read the same source of truth

**Bad**

- A validator is real machinery that exists only because the data format is loose. In Python, an undeclared variable would be a `NameError` at import
- Two version numbers is more bookkeeping than one, and nothing enforces that an editor bumps them. A commit that changes a body without touching `version` will pass validation
- Selection logic is now split: the conditions are in YAML, the scoring of those conditions is in `Template.matches()`. Understanding why a particular template was chosen means reading both

**Neutral**

- Specificity scoring (`decision` = 1 point, matching `reasons` = +2, matching `categories` = +1) is a judgement call about which signal should dominate. It is deliberately simple and will not express "prefer A over B except when C"
- Ties break alphabetically by template id, which is arbitrary but at least deterministic and testable
- Nothing supports rendering an *older* version of a template. The registry loads one file and that file has one version of each template. Reproducing a historical message exactly would require checking out the old YAML
