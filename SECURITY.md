# Security Policy

## Supported Versions

The `main` branch receives security fixes until versioned releases are established.

## Reporting a Vulnerability

Please use GitHub private vulnerability reporting when available, or open a minimal issue that does
not include sensitive evaluation data.

## Data Handling

RubricTrace runs locally and does not make network requests. Judgment records can contain private
model outputs, evaluation items, rubrics, and judge rationales. Treat input files and reports as
sensitive when your evaluation data is sensitive.

Current safeguards:

- Input files are capped at 10 MiB.
- Text reports include identifiers and compact structured evidence, not full rationale text.
- Malformed-input errors identify the path and line number without echoing full records.
- The scanner does not execute record content, rationale text, metadata, or evidence handles.

Do not commit private evaluation exports or reports unless they are intentionally sanitized.
