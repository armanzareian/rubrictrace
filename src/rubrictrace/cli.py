from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .ci import (
    CI_TEMPLATE_MODES,
    INPUT_FORMATS,
    CiTemplateOptions,
    render_github_actions_steps,
)
from .evaluation import evaluate_suite, evaluation_failed, render_evaluation
from .io import (
    CSV_FIELDS,
    PAIRWISE_CSV_FIELDS,
    RUBRIC_CSV_FIELDS,
    InputError,
    load_baseline,
    load_csv_records,
    load_pairwise_csv_records,
    load_policy,
    load_records,
    load_rubric_csv_records,
    load_suite,
)
from .metrics import render_metrics, summarize_records
from .models import DETECTORS, JudgeRecord, ModelError
from .report import render_report
from .scanner import audit_records


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"rubrictrace {__version__}")
        return 0
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2

    try:
        if args.command == "audit":
            return _run_audit(args)
        if args.command == "eval":
            return _run_eval(args)
        if args.command == "metrics":
            return _run_metrics(args)
        if args.command == "ci-template":
            return _run_ci_template(args)
    except (InputError, ModelError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rubrictrace",
        description="Offline audits for LLM-as-judge result logs.",
    )
    parser.add_argument("--version", action="store_true", help="print the package version")
    subparsers = parser.add_subparsers(dest="command")

    audit = subparsers.add_parser("audit", help="audit judgment records")
    audit.add_argument("--records", required=True, type=Path, help="judgment records")
    audit.add_argument(
        "--input-format",
        choices=("jsonl", "csv", "pairwise-csv", "rubric-csv"),
        default="jsonl",
        help="records input format",
    )
    audit.add_argument(
        "--map",
        action="append",
        dest="field_mapping",
        help="CSV field mapping override as field=column; repeat for each mapped field",
    )
    audit.add_argument("--policy", type=Path, help="optional JSON policy")
    audit.add_argument(
        "--baseline",
        type=Path,
        help="optional JSON baseline of reviewed finding fingerprints",
    )
    audit.add_argument(
        "--format",
        choices=("text", "json", "ci", "markdown", "sarif"),
        default="text",
    )
    audit.add_argument("--fail-on", choices=("low", "medium", "high", "critical"))
    audit.add_argument("--score-delta", type=float)
    audit.add_argument("--position-delta", type=float)
    audit.add_argument("--decision-threshold", type=float)
    audit.add_argument("--allow-missing-evidence", action="store_true")
    audit.add_argument("--allow-missing-rationale", action="store_true")
    audit.add_argument(
        "--disable-detector",
        action="append",
        choices=DETECTORS,
        help="disable one detector for this run; may be repeated",
    )
    audit.add_argument(
        "--severity-override",
        action="append",
        help="override detector severity as detector=low|medium|high|critical; may be repeated",
    )
    audit.add_argument(
        "--suppress-fingerprint",
        action="append",
        help="suppress a reviewed finding fingerprint; may be repeated",
    )

    eval_parser = subparsers.add_parser("eval", help="evaluate detectors against a suite")
    eval_parser.add_argument("--suite", required=True, type=Path, help="JSON evaluation suite")
    eval_parser.add_argument("--format", choices=("text", "json"), default="text")

    metrics = subparsers.add_parser("metrics", help="summarize agreement and thresholds")
    metrics.add_argument("--records", required=True, type=Path, help="judgment records")
    metrics.add_argument(
        "--input-format",
        choices=("jsonl", "csv", "pairwise-csv", "rubric-csv"),
        default="jsonl",
        help="records input format",
    )
    metrics.add_argument(
        "--map",
        action="append",
        dest="field_mapping",
        help="CSV field mapping override as field=column; repeat for each mapped field",
    )
    metrics.add_argument("--policy", type=Path, help="optional JSON policy")
    metrics.add_argument("--format", choices=("text", "json"), default="text")

    ci_template = subparsers.add_parser(
        "ci-template",
        help="render GitHub Actions audit steps",
    )
    ci_template.add_argument("--records", required=True, type=Path, help="judgment records")
    ci_template.add_argument(
        "--input-format",
        choices=INPUT_FORMATS,
        default="jsonl",
        help="records input format",
    )
    ci_template.add_argument(
        "--map",
        action="append",
        dest="field_mapping",
        help="CSV field mapping override as field=column; repeat for each mapped field",
    )
    ci_template.add_argument("--policy", type=Path, help="optional JSON policy")
    ci_template.add_argument(
        "--baseline",
        type=Path,
        help="optional JSON baseline of reviewed finding fingerprints",
    )
    ci_template.add_argument(
        "--mode",
        choices=CI_TEMPLATE_MODES,
        default="both",
        help="which GitHub Actions steps to render",
    )
    ci_template.add_argument(
        "--advisory-fail-on",
        choices=("low", "medium", "high", "critical"),
        default="low",
        help="severity threshold surfaced by the advisory step",
    )
    ci_template.add_argument(
        "--strict-fail-on",
        choices=("low", "medium", "high", "critical"),
        default="high",
        help="severity threshold enforced by the strict step",
    )
    ci_template.add_argument(
        "--python-command",
        default="python -m rubrictrace",
        help="command prefix used inside rendered steps",
    )

    return parser


