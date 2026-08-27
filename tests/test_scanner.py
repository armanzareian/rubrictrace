from __future__ import annotations

import json
import unittest

from rubrictrace.models import AuditReport, Issue, JudgeRecord, Policy, RubricThresholds
from rubrictrace.metrics import render_metrics, summarize_records
from rubrictrace.report import render_report
from rubrictrace.scanner import DetectorContext, audit_records


class ScannerTests(unittest.TestCase):
    def test_instability_and_threshold_flip(self) -> None:
        records = (
            JudgeRecord(
                case_id="case-1",
                candidate_id="answer-a",
                run_id="run-1",
                rubric="groundedness",
                score=4.5,
                verdict="pass",
                rationale="Grounded in the cited source.",
                evidence=("doc-1",),
            ),
            JudgeRecord(
                case_id="case-1",
                candidate_id="answer-a",
                run_id="run-2",
                rubric="groundedness",
                score=2.5,
                verdict="fail",
                rationale="Misses important support.",
                evidence=("doc-1",),
            ),
        )

        report = audit_records(records, Policy(score_delta=1.5, decision_threshold=3.0))
        detectors = {issue.detector for issue in report.issues}

        self.assertIn("score_instability", detectors)
        self.assertIn("verdict_conflict", detectors)
        self.assertIn("threshold_flip", detectors)
        self.assertTrue(report.failed())

    def test_position_bias_requires_both_positions(self) -> None:
        records = (
            JudgeRecord(
                case_id="case-2",
                candidate_id="answer-b",
                run_id="left-run",
                rubric="preference",
                score=4.0,
                position="first",
                pair_id="pair-1",
                rationale="Better supported answer.",
                evidence=("doc-2",),
            ),
            JudgeRecord(
                case_id="case-2",
                candidate_id="answer-b",
                run_id="right-run",
                rubric="preference",
                score=2.5,
                position="second",
                pair_id="pair-1",
                rationale="Less favored in this order.",
                evidence=("doc-2",),
            ),
        )

        report = audit_records(records, Policy(score_delta=5.0, position_delta=1.0, decision_threshold=1.0))

        self.assertEqual(["position_bias"], [issue.detector for issue in report.issues])
        self.assertFalse(report.failed())

    def test_missing_fields_respect_policy(self) -> None:
        record = JudgeRecord(
            case_id="case-3",
            candidate_id="answer-c",
            run_id="run-1",
            rubric="safety",
            score=5.0,
        )

        strict_report = audit_records((record,), Policy())
        relaxed_report = audit_records(
            (record,),
            Policy(require_evidence=False, require_rationale=False),
        )

        self.assertEqual({"missing_evidence", "missing_rationale"}, {
            issue.detector for issue in strict_report.issues
        })
        self.assertEqual(0, relaxed_report.issue_count)

    def test_custom_detector_can_emit_stable_issue_from_context(self) -> None:
        record = JudgeRecord(
            case_id="case-extension-1",
            candidate_id="answer-custom",
            run_id="judge-run-1",
            rubric="groundedness",
            score=4.0,
            rationale="Grounded answer with citations.",
            evidence=("doc-1",),
            metadata={"source_count": 1},
        )

        def low_source_count(context: DetectorContext) -> tuple[Issue, ...]:
            return (
                context.issue(
                    detector="low_source_count",
                    severity="low",
                    record=context.records[0],
                    message="answer cites fewer than two sources",
                    evidence={"source_count": context.records[0].metadata["source_count"]},
                ),
            )

        try:
            report = audit_records(
                (record,),
                Policy(fail_on="high"),
                custom_detectors=(low_source_count,),
            )
        except TypeError:
            self.fail("audit_records should accept custom_detectors")

        self.assertEqual(1, report.issue_count)
        issue = report.issues[0]
        self.assertEqual("low_source_count", issue.detector)
        self.assertEqual("low", issue.severity)
        self.assertEqual("case-extension-1", issue.case_id)
        self.assertEqual("answer-custom", issue.candidate_id)
        self.assertEqual({"source_count": 1}, issue.evidence)
        self.assertRegex(issue.fingerprint, r"^[0-9a-f]{16}$")
        self.assertFalse(report.failed())

        second = audit_records(
            (record,),
            Policy(fail_on="high"),
            custom_detectors=(low_source_count,),
        )
        self.assertEqual(issue.fingerprint, second.issues[0].fingerprint)

    def test_custom_detector_errors_are_sanitized_and_contained(self) -> None:
        record = JudgeRecord(
            case_id="case-extension-2",
            candidate_id="answer-custom",
            run_id="judge-run-1",
            rubric="safety",
            score=5.0,
            rationale="Safe answer with enough explanation.",
            evidence=("policy-1",),
        )

        def broken_detector(context: DetectorContext) -> tuple[Issue, ...]:
            raise RuntimeError("secret rationale should not be echoed")

        try:
            report = audit_records(
                (record,),
                Policy(fail_on="high"),
                custom_detectors=(broken_detector,),
            )
        except TypeError:
            self.fail("audit_records should accept custom_detectors")

        self.assertEqual(1, report.issue_count)
        issue = report.issues[0]
        self.assertEqual("extension_error", issue.detector)
        self.assertEqual("medium", issue.severity)
        self.assertEqual("__extensions__", issue.case_id)
        self.assertEqual("custom_detector", issue.rubric)
        self.assertEqual(
            {"detector": "broken_detector", "error_type": "RuntimeError"},
            issue.evidence,
        )
        self.assertIn("custom detector failed", issue.message)
        self.assertNotIn("secret rationale", json.dumps(issue.to_dict()))
        self.assertFalse(report.failed())

    def test_custom_detector_errors_can_be_configured_to_raise(self) -> None:
        record = JudgeRecord(
            case_id="case-extension-3",
            candidate_id="answer-custom",
            run_id="judge-run-1",
            rubric="style",
            score=5.0,
            rationale="Clear answer with concise structure.",
            evidence=("style-guide",),
        )

        def broken_detector(context: DetectorContext) -> tuple[Issue, ...]:
            raise RuntimeError("private details")

        try:
            with self.assertRaisesRegex(
                RuntimeError,
                "custom detector 'broken_detector' failed",
            ):
                audit_records(
                    (record,),
                    Policy(),
                    custom_detectors=(broken_detector,),
                    raise_custom_detector_errors=True,
                )
        except TypeError:
            self.fail("audit_records should accept raise_custom_detector_errors")

    def test_fingerprints_are_stable(self) -> None:
        records = (
            JudgeRecord(
                case_id="case-4",
                candidate_id="answer-d",
                run_id="run-1",
                rubric="style",
                score=1.0,
                rationale="Too terse to satisfy the style rubric.",
                evidence=("doc-4",),
            ),
            JudgeRecord(
                case_id="case-4",
                candidate_id="answer-d",
                run_id="run-2",
                rubric="style",
                score=4.0,
                rationale="Clear style with useful structure.",
                evidence=("doc-4",),
            ),
        )

        first = audit_records(records, Policy()).issues
        second = audit_records(tuple(reversed(records)), Policy()).issues

        self.assertEqual(
            [issue.fingerprint for issue in first],
            [issue.fingerprint for issue in second],
        )

    def test_policy_controls_partition_suppressed_issues(self) -> None:
        records = (
            JudgeRecord(
                case_id="case-5",
                candidate_id="answer-e",
                run_id="run-1",
                rubric="groundedness",
                score=4.5,
                verdict="pass",
                rationale="Grounded in the cited source.",
                evidence=("doc-5",),
            ),
            JudgeRecord(
                case_id="case-5",
                candidate_id="answer-e",
                run_id="run-2",
                rubric="groundedness",
                score=2.5,
                verdict="fail",
                rationale="Misses important support.",
                evidence=("doc-5",),
            ),
        )
        baseline = audit_records(records, Policy())
        score_issue = next(
            issue for issue in baseline.issues if issue.detector == "score_instability"
        )

        policy = Policy(
            fail_on="critical",
            enabled_detectors=("score_instability", "threshold_flip"),
            severity_overrides={"score_instability": "critical"},
            rubric_thresholds={
                "groundedness": RubricThresholds(score_delta=1.0, decision_threshold=3.0)
            },
            suppressions=(score_issue.fingerprint,),
        )
        report = audit_records(records, policy)

        self.assertEqual(["threshold_flip"], [issue.detector for issue in report.issues])
        self.assertEqual(1, report.suppressed_issue_count)
        self.assertEqual(score_issue.fingerprint, report.suppressed_issues[0].fingerprint)
        self.assertEqual("critical", report.suppressed_issues[0].severity)
        self.assertFalse(report.failed())

    def test_per_rubric_thresholds_only_affect_matching_rubric(self) -> None:
        records = (
            JudgeRecord(
                case_id="case-6",
                candidate_id="answer-f",
                run_id="run-1",
                rubric="style",
                score=1.0,
                rationale="Too terse for the requested style.",
                evidence=("doc-6",),
            ),
            JudgeRecord(
                case_id="case-6",
                candidate_id="answer-f",
                run_id="run-2",
                rubric="style",
                score=2.2,
                rationale="More complete style and structure.",
                evidence=("doc-6",),
            ),
            JudgeRecord(
                case_id="case-7",
                candidate_id="answer-g",
                run_id="run-1",
                rubric="safety",
                score=1.0,
                rationale="Safe response with sufficient caution.",
                evidence=("doc-7",),
            ),
            JudgeRecord(
                case_id="case-7",
                candidate_id="answer-g",
                run_id="run-2",
                rubric="safety",
                score=2.2,
                rationale="Still safe, but scored slightly higher.",
                evidence=("doc-7",),
            ),
        )

        report = audit_records(
            records,
            Policy(
                score_delta=5.0,
                decision_threshold=5.0,
                rubric_thresholds={"style": RubricThresholds(score_delta=1.0)},
            ),
        )

        self.assertEqual(["style"], [issue.rubric for issue in report.issues])
        self.assertEqual(["score_instability"], [issue.detector for issue in report.issues])

    def test_report_formats_do_not_change_fingerprints(self) -> None:
        records = (
            JudgeRecord(
                case_id="case-8",
                candidate_id="answer-h",
                run_id="run-1",
                rubric="evidence",
                score=4.0,
            ),
        )
        report = audit_records(records, Policy())
        fingerprints = [issue.fingerprint for issue in report.issues]

        text = render_report(report, output_format="text")
        ci = render_report(report, output_format="ci")
        markdown = render_report(report, output_format="markdown")
        sarif = render_report(report, output_format="sarif")
        rendered_json = render_report(report, output_format="json")

        self.assertEqual(fingerprints, [issue.fingerprint for issue in report.issues])
        self.assertIn(fingerprints[0], text)
        self.assertIn(fingerprints[0], ci)
        self.assertIn(fingerprints[0], markdown)
        self.assertIn(fingerprints[0], sarif)
        self.assertIn(fingerprints[0], rendered_json)

    def test_report_json_contract_includes_schema_version_and_issue_shape(self) -> None:
        report = AuditReport(
            records_scanned=1,
            issues=(
                Issue(
                    detector="missing_evidence",
                    severity="medium",
                    case_id="case-contract-1",
                    candidate_id="answer-contract",
                    rubric="safety",
                    message="judgment record is missing evidence handles",
                    fingerprint="0123456789abcdef",
                    evidence={"run_id": "judge-run-1"},
                ),
            ),
            policy=Policy(fail_on="medium"),
        )

        payload = report.to_dict()

        self.assertIn("schema_version", payload)
        self.assertEqual(1, payload["schema_version"])
        self.assertEqual(
            [
                "counts_by_severity",
                "failed",
                "issue_count",
                "issues",
                "policy",
                "records_scanned",
                "schema_version",
                "suppressed_issue_count",
                "suppressed_issues",
                "total_issue_count",
            ],
            sorted(payload),
        )
        self.assertEqual(
            [
                "candidate_id",
                "case_id",
                "detector",
                "evidence",
                "fingerprint",
                "message",
                "pair_id",
                "rubric",
                "severity",
            ],
            sorted(payload["issues"][0]),
        )

    def test_markdown_report_escapes_table_cells(self) -> None:
        report = AuditReport(
            records_scanned=1,
            issues=(
                Issue(
                    detector="missing_evidence",
                    severity="high",
                    case_id="case|9",
                    candidate_id="answer-a",
                    rubric="safety",
                    message="review case|9\nbefore release",
                    fingerprint="0123456789abcdef",
                    evidence={"run_id": "judge|one\nnext-line"},
                ),
            ),
            policy=Policy(fail_on="high"),
        )

        rendered = render_report(report, output_format="markdown")

        self.assertIn("# RubricTrace Audit", rendered)
        self.assertIn("| Status | Records | Active issues | Suppressed | Fail on |", rendered)
        self.assertIn("case=case\\|9", rendered)
        self.assertIn("review case\\|9<br>before release", rendered)
        self.assertIn("judge\\|one<br>next-line", rendered)
        self.assertIn("0123456789abcdef", rendered)

    def test_sarif_report_contains_machine_readable_findings(self) -> None:
        report = AuditReport(
            records_scanned=3,
            issues=(
                Issue(
                    detector="score_instability",
                    severity="high",
                    case_id="case-10",
                    candidate_id="answer-j",
                    rubric="groundedness",
                    message="repeated judgments have a large score range",
                    fingerprint="0123456789abcdef",
                    evidence={"min_score": 1.0, "max_score": 4.0},
                ),
            ),
            suppressed_issues=(
                Issue(
                    detector="missing_evidence",
                    severity="medium",
                    case_id="case-11",
                    candidate_id="answer-k",
                    rubric="safety",
                    message="judgment record is missing evidence handles",
                    fingerprint="abcdef0123456789",
                    evidence={"run_id": "judge-run-1"},
                ),
            ),
            policy=Policy(fail_on="high"),
        )

        payload = json.loads(
            render_report(
                report,
                output_format="sarif",
                source_uri="examples/judgments/records.jsonl",
            )
        )

        self.assertEqual("2.1.0", payload["version"])
        run = payload["runs"][0]
        self.assertEqual("RubricTrace", run["tool"]["driver"]["name"])
        self.assertEqual(1, run["properties"]["activeIssueCount"])
        self.assertEqual(1, run["properties"]["suppressedIssueCount"])
        self.assertEqual(
            ["score_instability"],
            [rule["id"] for rule in run["tool"]["driver"]["rules"]],
        )
        self.assertEqual(1, len(run["results"]))

        result = run["results"][0]
        self.assertEqual("score_instability", result["ruleId"])
        self.assertEqual("error", result["level"])
        self.assertEqual(
            {"rubricTraceFingerprint": "0123456789abcdef"},
            result["partialFingerprints"],
        )
        self.assertEqual("case-10", result["properties"]["caseId"])
        self.assertEqual({"min_score": 1.0, "max_score": 4.0}, result["properties"]["evidence"])
        self.assertEqual(
            "examples/judgments/records.jsonl",
            result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"],
        )
        self.assertIn(
            "case=case-10",
            result["locations"][0]["logicalLocations"][0]["fullyQualifiedName"],
        )

    def test_metrics_summarize_agreement_and_threshold_sensitivity(self) -> None:
        records = (
            JudgeRecord(
                case_id="case-9",
                candidate_id="answer-i",
                run_id="run-1",
                rubric="groundedness",
                score=4.5,
                verdict="pass",
                position="first",
                pair_id="pair-9",
                rationale="Grounded response with citations.",
                evidence=("doc-9",),
            ),
            JudgeRecord(
                case_id="case-9",
                candidate_id="answer-i",
                run_id="run-2",
                rubric="groundedness",
                score=2.5,
                verdict="fail",
                position="second",
                pair_id="pair-9",
                rationale="Missing important citation support.",
                evidence=("doc-9",),
            ),
        )

        summary = summarize_records(records, Policy(score_delta=2.0, position_delta=1.0))

        self.assertEqual(2, summary["records_scanned"])
        self.assertEqual(1, len(summary["agreement"]))
        self.assertEqual(2.0, summary["agreement"][0]["score_range"])
        self.assertEqual({"fail": 1, "pass": 1}, summary["agreement"][0]["verdict_counts"])
        self.assertEqual(0.5, summary["agreement"][0]["verdict_agreement"])
        self.assertEqual(
            {"lower": 0.094531, "upper": 0.905469, "successes": 1, "total": 2},
            summary["agreement"][0]["verdict_agreement_ci95"],
        )
        self.assertEqual(1, len(summary["position_effects"]))
        self.assertEqual(2.0, summary["position_effects"][0]["delta"])
        self.assertIn(
            {
                "score_delta": 2.0,
                "groups_flagged": 1,
                "groups_total": 1,
                "groups_flagged_rate": 1.0,
                "groups_flagged_ci95": {
                    "lower": 0.206549,
                    "upper": 1.0,
                    "successes": 1,
                    "total": 1,
                },
            },
            summary["threshold_sensitivity"]["score_instability"],
        )
        self.assertIn(
            {
                "position_delta": 1.0,
                "groups_flagged": 1,
                "groups_total": 1,
                "groups_flagged_rate": 1.0,
                "groups_flagged_ci95": {
                    "lower": 0.206549,
                    "upper": 1.0,
                    "successes": 1,
                    "total": 1,
                },
            },
            summary["threshold_sensitivity"]["position_bias"],
        )
        self.assertEqual("wilson_score", summary["confidence_intervals"]["method"])
        self.assertIn("position_effects:", render_metrics(summary))
        self.assertIn("threshold_sensitivity:", render_metrics(summary))
        self.assertIn("verdict_agreement_ci95=[0.094531, 0.905469]", render_metrics(summary))


if __name__ == "__main__":
    unittest.main()
