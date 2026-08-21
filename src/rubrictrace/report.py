from __future__ import annotations

from html import escape
import json

from .models import AuditReport, Issue

MAX_CI_ISSUES = 10


def render_report(report: AuditReport, *, output_format: str = "text") -> str:
    if output_format == "json":
        return json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    if output_format == "ci":
        return render_ci_report(report)
    if output_format == "markdown":
        return render_markdown_report(report)
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")
    return render_text_report(report)


def render_text_report(report: AuditReport) -> str:
    lines = [
        "RubricTrace audit",
        f"records: {report.records_scanned}",
        f"issues: {report.issue_count}",
        f"suppressed: {report.suppressed_issue_count}",
        f"fail_on: {report.policy.fail_on}",
    ]
    counts = report.counts_by_severity()
    lines.append(
        "severity_counts: "
        + ", ".join(f"{severity}={counts[severity]}" for severity in counts)
    )

    if not report.issues:
        if report.suppressed_issue_count:
            lines.append("No unsuppressed issues found.")
        else:
            lines.append("No issues found.")
        return "\n".join(lines) + "\n"

    lines.append("")
    for issue in report.issues:
        lines.append(_issue_line(issue))
    return "\n".join(lines) + "\n"


def render_ci_report(report: AuditReport) -> str:
    counts = report.counts_by_severity()
    status = "fail" if report.failed() else "pass"
    lines = [
        (
            "RubricTrace: "
            f"{status}; records={report.records_scanned}; issues={report.issue_count}; "
            f"suppressed={report.suppressed_issue_count}; fail_on={report.policy.fail_on}"
        ),
        "severity_counts: "
        + ", ".join(f"{severity}={counts[severity]}" for severity in counts),
    ]

    if not report.issues:
        lines.append("No unsuppressed issues found.")
        return "\n".join(lines) + "\n"

    shown = report.issues[:MAX_CI_ISSUES]
    for issue in shown:
        lines.append(
            f"- {issue.severity} {issue.detector} {_issue_subject(issue)} "
            f"fingerprint={issue.fingerprint}"
        )
    omitted = len(report.issues) - len(shown)
    if omitted > 0:
        lines.append(f"... {omitted} more issue(s) omitted")
    return "\n".join(lines) + "\n"


def render_markdown_report(report: AuditReport) -> str:
    counts = report.counts_by_severity()
    status = "fail" if report.failed() else "pass"
    lines = [
        "# RubricTrace Audit",
        "",
        "| Status | Records | Active issues | Suppressed | Fail on |",
        "| --- | ---: | ---: | ---: | --- |",
        (
            f"| {_markdown_cell(status)} | {report.records_scanned} | "
            f"{report.issue_count} | {report.suppressed_issue_count} | "
            f"{_markdown_cell(report.policy.fail_on)} |"
        ),
        "",
        "## Severity Counts",
        "",
        "| Low | Medium | High | Critical |",
        "| ---: | ---: | ---: | ---: |",
        (
            f"| {counts['low']} | {counts['medium']} | "
            f"{counts['high']} | {counts['critical']} |"
        ),
    ]

    if not report.issues:
        lines.extend(
            [
                "",
                "No unsuppressed issues found.",
            ]
        )
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "",
            "## Findings",
            "",
            "| Severity | Detector | Subject | Message | Fingerprint | Evidence |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    shown = report.issues[:MAX_CI_ISSUES]
    for issue in shown:
        lines.append(
            "| "
            f"{_markdown_cell(issue.severity)} | "
            f"{_markdown_cell(issue.detector)} | "
            f"{_markdown_cell(_issue_subject(issue))} | "
            f"{_markdown_cell(issue.message)} | "
            f"{_markdown_cell(issue.fingerprint)} | "
            f"{_markdown_cell(_evidence_summary(issue))} |"
        )

    omitted = len(report.issues) - len(shown)
    if omitted > 0:
        lines.extend(["", f"{omitted} additional issue(s) omitted from this summary."])
    return "\n".join(lines) + "\n"


def _issue_line(issue: Issue) -> str:
    evidence = _evidence_summary(issue)
    if evidence:
        evidence = f" evidence: {evidence}"
    return (
        f"- [{issue.severity}] {issue.detector} {_issue_subject(issue)} "
        f"fingerprint={issue.fingerprint}: {issue.message}{evidence}"
    )


def _issue_subject(issue: Issue) -> str:
    subject = f"case={issue.case_id} candidate={issue.candidate_id}"
    if issue.pair_id:
        subject += f" pair={issue.pair_id}"
    return f"{subject} rubric={issue.rubric}"


def _evidence_summary(issue: Issue) -> str:
    return ", ".join(f"{key}={value}" for key, value in issue.evidence.items())


def _markdown_cell(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = escape(text, quote=False)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")