def _run_audit(args: argparse.Namespace) -> int:
    records = _load_audit_records(args)
    suppressions = _audit_suppressions(args)
    policy = load_policy(args.policy).with_overrides(
        fail_on=args.fail_on,
        score_delta=args.score_delta,
        position_delta=args.position_delta,
        decision_threshold=args.decision_threshold,
        require_evidence=False if args.allow_missing_evidence else None,
        require_rationale=False if args.allow_missing_rationale else None,
        disabled_detectors=args.disable_detector,
        severity_overrides=_parse_severity_overrides(args.severity_override),
        suppressions=suppressions,
    )
    report = audit_records(records, policy)
    print(
        render_report(
            report,
            output_format=args.format,
            source_uri=_repo_relative_path(args.records),
        ),
        end="",
    )
    return 1 if report.failed() else 0


def _load_audit_records(args: argparse.Namespace) -> tuple[JudgeRecord, ...]:
    if args.input_format == "jsonl":
        if args.field_mapping:
            raise ValueError("--map can only be used with CSV input formats")
        return load_records(args.records)
    if args.input_format == "csv":
        return load_csv_records(
            args.records,
            _parse_field_mapping(args.field_mapping, CSV_FIELDS, "CSV"),
        )
    if args.input_format == "pairwise-csv":
        return load_pairwise_csv_records(
            args.records,
            _parse_field_mapping(args.field_mapping, PAIRWISE_CSV_FIELDS, "pairwise CSV"),
        )
    if args.input_format == "rubric-csv":
        return load_rubric_csv_records(
            args.records,
            _parse_field_mapping(args.field_mapping, RUBRIC_CSV_FIELDS, "rubric CSV"),
        )
    raise ValueError(f"unsupported input format: {args.input_format}")


def _audit_suppressions(args: argparse.Namespace) -> tuple[str, ...] | None:
    values = (*load_baseline(args.baseline), *(args.suppress_fingerprint or ()))
    return values or None


def _run_eval(args: argparse.Namespace) -> int:
    suite = load_suite(args.suite)
    result = evaluate_suite(suite)
    print(render_evaluation(result, output_format=args.format), end="")
    return 1 if evaluation_failed(result) else 0


def _run_metrics(args: argparse.Namespace) -> int:
    records = _load_audit_records(args)
    policy = load_policy(args.policy)
    print(render_metrics(summarize_records(records, policy), output_format=args.format), end="")
    return 0


def _run_ci_template(args: argparse.Namespace) -> int:
    print(
        render_github_actions_steps(
            CiTemplateOptions(
                records=args.records.as_posix(),
                input_format=args.input_format,
                field_mapping=tuple(args.field_mapping or ()),
                policy=args.policy.as_posix() if args.policy else None,
                baseline=args.baseline.as_posix() if args.baseline else None,
                advisory_fail_on=args.advisory_fail_on,
                strict_fail_on=args.strict_fail_on,
                python_command=args.python_command,
            ),
            mode=args.mode,
        ),
        end="",
    )
    return 0


def _parse_severity_overrides(values: Sequence[str] | None) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for value in values or ():
        if "=" not in value:
            raise ValueError("severity override must use detector=severity")
        detector, severity = value.split("=", 1)
        if not detector.strip() or not severity.strip():
            raise ValueError("severity override must use detector=severity")
        overrides[detector.strip()] = severity.strip()
    return overrides


def _parse_field_mapping(
    values: Sequence[str] | None,
    allowed_fields: Sequence[str],
    label: str,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for value in values or ():
        if "=" not in value:
            raise ValueError(f"{label} mapping must use field=column")
        field_name, column = value.split("=", 1)
        normalized_field = field_name.strip()
        if normalized_field not in allowed_fields:
            raise ValueError(f"{label} mapping field must be one of {', '.join(allowed_fields)}")
        if not column.strip():
            raise ValueError(f"{label} mapping column must be non-empty")
        mapping[normalized_field] = column.strip()
    return mapping


def _repo_relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()
