from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .evaluation import evaluate_suite, evaluation_failed, render_evaluation
from .io import InputError, load_policy, load_records, load_suite
from .models import ModelError
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
    audit.add_argument("--records", required=True, type=Path, help="JSONL judgment records")
    audit.add_argument("--policy", type=Path, help="optional JSON policy")
    audit.add_argument("--format", choices=("text", "json"), default="text")
    audit.add_argument("--fail-on", choices=("low", "medium", "high", "critical"))
    audit.add_argument("--score-delta", type=float)
    audit.add_argument("--position-delta", type=float)
    audit.add_argument("--decision-threshold", type=float)
    audit.add_argument("--allow-missing-evidence", action="store_true")
    audit.add_argument("--allow-missing-rationale", action="store_true")

    eval_parser = subparsers.add_parser("eval", help="evaluate detectors against a suite")
    eval_parser.add_argument("--suite", required=True, type=Path, help="JSON evaluation suite")
    eval_parser.add_argument("--format", choices=("text", "json"), default="text")

    return parser


def _run_audit(args: argparse.Namespace) -> int:
    records = load_records(args.records)
    policy = load_policy(args.policy).with_overrides(
        fail_on=args.fail_on,
        score_delta=args.score_delta,
        position_delta=args.position_delta,
        decision_threshold=args.decision_threshold,
        require_evidence=False if args.allow_missing_evidence else None,
        require_rationale=False if args.allow_missing_rationale else None,
    )
    report = audit_records(records, policy)
    print(render_report(report, output_format=args.format), end="")
    return 1 if report.failed() else 0


def _run_eval(args: argparse.Namespace) -> int:
    suite = load_suite(args.suite)
    result = evaluate_suite(suite)
    print(render_evaluation(result, output_format=args.format), end="")
    return 1 if evaluation_failed(result) else 0
