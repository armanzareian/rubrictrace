# Architecture

RubricTrace is a dependency-light Python package with a CLI and a small typed API.

## Components

- `rubrictrace.io` loads JSONL judgment records, explicitly mapped CSV records, pairwise CSV
  comparison exports, single-answer rubric CSV exports, JSON policies, and baseline files with
  bounded file-size checks.
- `rubrictrace.models` defines records, policy controls, issues, reports, and severity ordering.
- `rubrictrace.scanner` runs deterministic detectors over normalized records.
- `rubrictrace.metrics` summarizes repeated-judge agreement and threshold sensitivity.
- `rubrictrace.report` renders text, JSON, compact CI, Markdown summary, and SARIF reports.
- `rubrictrace.evaluation` compares scanner output against labeled fixture suites.
- `rubrictrace.cli` wires the commands, output formats, and exit codes.

## Data Flow

1. The loader parses JSONL rows, mapped CSV rows, expanded pairwise CSV comparisons, or expanded
   rubric CSV score columns into `JudgeRecord` values.
2. A `Policy` is created from defaults, an optional policy file, reviewed baseline fingerprints,
   and CLI overrides.
3. The scanner groups records by stable case, candidate, rubric, and pairwise identifiers.
4. Enabled detectors emit `Issue` values with stable fingerprints.
5. Severity overrides are applied before reviewed-fingerprint suppressions partition findings into
   active and suppressed sets.
6. The report renderer emits text, JSON, compact CI, Markdown summary, or SARIF output.
7. The CLI exits with `1` only when an active finding meets or exceeds the configured severity
   threshold.

The metrics command uses the same normalized records and policy thresholds, but emits descriptive
summaries instead of findings. It groups repeated case/candidate/rubric records for score and
verdict agreement, and groups pairwise records by case, pair, candidate, and rubric for position
threshold sensitivity.

The evaluation command audits suite records, compares issue keys with `expected_issues`, and reports
detector-level precision, recall, and F1. False positives carry review notes with the emitted issue
fingerprint, detector message, severity, and compact structured evidence so a suite maintainer can
decide whether labels, thresholds, or detector behavior need adjustment.

SARIF report output includes active findings as SARIF results, detector names as rule IDs, stable
RubricTrace fingerprints in `partialFingerprints`, run-level counts, and the audit input path as a
physical location when the CLI can provide it. Suppressed findings are not emitted as results, but
their count remains available on the run properties.

Baseline files are JSON objects containing reviewed finding fingerprints. The baseline loader
accepts explicit `suppressions` or report-shaped `findings`, `issues`, and `suppressed_issues`
arrays. Each entry may be a fingerprint string or an object with a `fingerprint` field. Baseline
fingerprints are merged with policy suppressions and one-off CLI suppressions before the scanner
partitions active and suppressed issues.

## Detector Design

Detectors are intentionally simple and reviewable:

- Missing-field checks inspect each record independently.
- Instability checks compare repeated judgments for the same case, candidate, and rubric.
- Position checks compare mean scores for the same candidate across pairwise presentation positions.

Global thresholds can be overridden per rubric. Suppression does not alter issue fingerprints; it
only removes reviewed findings from active counts and failure decisions.

The scanner avoids stochastic behavior and does not call external models. Future adapters should
normalize external exports into the same `JudgeRecord` model before scanning.

## Metrics Design

Metrics are deterministic summaries over the supplied rows, not estimates of broad model or judge
quality. Agreement rows require at least two records for the same case, candidate, and rubric.
Verdict agreement uses normalized pass/fail buckets and reports the majority share when verdicts
are available. Position-effect rows require both first and second presentation positions for the
same case, pair, candidate, and rubric. Threshold sensitivity is bootstrap-free: it reports the
number of observed groups that would be flagged at fixed score-delta and position-delta settings
plus the active policy thresholds.

Confidence intervals in metrics output use a fixed 95% Wilson-score interval for observed
proportions, including majority verdict agreement and threshold-sensitivity flagged-group rates.
They are deterministic, require no resampling, and apply only to the supplied records.

## Input Adapters

Native JSONL rows are parsed directly into the record model. Generic CSV inputs go through an
explicit field-mapping adapter so spreadsheet columns such as `item`, `answer`, or `judge_score`
can be normalized without changing scanner behavior. Required CSV mappings cover case, candidate,
run, rubric, and score identifiers; optional mappings preserve verdicts, pairwise position details,
rationales, and semicolon-separated evidence handles.

Pairwise CSV inputs use a named preset for comparison exports. Each physical row must describe the
case, pair, run, rubric, presented left/right candidate IDs, and left/right scores. The loader
expands that row into two `JudgeRecord` values, assigns `left` and `right` positions, and converts
winner-side labels into `win` and `lose` verdicts when available. Column overrides reuse the same
`field=column` CLI shape as generic CSV mappings.

Rubric CSV inputs use a named preset for single-answer rubric exports. Each physical row must
describe the case, candidate, and run. Score columns are discovered from headers ending in
`_score`, or supplied explicitly as `rubric:column` pairs. The loader expands each score column
into one `JudgeRecord` and copies optional verdict, position, pair, rationale, and evidence fields
onto each normalized record.

Adapter validation reports file row, mapped column, and expected type. It avoids echoing full rows
or long rationale text in error messages.
