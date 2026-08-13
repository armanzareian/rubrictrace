from __future__ import annotations

import json
from collections import Counter, defaultdict
from statistics import mean
from typing import Any, Iterable

from .models import JudgeRecord, Policy, position_bucket, verdict_bucket

THRESHOLD_SENSITIVITY_STEPS: tuple[float, ...] = (0.5, 1.0, 1.5, 2.0, 2.5)


def summarize_records(
    records: Iterable[JudgeRecord],
    policy: Policy | None = None,
) -> dict[str, Any]:
    resolved_policy = Policy() if policy is None else policy
    record_tuple = tuple(records)
    repeated_groups = _repeated_groups(record_tuple)
    position_groups = _position_groups(record_tuple)

    return {
        "records_scanned": len(record_tuple),
        "policy_thresholds": {
            "score_delta": resolved_policy.score_delta,
            "position_delta": resolved_policy.position_delta,
            "decision_threshold": resolved_policy.decision_threshold,
        },
        "agreement": _agreement_rows(repeated_groups, resolved_policy),
        "position_effects": _position_effect_rows(position_groups),
        "threshold_sensitivity": {
            "score_instability": _score_sensitivity(repeated_groups, resolved_policy),
            "position_bias": _position_sensitivity(position_groups, resolved_policy),
        },
    }


def render_metrics(summary: dict[str, Any], *, output_format: str = "text") -> str:
    if output_format == "json":
        return json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")

    lines = [
        "RubricTrace metrics",
        f"records: {summary['records_scanned']}",
        (
            "policy_thresholds: "
            f"score_delta={summary['policy_thresholds']['score_delta']}, "
            f"position_delta={summary['policy_thresholds']['position_delta']}, "
            f"decision_threshold={summary['policy_thresholds']['decision_threshold']}"
        ),
        "",
        "agreement:",
    ]

    agreement = summary["agreement"]
    if agreement:
        for row in agreement:
            lines.append(
                "- "
                f"case={row['case_id']} candidate={row['candidate_id']} "
                f"rubric={row['rubric']} runs={row['run_count']} "
                f"score_range={row['score_range']:.6g} "
                f"mean_score={row['mean_score']:.6g} "
                f"verdict_agreement={row['verdict_agreement']} "
                f"threshold_margin={row['threshold_margin']:.6g}"
            )
    else:
        lines.append("- no repeated case/candidate/rubric groups")

    lines.extend(("", "position_effects:"))
    position_effects = summary["position_effects"]
    if position_effects:
        for row in position_effects:
            lines.append(
                "- "
                f"case={row['case_id']} pair={row['pair_id']} "
                f"candidate={row['candidate_id']} rubric={row['rubric']} "
                f"first_mean={row['first_mean']:.6g} "
                f"second_mean={row['second_mean']:.6g} "
                f"delta={row['delta']:.6g}"
            )
    else:
        lines.append("- no comparable pairwise position groups")

    lines.extend(("", "threshold_sensitivity:", "score_instability:"))
    for row in summary["threshold_sensitivity"]["score_instability"]:
        lines.append(
            "- "
            f"score_delta={row['score_delta']:.6g} groups_flagged={row['groups_flagged']}"
        )
    lines.append("position_bias:")
    for row in summary["threshold_sensitivity"]["position_bias"]:
        lines.append(
            "- "
            f"position_delta={row['position_delta']:.6g} groups_flagged={row['groups_flagged']}"
        )

    return "\n".join(lines) + "\n"


def _repeated_groups(
    records: tuple[JudgeRecord, ...],
) -> dict[tuple[str, str, str], list[JudgeRecord]]:
    groups: dict[tuple[str, str, str], list[JudgeRecord]] = defaultdict(list)
    for record in records:
        groups[(record.case_id, record.candidate_id, record.rubric)].append(record)
    return groups


def _position_groups(
    records: tuple[JudgeRecord, ...],
) -> dict[tuple[str, str, str, str], list[JudgeRecord]]:
    groups: dict[tuple[str, str, str, str], list[JudgeRecord]] = defaultdict(list)
    for record in records:
        if record.pair_id:
            groups[(record.case_id, record.pair_id, record.candidate_id, record.rubric)].append(
                record
            )
    return groups


