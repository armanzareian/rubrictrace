from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from .io import InputError
from .models import Issue, JudgeRecord, ModelError, Policy
from .scanner import audit_records

IssueKey = tuple[str, str, str, str, str]


def evaluate_suite(suite: dict[str, Any]) -> dict[str, Any]:
    policy = _suite_policy(suite)
    records = _suite_records(suite)
    expected = _suite_expected(suite)
    report = audit_records(records, policy)

    actual = {_issue_key(issue) for issue in report.issues}
    true_positive = actual & expected
    false_positive = actual - expected
    false_negative = expected - actual
    detector_metrics = _detector_metrics(actual, expected)

    return {
        "name": suite.get("name", "unnamed-suite"),
        "records_scanned": report.records_scanned,
        "expected_issue_count": len(expected),
        "actual_issue_count": len(actual),
        "true_positive": len(true_positive),
        "false_positive": len(false_positive),
        "false_negative": len(false_negative),
        "precision": _ratio(len(true_positive), len(actual)),
        "recall": _ratio(len(true_positive), len(expected)),
        "f1": _f1(len(true_positive), len(actual), len(expected)),
        "detectors": detector_metrics,
        "false_positive_keys": [_key_to_dict(key) for key in sorted(false_positive)],
        "false_negative_keys": [_key_to_dict(key) for key in sorted(false_negative)],
    }


def render_evaluation(result: dict[str, Any], *, output_format: str = "text") -> str:
    if output_format == "json":
        return json.dumps(result, indent=2, sort_keys=True) + "\n"
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")

    lines = [
        f"RubricTrace evaluation: {result['name']}",
        f"records: {result['records_scanned']}",
        f"expected_issues: {result['expected_issue_count']}",
        f"actual_issues: {result['actual_issue_count']}",
        (
            "precision: "
            f"{result['precision']:.3f} recall: {result['recall']:.3f} "
            f"f1: {result['f1']:.3f}"
        ),
    ]
    if result["false_positive_keys"] or result["false_negative_keys"]:
        lines.append("mismatches:")
        for key in result["false_positive_keys"]:
            lines.append(f"- false_positive {key}")
        for key in result["false_negative_keys"]:
            lines.append(f"- false_negative {key}")
    else:
        lines.append("mismatches: none")
    if result["detectors"]:
        lines.append("detectors:")
        for detector, metrics in result["detectors"].items():
            lines.append(
                "- "
                f"{detector}: precision={metrics['precision']:.3f} "
                f"recall={metrics['recall']:.3f} f1={metrics['f1']:.3f} "
                f"false_positive={metrics['false_positive']} "
                f"false_negative={metrics['false_negative']}"
            )
    return "\n".join(lines) + "\n"


def evaluation_failed(result: dict[str, Any]) -> bool:
    return bool(result["false_positive"] or result["false_negative"])


def _suite_policy(suite: dict[str, Any]) -> Policy:
    raw_policy = suite.get("policy", {})
    if not isinstance(raw_policy, dict):
        raise InputError("suite: policy must be an object when present")
    try:
        return Policy.from_mapping(raw_policy)
    except ModelError as exc:
        raise InputError(str(exc)) from exc


def _suite_records(suite: dict[str, Any]) -> tuple[JudgeRecord, ...]:
    raw_records = suite.get("records")
    if not isinstance(raw_records, list):
        raise InputError("suite: records must be a list")
    records: list[JudgeRecord] = []
    for index, row in enumerate(raw_records):
        if not isinstance(row, dict):
            raise InputError(f"suite: records[{index}] must be an object")
        try:
            records.append(JudgeRecord.from_mapping(row, source=f"suite records[{index}]"))
        except ModelError as exc:
            raise InputError(str(exc)) from exc
    if not records:
        raise InputError("suite: records must not be empty")
    return tuple(records)


def _suite_expected(suite: dict[str, Any]) -> set[IssueKey]:
    raw_expected = suite.get("expected_issues")
    if not isinstance(raw_expected, list):
        raise InputError("suite: expected_issues must be a list")
    expected: set[IssueKey] = set()
    for index, row in enumerate(raw_expected):
        if not isinstance(row, dict):
            raise InputError(f"suite: expected_issues[{index}] must be an object")
        detector = _expected_string(row, "detector", index)
        case_id = _expected_string(row, "case_id", index)
        candidate_id = _expected_string(row, "candidate_id", index)
        pair_id = _expected_optional_string(row, "pair_id", index)
        rubric = _expected_string(row, "rubric", index)
        expected.add((detector, case_id, candidate_id, pair_id or "", rubric))
    return expected


def _issue_key(issue: Issue) -> IssueKey:
    return (
        issue.detector,
        issue.case_id,
        issue.candidate_id or "",
        issue.pair_id or "",
        issue.rubric,
    )


def _detector_metrics(actual: set[IssueKey], expected: set[IssueKey]) -> dict[str, Any]:
    detectors = sorted({key[0] for key in actual | expected})
    result: dict[str, Any] = {}
    for detector in detectors:
        actual_for_detector = {key for key in actual if key[0] == detector}
        expected_for_detector = {key for key in expected if key[0] == detector}
        true_positive = len(actual_for_detector & expected_for_detector)
        result[detector] = {
            "expected": len(expected_for_detector),
            "actual": len(actual_for_detector),
            "true_positive": true_positive,
            "false_positive": len(actual_for_detector - expected_for_detector),
            "false_negative": len(expected_for_detector - actual_for_detector),
            "precision": _ratio(true_positive, len(actual_for_detector)),
            "recall": _ratio(true_positive, len(expected_for_detector)),
            "f1": _f1(true_positive, len(actual_for_detector), len(expected_for_detector)),
        }
    return result


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


def _f1(true_positive: int, actual_count: int, expected_count: int) -> float:
    precision = _ratio(true_positive, actual_count)
    recall = _ratio(true_positive, expected_count)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _key_to_dict(key: IssueKey) -> dict[str, str]:
    detector, case_id, candidate_id, pair_id, rubric = key
    return {
        "detector": detector,
        "case_id": case_id,
        "candidate_id": candidate_id,
        "pair_id": pair_id,
        "rubric": rubric,
    }


def _expected_string(row: dict[str, Any], field_name: str, index: int) -> str:
    value = row.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"suite: expected_issues[{index}].{field_name} must be a string")
    return value.strip()


def _expected_optional_string(row: dict[str, Any], field_name: str, index: int) -> str | None:
    value = row.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InputError(f"suite: expected_issues[{index}].{field_name} must be a string")
    return value.strip() or None
