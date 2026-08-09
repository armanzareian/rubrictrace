from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from statistics import mean
from typing import Any, Iterable

from .models import (
    AuditReport,
    Issue,
    JudgeRecord,
    Policy,
    position_bucket,
    verdict_bucket,
)


def audit_records(records: Iterable[JudgeRecord], policy: Policy | None = None) -> AuditReport:
    resolved_policy = Policy() if policy is None else policy
    record_tuple = tuple(records)
    issues: list[Issue] = []

    for record in record_tuple:
        issues.extend(_single_record_issues(record, resolved_policy))

    repeated_groups: dict[tuple[str, str, str], list[JudgeRecord]] = defaultdict(list)
    position_groups: dict[tuple[str, str, str, str], list[JudgeRecord]] = defaultdict(list)

    for record in record_tuple:
        repeated_groups[(record.case_id, record.candidate_id, record.rubric)].append(record)
        if record.pair_id:
            position_groups[
                (record.case_id, record.pair_id, record.candidate_id, record.rubric)
            ].append(record)

    for group_records in repeated_groups.values():
        issues.extend(_instability_issues(group_records, resolved_policy))

    for group_records in position_groups.values():
        issue = _position_issue(group_records, resolved_policy)
        if issue is not None:
            issues.append(issue)

    sorted_issues = sorted(
        issues,
        key=lambda issue: (
            issue.case_id,
            issue.candidate_id or "",
            issue.pair_id or "",
            issue.rubric,
            issue.detector,
            issue.fingerprint,
        ),
    )
    active_issues, suppressed_issues = _partition_suppressed(sorted_issues, resolved_policy)
    return AuditReport(
        records_scanned=len(record_tuple),
        issues=tuple(active_issues),
        policy=resolved_policy,
        suppressed_issues=tuple(suppressed_issues),
    )


def _single_record_issues(record: JudgeRecord, policy: Policy) -> list[Issue]:
    issues: list[Issue] = []
    if (
        policy.detector_enabled("missing_rationale")
        and policy.require_rationale
        and not _has_rationale(record)
    ):
        issues.append(
            _issue(
                detector="missing_rationale",
                severity=policy.severity_for("missing_rationale", "medium"),
                record=record,
                message="judgment record is missing a reviewable rationale",
                evidence={"run_id": record.run_id},
            )
        )
    if (
        policy.detector_enabled("missing_evidence")
        and policy.require_evidence
        and not record.evidence
    ):
        issues.append(
            _issue(
                detector="missing_evidence",
                severity=policy.severity_for("missing_evidence", "medium"),
                record=record,
                message="judgment record is missing evidence handles",
                evidence={"run_id": record.run_id},
            )
        )
    return issues


def _instability_issues(records: list[JudgeRecord], policy: Policy) -> list[Issue]:
    if len(records) < 2:
        return []

    first = records[0]
    scores = [record.score for record in records]
    low_score = min(scores)
    high_score = max(scores)
    score_range = high_score - low_score
    run_ids = sorted(record.run_id for record in records)
    issues: list[Issue] = []

    if (
        policy.detector_enabled("score_instability")
        and score_range >= policy.score_delta_for(first.rubric)
    ):
        issues.append(
            _issue(
                detector="score_instability",
                severity=policy.severity_for("score_instability", "high"),
                record=first,
                message="repeated judgments have a large score range",
                evidence={
                    "min_score": low_score,
                    "max_score": high_score,
                    "score_range": round(score_range, 6),
                    "run_ids": run_ids,
                },
            )
        )

    verdicts = sorted(
        bucket for bucket in {verdict_bucket(record.verdict) for record in records} if bucket
    )
    if policy.detector_enabled("verdict_conflict") and verdicts == ["fail", "pass"]:
        issues.append(
            _issue(
                detector="verdict_conflict",
                severity=policy.severity_for("verdict_conflict", "high"),
                record=first,
                message="repeated judgments disagree between passing and failing verdicts",
                evidence={"verdicts": verdicts, "run_ids": run_ids},
            )
        )

    decision_threshold = policy.decision_threshold_for(first.rubric)
    if (
        policy.detector_enabled("threshold_flip")
        and low_score < decision_threshold <= high_score
    ):
        issues.append(
            _issue(
                detector="threshold_flip",
                severity=policy.severity_for("threshold_flip", "high"),
                record=first,
                message="repeated scores straddle the configured decision threshold",
                evidence={
                    "threshold": decision_threshold,
                    "min_score": low_score,
                    "max_score": high_score,
                    "run_ids": run_ids,
                },
            )
        )

    return issues


def _position_issue(records: list[JudgeRecord], policy: Policy) -> Issue | None:
    if not policy.detector_enabled("position_bias"):
        return None

    by_position: dict[str, list[float]] = defaultdict(list)
    for record in records:
        bucket = position_bucket(record.position)
        if bucket is not None:
            by_position[bucket].append(record.score)

    if set(by_position) != {"first", "second"}:
        return None

    first_mean = mean(by_position["first"])
    second_mean = mean(by_position["second"])
    delta = abs(first_mean - second_mean)
    first = records[0]
    if delta < policy.position_delta_for(first.rubric):
        return None

    return _issue(
        detector="position_bias",
        severity=policy.severity_for("position_bias", "medium"),
        record=first,
        message="candidate score differs across pairwise presentation positions",
        evidence={
            "first_mean": round(first_mean, 6),
            "second_mean": round(second_mean, 6),
            "delta": round(delta, 6),
            "run_ids": sorted(record.run_id for record in records),
        },
    )


def _partition_suppressed(
    issues: list[Issue],
    policy: Policy,
) -> tuple[list[Issue], list[Issue]]:
    active_issues: list[Issue] = []
    suppressed_issues: list[Issue] = []
    for issue in issues:
        if policy.is_suppressed(issue.fingerprint):
            suppressed_issues.append(issue)
        else:
            active_issues.append(issue)
    return active_issues, suppressed_issues


def _has_rationale(record: JudgeRecord) -> bool:
    if record.rationale is None:
        return False
    return len(record.rationale.strip()) >= 12


def _issue(
    *,
    detector: str,
    severity: str,
    record: JudgeRecord,
    message: str,
    evidence: dict[str, Any],
) -> Issue:
    pair_id = record.pair_id if detector == "position_bias" else None
    fingerprint = _fingerprint(
        {
            "detector": detector,
            "case_id": record.case_id,
            "candidate_id": record.candidate_id,
            "pair_id": pair_id,
            "rubric": record.rubric,
            "evidence": evidence,
        }
    )
    return Issue(
        detector=detector,
        severity=severity,
        case_id=record.case_id,
        candidate_id=record.candidate_id,
        pair_id=pair_id,
        rubric=record.rubric,
        message=message,
        evidence=evidence,
        fingerprint=fingerprint,
    )


def _fingerprint(parts: dict[str, Any]) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
