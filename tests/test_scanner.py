from __future__ import annotations

import unittest

from rubrictrace.models import JudgeRecord, Policy
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


if __name__ == "__main__":
    unittest.main()
