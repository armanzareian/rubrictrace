# Architecture

RubricTrace is a dependency-light Python package with a CLI and a small typed API.

## Components

- `rubrictrace.io` loads JSONL judgment records and JSON policies with bounded file-size checks.
- `rubrictrace.models` defines records, policy, issues, reports, and severity ordering.
- `rubrictrace.scanner` runs deterministic detectors over normalized records.
- `rubrictrace.report` renders text and JSON reports.
- `rubrictrace.evaluation` compares scanner output against labeled fixture suites.
- `rubrictrace.cli` wires the commands, output formats, and exit codes.

## Data Flow

1. The loader parses JSONL rows into `JudgeRecord` values.
2. A `Policy` is created from defaults, an optional policy file, and CLI overrides.
3. The scanner groups records by stable case, candidate, rubric, and pairwise identifiers.
4. Detectors emit `Issue` values with stable fingerprints.
5. The report renderer emits text or JSON.
6. The CLI exits with `1` only when a finding meets or exceeds the configured severity threshold.

## Detector Design

Detectors are intentionally simple and reviewable:

- Missing-field checks inspect each record independently.
- Instability checks compare repeated judgments for the same case, candidate, and rubric.
- Position checks compare mean scores for the same candidate across pairwise presentation positions.

The scanner avoids stochastic behavior and does not call external models. Future adapters should
normalize external exports into the same `JudgeRecord` model before scanning.
