# ADR 002: Objective defects hard-gate, independently of the quality score

## Status

Accepted

## Context

The original design scored a rendered blurb on a weighted average of criteria and gated at a threshold. Criteria and weights came from `guidelines.yaml`:

| Criterion | Weight |
|:--|:--|
| no_unfilled_placeholders | 3 |
| length_within_bounds | 1 |
| no_banned_phrases | 3 |
| has_greeting | 1 |
| has_product_reference | 2 |
| has_next_steps | 3 |
| has_recourse | 2 |

Score is `100 * (earned weight) / (total weight)`, with a default threshold of 75. Clean and easy to explain.

A test then failed that I had expected to pass. A blurb whose `reason` field contained "we guarantee" — a phrase on the banned list — came back `ready`. Working the arithmetic showed this was not a one-off:

```
total weight = 15
only no_banned_phrases         fails -> 80.0
only no_unfilled_placeholders  fails -> 80.0
only has_next_steps            fails -> 80.0
only has_recourse              fails -> 86.7
only length_within_bounds      fails -> 93.3
only has_greeting              fails -> 93.3
```

**No single criterion failure could gate anything.** The lowest a one-failure blurb could score was 80, comfortably above 75. Worst of all, a leaked `{placeholder}` scored 80, meaning the system would have marked "Hello {merchant_name}" as ready to send.

Raising the threshold does not fix this. To catch a single weight-3 failure the threshold has to exceed 80, which then also rejects any blurb with two weight-1 failures — a much less serious condition. The threshold is a single dial being asked to express two different policies.

The real error was conceptual. A weighted average models criteria that **trade off** against each other. But "does this text contain a phrase legal banned" does not trade off against "does it have a greeting". One is a binary compliance requirement; the other is a quality preference. Averaging them together says a banned phrase can be compensated for by good structure elsewhere, which is false.

## Decision

Split the checks by kind.

**Objective defects** are deterministic facts about the rendered text, computed in `core/gate.py`:

- a leftover `{placeholder}`
- a banned phrase from the guidelines
- empty output
- length above the template maximum

Any one of them forces `NEEDS_REVIEW`, regardless of score, confidence, or which provider ran.

**Quality score and classification confidence** keep their thresholds and continue to catch the fuzzy problems — missing structural elements, weak template match, tone.

Both live in one pure function so the whole policy is readable in one place:

```python
def decide_status(confidence, report, defects, confidence_threshold, quality_threshold):
    status = Status.READY
    if defects:
        status = Status.NEEDS_REVIEW
    if confidence < confidence_threshold:
        status = Status.NEEDS_REVIEW
    if report.score < quality_threshold:
        status = Status.NEEDS_REVIEW
    return status, issues
```

The second decision matters as much as the first: **`objective_defects()` runs regardless of which provider produced the score.** With Bedrock enabled the LLM judges quality, but the placeholder and banned-phrase checks still run as Python string operations. A model is allowed to be wrong about tone. It is not allowed to be the only thing checking whether a template variable leaked into merchant-facing text — that is a fact, not a judgement, and it should never depend on an inference call succeeding.

The banned-phrase check therefore appears in two places: as a scored criterion (so it contributes to the number, which is informative) and as an objective defect (so it gates). `decide_status` de-duplicates the issue string so a reviewer sees it once.

## Verified behaviour

Against the shipped templates and guidelines:

```
$ blurb-gen generate --case-id BG-2002 --decision reject \
    --product-id SKU-99002 --reason "missing_docs, we guarantee a fast turnaround"

status          needs_review
quality         80 via rules
issue           banned phrase present: 'we guarantee'
  [FAIL] no_banned_phrases (weight 3)
```

Score 80 with a threshold of 75 — the score alone says pass. The gate says no. `tests/unit/test_gate.py::TestWhyTheGateExists` pins this exact case so the regression cannot come back.

A mixed batch of six exercises all three outcomes: 2 `ready`, 2 `needs_review` (both caught by banned phrases at score 80), 2 `failed` (one missing variable, one unmatched decision).

## Consequences

**Good**

- A defect can no longer be averaged away by good structure elsewhere
- The two policies are now separately tunable. Thresholds move without weakening the hard checks
- Hard checks do not depend on a network call or a model behaving. They work identically under every provider, including with no credentials at all
- `decide_status` is a pure function of five arguments, so every combination is a fast unit test
- The score is still reported even when a defect gates, so a reviewer sees both "how good was it" and "what is specifically wrong"

**Bad**

- Two mechanisms to understand instead of one. "Why was this gated" now has two possible answers
- The defect list is hardcoded in `objective_defects()` rather than configured. Adding a new hard check is a code change, unlike adding a scored criterion which is a YAML edit. That asymmetry is deliberate — hard gates should be harder to add than soft ones — but it will annoy someone eventually
- Banned phrases are checked twice, which is duplicated work and a little confusing when reading the code

**Neutral**

- Substring matching is the whole banned-phrase implementation, so it cannot catch a paraphrase. "We can assure you of a fast fix" passes. Catching intent rather than wording is what the LLM judge is for, and that path is advisory
- Length is checked twice with different severity: over `max_chars` is an objective defect, but under `min_chars` only affects the score. A too-short message is a quality problem; a too-long one may not fit the destination field
- The default thresholds (75 quality, 60 confidence) remain judgement calls with no measurement behind them