def _agreement_rows(
    groups: dict[tuple[str, str, str], list[JudgeRecord]],
    policy: Policy,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (case_id, candidate_id, rubric), group_records in groups.items():
        if len(group_records) < 2:
            continue

        scores = [record.score for record in group_records]
        verdict_buckets = (verdict_bucket(record.verdict) for record in group_records)
        verdict_counts = Counter(bucket for bucket in verdict_buckets if bucket)
        verdict_total = sum(verdict_counts.values())
        if verdict_total:
            majority_count = max(verdict_counts.values())
            verdict_agreement = round(majority_count / verdict_total, 6)
        else:
            verdict_agreement = None

        rows.append(
            {
                "case_id": case_id,
                "candidate_id": candidate_id,
                "rubric": rubric,
                "run_count": len(group_records),
                "min_score": min(scores),
                "max_score": max(scores),
                "mean_score": round(mean(scores), 6),
                "score_range": round(max(scores) - min(scores), 6),
                "verdict_counts": dict(sorted(verdict_counts.items())),
                "verdict_agreement": verdict_agreement,
                "threshold_margin": round(
                    _threshold_margin(scores, policy.decision_threshold_for(rubric)),
                    6,
                ),
                "run_ids": sorted(record.run_id for record in group_records),
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row["case_id"],
            row["candidate_id"],
            row["rubric"],
        ),
    )


def _position_effect_rows(
    groups: dict[tuple[str, str, str, str], list[JudgeRecord]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (case_id, pair_id, candidate_id, rubric), group_records in groups.items():
        by_position: dict[str, list[float]] = defaultdict(list)
        for record in group_records:
            bucket = position_bucket(record.position)
            if bucket is not None:
                by_position[bucket].append(record.score)
        if set(by_position) != {"first", "second"}:
            continue

        first_mean = round(mean(by_position["first"]), 6)
        second_mean = round(mean(by_position["second"]), 6)
        rows.append(
            {
                "case_id": case_id,
                "pair_id": pair_id,
                "candidate_id": candidate_id,
                "rubric": rubric,
                "first_count": len(by_position["first"]),
                "second_count": len(by_position["second"]),
                "first_mean": first_mean,
                "second_mean": second_mean,
                "delta": round(abs(first_mean - second_mean), 6),
                "run_ids": sorted(record.run_id for record in group_records),
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            row["case_id"],
            row["pair_id"],
            row["candidate_id"],
            row["rubric"],
        ),
    )


def _score_sensitivity(
    groups: dict[tuple[str, str, str], list[JudgeRecord]],
    policy: Policy,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for score_delta in _sensitivity_steps(policy.score_delta, THRESHOLD_SENSITIVITY_STEPS):
        flagged = 0
        for group_records in groups.values():
            if len(group_records) < 2:
                continue
            scores = [record.score for record in group_records]
            if max(scores) - min(scores) >= score_delta:
                flagged += 1
        rows.append({"score_delta": score_delta, "groups_flagged": flagged})
    return rows


def _position_sensitivity(
    groups: dict[tuple[str, str, str, str], list[JudgeRecord]],
    policy: Policy,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    deltas = [_position_delta(group_records) for group_records in groups.values()]
    comparable_deltas = [delta for delta in deltas if delta is not None]

    for position_delta in _sensitivity_steps(policy.position_delta, THRESHOLD_SENSITIVITY_STEPS):
        flagged = sum(delta >= position_delta for delta in comparable_deltas)
        rows.append({"position_delta": position_delta, "groups_flagged": flagged})
    return rows


def _position_delta(records: list[JudgeRecord]) -> float | None:
    by_position: dict[str, list[float]] = defaultdict(list)
    for record in records:
        bucket = position_bucket(record.position)
        if bucket is not None:
            by_position[bucket].append(record.score)
    if set(by_position) != {"first", "second"}:
        return None
    return round(abs(mean(by_position["first"]) - mean(by_position["second"])), 6)


def _threshold_margin(scores: list[float], decision_threshold: float) -> float:
    if min(scores) < decision_threshold <= max(scores):
        return 0.0
    return min(abs(score - decision_threshold) for score in scores)


def _sensitivity_steps(base: float, defaults: tuple[float, ...]) -> list[float]:
    return sorted({round(value, 6) for value in (*defaults, base)})
