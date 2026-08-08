from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")
SEVERITY_RANK: dict[str, int] = {severity: index for index, severity in enumerate(SEVERITIES)}

PASSING_VERDICTS = {"pass", "passed", "accept", "accepted", "yes", "win", "winner"}
FAILING_VERDICTS = {"fail", "failed", "reject", "rejected", "no", "lose", "loser"}

FIRST_POSITIONS = {"first", "left", "a", "1"}
SECOND_POSITIONS = {"second", "right", "b", "2"}


class ModelError(ValueError):
    """Raised when a public model cannot be constructed from input data."""


@dataclass(frozen=True)
class JudgeRecord:
    case_id: str
    candidate_id: str
    run_id: str
    rubric: str
    score: float
    verdict: str | None = None
    position: str | None = None
    pair_id: str | None = None
    rationale: str | None = None
    evidence: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any], *, source: str) -> "JudgeRecord":
        required = ("case_id", "candidate_id", "run_id", "rubric", "score")
        for field_name in required:
            if field_name not in data:
                raise ModelError(f"{source}: missing required field {field_name!r}")

        case_id = _required_string(data["case_id"], "case_id", source)
        candidate_id = _required_string(data["candidate_id"], "candidate_id", source)
        run_id = _required_string(data["run_id"], "run_id", source)
        rubric = _required_string(data["rubric"], "rubric", source)
        score = _required_number(data["score"], "score", source)

        verdict = _optional_string(data.get("verdict"), "verdict", source)
        position = _optional_string(data.get("position"), "position", source)
        pair_id = _optional_string(data.get("pair_id"), "pair_id", source)
        rationale = _optional_string(data.get("rationale"), "rationale", source)
        evidence = _evidence_tuple(data.get("evidence"), source)
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ModelError(f"{source}: metadata must be an object when present")

        return cls(
            case_id=case_id,
            candidate_id=candidate_id,
            run_id=run_id,
            rubric=rubric,
            score=score,
            verdict=_normalize_verdict(verdict),
            position=_normalize_position(position),
            pair_id=pair_id,
            rationale=rationale,
            evidence=evidence,
            metadata=dict(metadata),
        )


@dataclass(frozen=True)
class Policy:
    fail_on: str = "high"
    score_delta: float = 1.5
    position_delta: float = 1.0
    decision_threshold: float = 3.0
    require_evidence: bool = True
    require_rationale: bool = True

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "Policy":
        allowed = {
            "fail_on",
            "score_delta",
            "position_delta",
            "decision_threshold",
            "require_evidence",
            "require_rationale",
        }
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ModelError(f"policy: unknown field {unknown[0]!r}")

        fail_on = str(data.get("fail_on", cls.fail_on)).lower()
        if fail_on not in SEVERITY_RANK:
            raise ModelError("policy: fail_on must be low, medium, high, or critical")

        return cls(
            fail_on=fail_on,
            score_delta=_policy_number(data, "score_delta", cls.score_delta),
            position_delta=_policy_number(data, "position_delta", cls.position_delta),
            decision_threshold=_policy_number(
                data, "decision_threshold", cls.decision_threshold
            ),
            require_evidence=_policy_bool(data, "require_evidence", cls.require_evidence),
            require_rationale=_policy_bool(data, "require_rationale", cls.require_rationale),
        )

    def with_overrides(
        self,
        *,
        fail_on: str | None = None,
        score_delta: float | None = None,
        position_delta: float | None = None,
        decision_threshold: float | None = None,
        require_evidence: bool | None = None,
        require_rationale: bool | None = None,
    ) -> "Policy":
        resolved_fail_on = self.fail_on if fail_on is None else fail_on.lower()
        if resolved_fail_on not in SEVERITY_RANK:
            raise ModelError("fail_on must be low, medium, high, or critical")
        return Policy(
            fail_on=resolved_fail_on,
            score_delta=self.score_delta if score_delta is None else score_delta,
            position_delta=self.position_delta if position_delta is None else position_delta,
            decision_threshold=(
                self.decision_threshold if decision_threshold is None else decision_threshold
            ),
            require_evidence=(
                self.require_evidence if require_evidence is None else require_evidence
            ),
            require_rationale=(
                self.require_rationale if require_rationale is None else require_rationale
            ),
        )


@dataclass(frozen=True)
class Issue:
    detector: str
    severity: str
    case_id: str
    rubric: str
    message: str
    fingerprint: str
    candidate_id: str | None = None
    pair_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "severity": self.severity,
            "case_id": self.case_id,
            "candidate_id": self.candidate_id,
            "pair_id": self.pair_id,
            "rubric": self.rubric,
            "message": self.message,
            "fingerprint": self.fingerprint,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class AuditReport:
    records_scanned: int
    issues: tuple[Issue, ...]
    policy: Policy

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    def counts_by_severity(self) -> dict[str, int]:
        counts = {severity: 0 for severity in SEVERITIES}
        for issue in self.issues:
            counts[issue.severity] += 1
        return counts

    def failed(self) -> bool:
        threshold = SEVERITY_RANK[self.policy.fail_on]
        return any(SEVERITY_RANK[issue.severity] >= threshold for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "records_scanned": self.records_scanned,
            "issue_count": self.issue_count,
            "failed": self.failed(),
            "policy": {
                "fail_on": self.policy.fail_on,
                "score_delta": self.policy.score_delta,
                "position_delta": self.policy.position_delta,
                "decision_threshold": self.policy.decision_threshold,
                "require_evidence": self.policy.require_evidence,
                "require_rationale": self.policy.require_rationale,
            },
            "counts_by_severity": self.counts_by_severity(),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def verdict_bucket(verdict: str | None) -> str | None:
    if verdict is None:
        return None
    if verdict in PASSING_VERDICTS:
        return "pass"
    if verdict in FAILING_VERDICTS:
        return "fail"
    return None


def position_bucket(position: str | None) -> str | None:
    if position is None:
        return None
    if position in FIRST_POSITIONS:
        return "first"
    if position in SECOND_POSITIONS:
        return "second"
    return None


def _required_string(value: Any, field_name: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelError(f"{source}: {field_name} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, field_name: str, source: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ModelError(f"{source}: {field_name} must be a string when present")
    stripped = value.strip()
    return stripped or None


def _required_number(value: Any, field_name: str, source: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ModelError(f"{source}: {field_name} must be a number")
    return float(value)


def _policy_number(data: dict[str, Any], field_name: str, default: float) -> float:
    value = data.get(field_name, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ModelError(f"policy: {field_name} must be a number")
    numeric = float(value)
    if numeric < 0:
        raise ModelError(f"policy: {field_name} must be non-negative")
    return numeric


def _policy_bool(data: dict[str, Any], field_name: str, default: bool) -> bool:
    value = data.get(field_name, default)
    if not isinstance(value, bool):
        raise ModelError(f"policy: {field_name} must be true or false")
    return value


def _evidence_tuple(value: Any, source: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ModelError(f"{source}: evidence must be a list of strings when present")
    evidence: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ModelError(f"{source}: evidence item {index} must be a non-empty string")
        evidence.append(item.strip())
    return tuple(evidence)


def _normalize_verdict(verdict: str | None) -> str | None:
    return None if verdict is None else verdict.strip().lower()


def _normalize_position(position: str | None) -> str | None:
    return None if position is None else position.strip().lower()
