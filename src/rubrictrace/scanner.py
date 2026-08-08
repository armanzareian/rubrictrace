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
    return AuditReport(
        records_scanned=len(record_tuple),
        issues=tuple(sorted_issues),
        policy=resolved_policy,
    )


def _single_record_issues(record: JudgeRecord, policy: Policy) -> list[Issue]:
    issues: list[Issue] = []
    if policy.require_rationale and not _has_rationale(record):
        issues.append(
            _issue(
                detector="missing_rationale",
                severity="medium",
                record=record,
                message="judgment record is missing a reviewable rationale",
                evidence={"run_id": record.run_id},
            )
        )
    if policy.require_evidence and not record.evidence:
        issues.append(
            _issue(
                detector="missing_evidence",
                severity="medium",
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

    if score_range >= policy.score_delta:
        issues.append(
            _issue(
                detector="score_instability",
                severity="high",
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
    if verdicts == ["fail", "pass"]:
        issues.append(
            _issue(
                detector="verdict_conflict",
                severity="high",
                record=first,
                message="repeated judgments disagree between passing and failing verdicts",
                evidence={"verdicts": verdicts, "run_ids": run_ids},
            )
        )

    if low_score < policy.decision_threshold <= high_score:
        issues.append(
            _issue(
                detector="threshold_flip",
                severity="high",
                record=first,
                message="repeated scores straddle the configured decision threshold",
                evidence={
                    "threshold": policy.decision_threshold,
                    "min_score": low_score,
                    "max_score": high_score,
                    "run_ids": run_ids,
                },
            )
        )

    return issues


def _position_issue(records: list[JudgeRecord], policy: Policy) -> Issue | None:
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
    if delta < policy.position_delta:
        return None

    first = records[0]
    return _issue(
        detector="position_bias",
        severity="medium",
        record=first,
        message="candidate score differs across pairwise presentation positions",
        evidence={
            "first_mean": round(first_mean, 6),
            "second_mean": round(second_mean, 6),
            "delta": round(delta, 6),
            "run_ids": sorted(record.run_id for record in records),
        },
    )


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
