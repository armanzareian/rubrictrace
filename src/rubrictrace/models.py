from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")
SEVERITY_RANK: dict[str, int] = {severity: index for index, severity in enumerate(SEVERITIES)}

DETECTORS: tuple[str, ...] = (
    "missing_rationale",
    "missing_evidence",
    "score_instability",
    "verdict_conflict",
    "threshold_flip",
    "position_bias",
)

PASSING_VERDICTS = {"pass", "passed", "accept", "accepted", "yes", "win", "winner"}
FAILING_VERDICTS = {"fail", "failed", "reject", "rejected", "no", "lose", "loser"}

FIRST_POSITIONS = {"first", "left", "a", "1"}
SECOND_POSITIONS = {"second", "right", "b", "2"}
FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{16}$")


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
class RubricThresholds:
    score_delta: float | None = None
    position_delta: float | None = None
    decision_threshold: float | None = None

    def to_dict(self) -> dict[str, float]:
        result: dict[str, float] = {}
        if self.score_delta is not None:
            result["score_delta"] = self.score_delta
        if self.position_delta is not None:
            result["position_delta"] = self.position_delta
        if self.decision_threshold is not None:
            result["decision_threshold"] = self.decision_threshold
        return result


@dataclass(frozen=True)
class Policy:
    fail_on: str = "high"
    score_delta: float = 1.5
    position_delta: float = 1.0
    decision_threshold: float = 3.0
    require_evidence: bool = True
    require_rationale: bool = True
    enabled_detectors: tuple[str, ...] = DETECTORS
    severity_overrides: Mapping[str, str] = field(default_factory=dict)
    rubric_thresholds: Mapping[str, RubricThresholds] = field(default_factory=dict)
    suppressions: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "Policy":
        allowed = {
            "fail_on",
            "score_delta",
            "position_delta",
            "decision_threshold",
            "require_evidence",
            "require_rationale",
            "enabled_detectors",
            "severity_overrides",
            "rubric_thresholds",
            "suppressions",
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
            enabled_detectors=_policy_detector_list(data, "enabled_detectors", DETECTORS),
            severity_overrides=_policy_severity_overrides(data),
            rubric_thresholds=_policy_rubric_thresholds(data),
            suppressions=_policy_suppressions(data, "suppressions"),
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
        disabled_detectors: Iterable[str] | None = None,
        severity_overrides: Mapping[str, str] | None = None,
        suppressions: Iterable[str] | None = None,
    ) -> "Policy":
        resolved_fail_on = self.fail_on if fail_on is None else fail_on.lower()
        if resolved_fail_on not in SEVERITY_RANK:
            raise ModelError("fail_on must be low, medium, high, or critical")

        resolved_enabled_detectors = self.enabled_detectors
        if disabled_detectors is not None:
            disabled = set(_validated_detector_tuple(disabled_detectors, "disabled_detectors"))
            resolved_enabled_detectors = tuple(
                detector for detector in resolved_enabled_detectors if detector not in disabled
            )

        resolved_severity_overrides = dict(self.severity_overrides)
        if severity_overrides:
            for detector, severity in severity_overrides.items():
                validated_detector = _validate_detector(detector, "severity_overrides")
                resolved_severity_overrides[validated_detector] = _validate_severity(
                    severity,
                    f"severity_overrides.{validated_detector}",
                )

        resolved_suppressions = self.suppressions
        if suppressions is not None:
            resolved_suppressions = _dedupe(
                (*resolved_suppressions, *_validated_suppressions(suppressions, "suppressions"))
            )

        return Policy(
            fail_on=resolved_fail_on,
            score_delta=_override_number(self.score_delta, score_delta, "score_delta"),
            position_delta=_override_number(self.position_delta, position_delta, "position_delta"),
            decision_threshold=(
                _override_number(
                    self.decision_threshold,
                    decision_threshold,
                    "decision_threshold",
                )
            ),
            require_evidence=(
                self.require_evidence if require_evidence is None else require_evidence
            ),
            require_rationale=(
                self.require_rationale if require_rationale is None else require_rationale
            ),
            enabled_detectors=resolved_enabled_detectors,
            severity_overrides=resolved_severity_overrides,
            rubric_thresholds=dict(self.rubric_thresholds),
            suppressions=resolved_suppressions,
        )

    def detector_enabled(self, detector: str) -> bool:
        return detector in self.enabled_detectors

    def severity_for(self, detector: str, default: str) -> str:
        return self.severity_overrides.get(detector, default)

    def score_delta_for(self, rubric: str) -> float:
        threshold = self.rubric_thresholds.get(rubric)
        if threshold is not None and threshold.score_delta is not None:
            return threshold.score_delta
        return self.score_delta

    def position_delta_for(self, rubric: str) -> float:
        threshold = self.rubric_thresholds.get(rubric)
        if threshold is not None and threshold.position_delta is not None:
            return threshold.position_delta
        return self.position_delta

    def decision_threshold_for(self, rubric: str) -> float:
        threshold = self.rubric_thresholds.get(rubric)
        if threshold is not None and threshold.decision_threshold is not None:
            return threshold.decision_threshold
        return self.decision_threshold

    def is_suppressed(self, fingerprint: str) -> bool:
        return fingerprint in self.suppressions

    def to_dict(self) -> dict[str, Any]:
        return {
            "fail_on": self.fail_on,
            "score_delta": self.score_delta,
            "position_delta": self.position_delta,
            "decision_threshold": self.decision_threshold,
            "require_evidence": self.require_evidence,
            "require_rationale": self.require_rationale,
            "enabled_detectors": list(self.enabled_detectors),
            "severity_overrides": dict(sorted(self.severity_overrides.items())),
            "rubric_thresholds": {
                rubric: thresholds.to_dict()
                for rubric, thresholds in sorted(self.rubric_thresholds.items())
            },
            "suppressions": list(self.suppressions),
        }


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
    suppressed_issues: tuple[Issue, ...] = ()

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def suppressed_issue_count(self) -> int:
        return len(self.suppressed_issues)

    @property
    def total_issue_count(self) -> int:
        return self.issue_count + self.suppressed_issue_count

    def counts_by_severity(self, *, include_suppressed: bool = False) -> dict[str, int]:
        counts = {severity: 0 for severity in SEVERITIES}
        issues = self.issues
        if include_suppressed:
            issues = (*issues, *self.suppressed_issues)
        for issue in issues:
            counts[issue.severity] += 1
        return counts

    def failed(self) -> bool:
        threshold = SEVERITY_RANK[self.policy.fail_on]
        return any(SEVERITY_RANK[issue.severity] >= threshold for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "records_scanned": self.records_scanned,
            "issue_count": self.issue_count,
            "suppressed_issue_count": self.suppressed_issue_count,
            "total_issue_count": self.total_issue_count,
            "failed": self.failed(),
            "policy": self.policy.to_dict(),
            "counts_by_severity": self.counts_by_severity(),
            "issues": [issue.to_dict() for issue in self.issues],
            "suppressed_issues": [issue.to_dict() for issue in self.suppressed_issues],
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


def _optional_policy_number(data: dict[str, Any], field_name: str, source: str) -> float | None:
    if field_name not in data:
        return None
    value = data[field_name]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ModelError(f"{source} must be a number")
    numeric = float(value)
    if numeric < 0:
        raise ModelError(f"{source} must be non-negative")
    return numeric


def _override_number(current: float, value: float | None, field_name: str) -> float:
    if value is None:
        return current
    if value < 0:
        raise ModelError(f"{field_name} must be non-negative")
    return value


def _policy_bool(data: dict[str, Any], field_name: str, default: bool) -> bool:
    value = data.get(field_name, default)
    if not isinstance(value, bool):
        raise ModelError(f"policy: {field_name} must be true or false")
    return value


def _policy_detector_list(
    data: dict[str, Any],
    field_name: str,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    if field_name not in data:
        return default
    value = data[field_name]
    if not isinstance(value, list):
        raise ModelError(f"policy: {field_name} must be a list of detector names")
    return _validated_detector_tuple(value, f"policy: {field_name}")


def _policy_severity_overrides(data: dict[str, Any]) -> dict[str, str]:
    if "severity_overrides" not in data:
        return {}
    value = data["severity_overrides"]
    if not isinstance(value, dict):
        raise ModelError("policy: severity_overrides must be an object")
    overrides: dict[str, str] = {}
    for raw_detector, raw_severity in value.items():
        detector = _validate_detector(raw_detector, "policy: severity_overrides detector")
        overrides[detector] = _validate_severity(
            raw_severity,
            f"policy: severity_overrides.{detector}",
        )
    return overrides


def _policy_rubric_thresholds(data: dict[str, Any]) -> dict[str, RubricThresholds]:
    if "rubric_thresholds" not in data:
        return {}
    value = data["rubric_thresholds"]
    if not isinstance(value, dict):
        raise ModelError("policy: rubric_thresholds must be an object")

    thresholds: dict[str, RubricThresholds] = {}
    allowed = {"score_delta", "position_delta", "decision_threshold"}
    for raw_rubric, raw_thresholds in value.items():
        if not isinstance(raw_rubric, str) or not raw_rubric.strip():
            raise ModelError("policy: rubric_thresholds keys must be non-empty strings")
        rubric = raw_rubric.strip()
        source = f"policy: rubric_thresholds.{rubric}"
        if not isinstance(raw_thresholds, dict):
            raise ModelError(f"{source} must be an object")
        unknown = sorted(set(raw_thresholds) - allowed)
        if unknown:
            raise ModelError(f"{source}.{unknown[0]} is not supported")
        thresholds[rubric] = RubricThresholds(
            score_delta=_optional_policy_number(
                raw_thresholds,
                "score_delta",
                f"{source}.score_delta",
            ),
            position_delta=_optional_policy_number(
                raw_thresholds,
                "position_delta",
                f"{source}.position_delta",
            ),
            decision_threshold=_optional_policy_number(
                raw_thresholds,
                "decision_threshold",
                f"{source}.decision_threshold",
            ),
        )
    return thresholds


def _policy_suppressions(data: dict[str, Any], field_name: str) -> tuple[str, ...]:
    if field_name not in data:
        return ()
    value = data[field_name]
    if not isinstance(value, list):
        raise ModelError(f"policy: {field_name} must be a list of fingerprints")
    return _validated_suppressions(value, f"policy: {field_name}")


def _validated_detector_tuple(values: Iterable[Any], source: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise ModelError(f"{source} must be a list of detector names")
    detectors: list[str] = []
    for index, value in enumerate(values):
        detectors.append(_validate_detector(value, f"{source}[{index}]"))
    return _dedupe(detectors)


def _validate_detector(value: Any, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelError(f"{source} must be a detector name")
    detector = value.strip().lower()
    if detector not in DETECTORS:
        raise ModelError(f"{source} must be one of {', '.join(DETECTORS)}")
    return detector


def _validate_severity(value: Any, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelError(f"{source} must be a severity")
    severity = value.strip().lower()
    if severity not in SEVERITY_RANK:
        raise ModelError(f"{source} must be low, medium, high, or critical")
    return severity


def _validated_suppressions(values: Iterable[Any], source: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise ModelError(f"{source} must be a list of fingerprints")
    suppressions: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str):
            raise ModelError(f"{source}[{index}] must be a fingerprint")
        fingerprint = value.strip().lower()
        if FINGERPRINT_PATTERN.fullmatch(fingerprint) is None:
            raise ModelError(f"{source}[{index}] must be a 16-character hexadecimal fingerprint")
        suppressions.append(fingerprint)
    return _dedupe(suppressions)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


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
