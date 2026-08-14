from __future__ import annotations

import unittest

from rubrictrace.models import JudgeRecord, Policy, RubricThresholds
from rubrictrace.metrics import render_metrics, summarize_records
from rubrictrace.report import render_report
from rubrictrace.scanner import audit_records


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
        rendered_json = render_report(report, output_format="json")

        self.assertEqual(fingerprints, [issue.fingerprint for issue in report.issues])
        self.assertIn(fingerprints[0], text)
        self.assertIn(fingerprints[0], ci)
        self.assertIn(fingerprints[0], rendered_json)

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
