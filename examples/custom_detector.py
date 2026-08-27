from __future__ import annotations

from pathlib import Path

from rubrictrace import (
    CustomDetector,
    DetectorContext,
    Issue,
    Policy,
    audit_records,
    load_records,
)

ROOT = Path(__file__).resolve().parents[1]


def low_evidence_count(context: DetectorContext) -> tuple[Issue, ...]:
    issues: list[Issue] = []
    for record in context.records:
        if len(record.evidence) < 2:
            issues.append(
                context.issue(
                    detector="low_evidence_count",
                    severity="low",
                    record=record,
                    message="judgment cites fewer than two evidence handles",
                    evidence={
                        "run_id": record.run_id,
                        "evidence_count": len(record.evidence),
                    },
                )
            )
    return tuple(issues)


def main() -> int:
    records = load_records(ROOT / "examples/judgments/records.jsonl")
    custom_detectors: tuple[CustomDetector, ...] = (low_evidence_count,)
    report = audit_records(
        records,
        Policy(fail_on="critical"),
        custom_detectors=custom_detectors,
    )
    custom_issue_count = sum(
        1 for issue in report.issues if issue.detector == "low_evidence_count"
    )
    print(f"records={report.records_scanned}")
    print(f"active_issues={report.issue_count}")
    print(f"low_evidence_count={custom_issue_count}")
    print(f"schema_version={report.to_dict()['schema_version']}")
    return 1 if report.failed() else 0


if __name__ == "__main__":
    raise SystemExit(main())
