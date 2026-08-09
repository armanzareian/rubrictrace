# Architecture

RubricTrace is a dependency-light Python package with a CLI and a small typed API.

## Components

- `rubrictrace.io` loads JSONL judgment records and JSON policies with bounded file-size checks.
- `rubrictrace.models` defines records, policy controls, issues, reports, and severity ordering.
- `rubrictrace.scanner` runs deterministic detectors over normalized records.
- `rubrictrace.report` renders text, JSON, and compact CI reports.
- `rubrictrace.evaluation` compares scanner output against labeled fixture suites.
- `rubrictrace.cli` wires the commands, output formats, and exit codes.

## Data Flow

1. The loader parses JSONL rows into `JudgeRecord` values.
2. A `Policy` is created from defaults, an optional policy file, and CLI overrides.
3. The scanner groups records by stable case, candidate, rubric, and pairwise identifiers.
4. Enabled detectors emit `Issue` values with stable fingerprints.
5. Severity overrides are applied before reviewed-fingerprint suppressions partition findings into
   active and suppressed sets.
6. The report renderer emits text, JSON, or compact CI output.
7. The CLI exits with `1` only when an active finding meets or exceeds the configured severity
   threshold.

## Detector Design

Detectors are intentionally simple and reviewable:

- Missing-field checks inspect each record independently.
- Instability checks compare repeated judgments for the same case, candidate, and rubric.
- Position checks compare mean scores for the same candidate across pairwise presentation positions.

Global thresholds can be overridden per rubric. Suppression does not alter issue fingerprints; it
only removes reviewed findings from active counts and failure decisions.

The scanner avoids stochastic behavior and does not call external models. Future adapters should
normalize external exports into the same `JudgeRecord` model before scanning.
