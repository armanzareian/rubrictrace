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

## Development

```bash
make test
make quality
make demo
make eval
```

The project is intentionally dependency-light. Optional `ruff` and `mypy` configuration is included
for teams that want stricter local checks.

## Python API

```python
from pathlib import Path

from rubrictrace import audit_records, load_policy, load_records

records = load_records(Path("examples/judgments/records.jsonl"))
policy = load_policy(Path("examples/judgments/policy.json"))
report = audit_records(records, policy)

for issue in report.issues:
    print(issue.detector, issue.severity, issue.fingerprint)
```

## Limitations

- The initial loader expects native RubricTrace JSONL.
- Position bias checks require repeated records for the same `case_id`, `pair_id`,
  `candidate_id`, and `rubric` across different positions.
- Evidence handles are checked for presence, not semantic correctness.
- Score and verdict instability depend on repeated or replicated judgment rows being present.
