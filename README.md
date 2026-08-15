# RubricTrace

[![CI](https://github.com/armanzareian/rubrictrace/actions/workflows/ci.yml/badge.svg)](https://github.com/armanzareian/rubrictrace/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB.svg)](pyproject.toml)

Offline audits for LLM-as-judge result logs.

RubricTrace reads exported judgment records and reports reviewable signs that an evaluation may be
too unstable to trust as a release gate: score drift across repeated runs, pass/fail conflicts,
threshold flips, pairwise position effects, and missing rationale or evidence fields. It runs
locally with no runtime dependencies and makes no network requests.

## Why RubricTrace

- **Judgment-row audit:** inspect the records behind aggregate eval scores before relying on them.
- **Deterministic diagnostics:** produce repeatable findings for local development and CI.
- **Reviewable evidence:** include compact score ranges, verdict sets, positions, and record IDs.
- **Agreement metrics:** summarize repeated-judge agreement and threshold sensitivity from the
  supplied log, including deterministic confidence intervals for observed proportions.
- **Stable fingerprints:** identify findings across report formats and future baselines.
- **Policy exit codes:** fail only when findings meet the severity threshold you choose.
- **Labeled evaluation:** measure detector behavior against a small JSON fixture suite.
- **Small integration surface:** use the CLI, or call the typed Python API directly.

RubricTrace is a log auditor. It does not decide whether a model answer is correct, and it does not
replace human review of rubrics, judge instructions, or representative eval data. Findings are meant to
make instability and missing evidence visible before those issues are hidden inside averages.

## Quickstart

Run from a checkout:

```bash
git clone https://github.com/armanzareian/rubrictrace.git
cd rubrictrace
PYTHONPATH=src python3 -m rubrictrace audit \
  --records examples/judgments/records.jsonl \
  --policy examples/judgments/policy.json \
  --fail-on critical
```

Install the CLI:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
rubrictrace --version
```

Run the included labeled evaluation:

```bash
rubrictrace eval --suite examples/judgments/suite.json
```

Summarize repeated-judge agreement and threshold sensitivity:

```bash
rubrictrace metrics \
  --records examples/judgments/records.jsonl \
  --policy examples/judgments/policy.json
```

## Judgment Records

Input is JSON Lines by default. Each row is one judge observation:

```json
{"case_id":"refund-001","candidate_id":"answer-a","run_id":"judge-a","rubric":"groundedness","score":4,"verdict":"pass","position":"first","pair_id":"refund-pair","rationale":"Matches the policy text.","evidence":["doc-refunds"]}
```

Required fields:

- `case_id`: stable evaluation item identifier.
- `candidate_id`: model, answer, or system variant being judged.
- `run_id`: stable identifier for the judge run or repeated sample.
- `rubric`: rubric dimension such as groundedness, safety, style, or correctness.
- `score`: numeric judge score.

Optional fields:

- `verdict`: `pass`, `fail`, `accept`, `reject`, `win`, `lose`, `yes`, or `no`.
- `position`: pairwise presentation position such as `first`, `second`, `left`, `right`, `a`, or `b`.
- `pair_id`: stable ID for a pairwise comparison.
- `rationale`: judge explanation text.
- `evidence`: list of source IDs, quote IDs, or other evidence handles.
- `metadata`: object preserved for callers but not interpreted by the current scanner.

Input files are capped at 10 MiB. RubricTrace reports record identifiers and short structured
evidence; it does not print full rationales in text output.

### CSV Records

CSV exports can be audited with explicit field mappings. This is useful for spreadsheet-style
evaluation logs or benchmark exports whose column names do not match RubricTrace's native JSONL
field names.

```bash
rubrictrace audit \
  --records examples/judgments/records.csv \
  --input-format csv \
  --map case_id=item \
  --map candidate_id=answer \
  --map run_id=judge \
  --map rubric=dimension \
  --map score=judge_score \
  --map verdict=decision \
  --map position=order \
  --map pair_id=pair \
  --map rationale=why \
  --map evidence=evidence_refs \
  --fail-on critical
```

Required CSV mappings are `case_id`, `candidate_id`, `run_id`, `rubric`, and `score`. Optional
mappings are `verdict`, `position`, `pair_id`, `rationale`, and `evidence`. Evidence cells use
semicolon-separated handles such as `doc-1;doc-2`. CSV validation errors identify the row, mapped
column, and expected type without printing the full row.

### Pairwise CSV Records

Pairwise benchmark exports can be audited with a named CSV adapter that expands each comparison row
into one normalized judgment record for the left candidate and one for the right candidate:

```bash
rubrictrace audit \
  --records examples/judgments/pairwise.csv \
  --input-format pairwise-csv \
  --fail-on critical
```

The default pairwise columns are:

- `case_id`: stable evaluation item identifier.
- `pair_id`: stable identifier for the compared answer pair.
- `run_id`: judge run, replicate, or annotation identifier.
- `rubric`: rubric dimension for the comparison.
- `left_candidate` and `right_candidate`: candidate IDs as presented to the judge.
- `left_score` and `right_score`: numeric scores assigned to each side.
- `winner`: optional side or candidate ID; accepts `left`, `right`, `a`, `b`, `1`, `2`, `tie`,
  `draw`, or either candidate ID.
- `rationale`: optional judge explanation copied to both normalized records.
- `evidence`: optional semicolon-separated evidence handles copied to both normalized records.

Use `--map` with `--input-format pairwise-csv` to override a preset column name:

```bash
rubrictrace audit \
  --records pairwise-export.csv \
  --input-format pairwise-csv \
  --map case_id=item_id \
  --map left_candidate=model_a \
  --map right_candidate=model_b \
  --map winner=chosen_side
```

Pairwise rows preserve presentation position as `left` and `right`, and winner labels normalize to
`win` and `lose` verdicts. This lets the same instability, threshold-flip, verdict-conflict, and
position-bias detectors run over pairwise comparison exports.

### Rubric CSV Records

Single-answer rubric exports often store one answer per row with a separate score column for each
rubric dimension. The `rubric-csv` adapter expands each score column into its own normalized
judgment record:

```bash
rubrictrace audit \
  --records examples/judgments/rubric_safety.csv \
  --input-format rubric-csv \
  --fail-on critical
```

Default rubric CSV columns are:

- `case_id`: stable evaluation item identifier.
- `candidate_id`: model, answer, or system variant being judged.
- `run_id`: judge run, replicate, or annotation identifier.
- `<rubric>_score`: one or more score columns, such as `safety_score` or `groundedness_score`.
- `verdict`: optional verdict copied to each normalized rubric record.
- `position`: optional presentation position copied to each normalized rubric record.
- `pair_id`: optional pairwise identifier copied to each normalized rubric record.
- `rationale`: optional judge explanation copied to each normalized rubric record.
- `evidence`: optional semicolon-separated evidence handles copied to each normalized record.

Use `--map` to adapt exports with different identifier or score column names:

```bash
rubrictrace audit \
  --records examples/judgments/rubric_retrieval.csv \
  --input-format rubric-csv \
  --map case_id=question_id \
  --map candidate_id=answer_id \
  --map run_id=judge_id \
  --map verdict=decision \
  --map rationale=why \
  --map evidence=source_ids \
  --map score_columns=groundedness:grounded,coverage:coverage \
  --fail-on critical
```

When `score_columns` is not provided, every header ending in `_score` becomes a rubric after
removing that suffix. For example, `safety_score` becomes rubric `safety`. Rubric CSV validation
errors identify the row, mapped column, and expected type without printing the full row.

## Policy

Policies are JSON:

```json
{
  "fail_on": "high",
  "score_delta": 1.5,
  "position_delta": 1.0,
  "decision_threshold": 3.0,
  "require_evidence": true,
  "require_rationale": true,
  "enabled_detectors": [
    "missing_rationale",
    "missing_evidence",
    "score_instability",
    "verdict_conflict",
    "threshold_flip",
    "position_bias"
  ],
  "severity_overrides": {
    "position_bias": "high"
  },
  "rubric_thresholds": {
    "preference": {
      "position_delta": 0.75
    }
  },
  "suppressions": [
    "0123456789abcdef"
  ]
}
```

`fail_on` accepts `low`, `medium`, `high`, or `critical`. The CLI exits with code `1` when any
issue meets or exceeds that threshold. Malformed inputs exit with code `2`.

Optional policy controls:

- `enabled_detectors`: run only the listed detectors.
- `severity_overrides`: change the severity assigned to a detector without changing its fingerprint.
- `rubric_thresholds`: override `score_delta`, `position_delta`, or `decision_threshold` for a
  specific rubric.
- `suppressions`: hide reviewed findings by fingerprint from active issue counts and exit-code
  decisions while keeping them visible in JSON under `suppressed_issues`.

CLI flags override policy-file values:

```bash
rubrictrace audit \
  --records examples/judgments/records.jsonl \
  --policy examples/judgments/policy.json \
  --score-delta 2.0 \
  --fail-on medium \
  --format json
```

Compact CI output and review controls are available from the CLI:

```bash
rubrictrace audit \
  --records examples/judgments/records.jsonl \
  --policy examples/judgments/policy.json \
  --format ci \
  --disable-detector missing_evidence \
  --severity-override position_bias=high \
  --suppress-fingerprint 0123456789abcdef
```

## Detectors

- `missing_rationale`: a record lacks a reviewable rationale when policy requires one.
- `missing_evidence`: a record lacks evidence handles when policy requires them.
- `score_instability`: repeated judgments for the same case, candidate, and rubric have a score
  range at or above `score_delta`.
- `verdict_conflict`: repeated judgments disagree between passing and failing verdicts.
- `threshold_flip`: repeated scores for the same case, candidate, and rubric straddle
  `decision_threshold`.
- `position_bias`: a candidate's mean score differs across pairwise presentation positions by at
  least `position_delta`.

The checks are deterministic heuristics over supplied logs. They surface rows that deserve review;
they do not prove the cause of a disagreement.

Suppression and report-format settings do not change issue fingerprints. Fingerprints are computed
before findings are partitioned into active and suppressed sets.

## Metrics

The `metrics` command reports deterministic summaries over the supplied judgment records:

- repeated case/candidate/rubric groups with run counts, score range, mean score, verdict counts,
  majority verdict agreement, Wilson-score confidence intervals, and distance from the decision
  threshold;
- pairwise position-effect rows by case, pair, candidate, and rubric;
- threshold-sensitivity rows showing how many repeated groups would be flagged at several
  `score_delta` settings;
- threshold-sensitivity rows showing how many pairwise position groups would be flagged at several
  `position_delta` settings.

Use `--format json` when feeding the summary into dashboards or notebooks. The output describes
only the supplied records and should not be read as a broader statement about model quality.
Confidence intervals are deterministic 95% Wilson-score intervals over observed proportions such as
verdict agreement and flagged-group rates; they are not random bootstrap estimates.

## Labeled Evaluation

The `eval` command compares scanner output against a JSON suite's `expected_issues` labels. Text
and JSON output include suite-level precision, recall, F1, detector-level metrics, false-positive
keys, and false-negative keys.

When a detector emits an issue that is not listed in `expected_issues`, the result also includes a
false-positive review note with the issue key, severity, stable fingerprint, detector message, and
compact structured evidence. Use these notes to decide whether the labeled suite should include the
finding or whether policy thresholds or detector behavior need adjustment. The evaluation describes
only the supplied fixture suite; it is not a benchmark claim about broader model quality.

## Development

```bash
make test
make quality
make demo
make eval
make metrics
```

The project is intentionally dependency-light. Optional `ruff` and `mypy` configuration is included
for teams that want stricter local checks.

## Python API

```python
from pathlib import Path

from rubrictrace import audit_records, load_policy, load_records, summarize_records

records = load_records(Path("examples/judgments/records.jsonl"))
policy = load_policy(Path("examples/judgments/policy.json"))
report = audit_records(records, policy)

for issue in report.issues:
    print(issue.detector, issue.severity, issue.fingerprint)

summary = summarize_records(records, policy)
print(summary["threshold_sensitivity"]["score_instability"])
```

CSV inputs use the same normalized record model:

```python
from pathlib import Path

from rubrictrace import load_csv_records

records = load_csv_records(
    Path("examples/judgments/records.csv"),
    {
        "case_id": "item",
        "candidate_id": "answer",
        "run_id": "judge",
        "rubric": "dimension",
        "score": "judge_score",
    },
)
```

Pairwise CSV exports can be expanded through the preset adapter:

```python
from pathlib import Path

from rubrictrace import load_pairwise_csv_records

records = load_pairwise_csv_records(Path("examples/judgments/pairwise.csv"))
```

Single-answer rubric CSV exports can also be expanded into normalized records:

```python
from pathlib import Path

from rubrictrace import load_rubric_csv_records

records = load_rubric_csv_records(Path("examples/judgments/rubric_safety.csv"))
```

## Limitations

- JSONL is the default input format; generic CSV inputs require explicit mappings for required
  fields.
- Pairwise CSV inputs assume each row compares exactly two presented candidates.
- Rubric CSV inputs assume each physical row represents one answer and one or more score columns.
- Position bias checks require repeated records for the same `case_id`, `pair_id`,
  `candidate_id`, and `rubric` across different positions.
- Evidence handles are checked for presence, not semantic correctness.
- Score and verdict instability depend on repeated or replicated judgment rows being present.
