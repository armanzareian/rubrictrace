from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rubrictrace.evaluation import evaluate_suite, render_evaluation
from rubrictrace.io import (
    InputError,
    load_csv_records,
    load_pairwise_csv_records,
    load_policy,
    load_records,
    load_rubric_csv_records,
)
from rubrictrace.models import Policy, RubricThresholds
from rubrictrace.scanner import audit_records

ROOT = Path(__file__).resolve().parents[1]
CSV_MAPPING = {
    "case_id": "item",
    "candidate_id": "answer",
    "run_id": "judge",
    "rubric": "dimension",
    "score": "judge_score",
    "verdict": "decision",
    "position": "order",
    "pair_id": "pair",
    "rationale": "why",
    "evidence": "evidence_refs",
}


class IoCliEvaluationTests(unittest.TestCase):
    def test_load_records_rejects_bad_record_without_echoing_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.jsonl"
            path.write_text('{"case_id":"x","score":1,"secret":"do-not-print"}\n', encoding="utf-8")

            with self.assertRaises(InputError) as caught:
                load_records(path)

        message = str(caught.exception)
        self.assertIn("missing required field", message)
        self.assertNotIn("do-not-print", message)

    def test_policy_loading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.json"
            path.write_text(
                json.dumps(
                    {
                        "fail_on": "medium",
                        "score_delta": 2.0,
                        "position_delta": 0.5,
                        "decision_threshold": 4.0,
                        "require_evidence": False,
                        "require_rationale": True,
                        "enabled_detectors": ["score_instability", "position_bias"],
                        "severity_overrides": {"position_bias": "high"},
                        "rubric_thresholds": {
                            "preference": {
                                "position_delta": 0.25,
                                "decision_threshold": 3.5,
                            }
                        },
                        "suppressions": ["0123456789abcdef"],
                    }
                ),
                encoding="utf-8",
            )

            policy = load_policy(path)

        self.assertEqual(
            Policy(
                fail_on="medium",
                score_delta=2.0,
                position_delta=0.5,
                decision_threshold=4.0,
                require_evidence=False,
                require_rationale=True,
                enabled_detectors=("score_instability", "position_bias"),
                severity_overrides={"position_bias": "high"},
                rubric_thresholds={
                    "preference": RubricThresholds(
                        position_delta=0.25,
                        decision_threshold=3.5,
                    )
                },
                suppressions=("0123456789abcdef",),
            ),
            policy,
        )

    def test_policy_loading_rejects_nested_error_without_echoing_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.json"
            path.write_text(
                json.dumps({"rubric_thresholds": {"groundedness": {"score_delta": "secret"}}}),
                encoding="utf-8",
            )

            with self.assertRaises(InputError) as caught:
                load_policy(path)

        message = str(caught.exception)
        self.assertIn("rubric_thresholds.groundedness.score_delta", message)
        self.assertNotIn("secret", message)

    def test_csv_mapping_loads_auditable_records(self) -> None:
        records = load_csv_records(ROOT / "examples/judgments/records.csv", CSV_MAPPING)

        self.assertEqual(4, len(records))
        self.assertEqual(("doc-refunds",), records[0].evidence)
        report = audit_records(records, Policy())

        self.assertEqual(
            {"position_bias", "score_instability", "threshold_flip", "verdict_conflict"},
            {issue.detector for issue in report.issues},
        )

    def test_csv_error_identifies_row_column_and_expected_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.csv"
            path.write_text(
                "item,answer,judge,dimension,judge_score\n"
                "case-1,answer-a,judge-1,groundedness,secret-score\n",
                encoding="utf-8",
            )

            with self.assertRaises(InputError) as caught:
                load_csv_records(
                    path,
                    {
                        "case_id": "item",
                        "candidate_id": "answer",
                        "run_id": "judge",
                        "rubric": "dimension",
                        "score": "judge_score",
                    },
                )

        message = str(caught.exception)
        self.assertIn("records.csv:2 column 'judge_score'", message)
        self.assertIn("score must be a number", message)
        self.assertNotIn("secret-score", message)

    def test_pairwise_csv_preset_expands_comparison_rows(self) -> None:
        records = load_pairwise_csv_records(ROOT / "examples/judgments/pairwise.csv")

        self.assertEqual(4, len(records))
        self.assertEqual(
            ["answer-a", "answer-b", "answer-b", "answer-a"],
            [record.candidate_id for record in records],
        )
        self.assertEqual(
            ["left", "right", "left", "right"],
            [record.position for record in records],
        )
        self.assertEqual(["win", "lose", "win", "lose"], [record.verdict for record in records])
        self.assertEqual(("doc-refunds", "eval-note-7"), records[0].evidence)

        report = audit_records(records, Policy(fail_on="critical"))

        self.assertEqual(
            {"position_bias", "score_instability", "threshold_flip", "verdict_conflict"},
            {issue.detector for issue in report.issues},
        )
        position_issue = next(issue for issue in report.issues if issue.detector == "position_bias")
        self.assertEqual("refund-pref-001", position_issue.pair_id)

    def test_pairwise_csv_error_identifies_row_column_and_expected_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pairwise.csv"
            path.write_text(
                "case_id,pair_id,run_id,rubric,left_candidate,right_candidate,"
                "left_score,right_score,winner\n"
                "case-1,pair-1,judge-1,preference,answer-a,answer-b,secret-score,2.0,left\n",
                encoding="utf-8",
            )

            with self.assertRaises(InputError) as caught:
                load_pairwise_csv_records(path)

        message = str(caught.exception)
        self.assertIn("pairwise.csv:2 column 'left_score'", message)
        self.assertIn("left_score must be a number", message)
        self.assertNotIn("secret-score", message)

    def test_rubric_csv_preset_expands_score_columns(self) -> None:
        records = load_rubric_csv_records(ROOT / "examples/judgments/rubric_safety.csv")

        self.assertEqual(6, len(records))
        self.assertEqual(
            ["safety", "helpfulness", "safety", "helpfulness", "safety", "helpfulness"],
            [record.rubric for record in records],
        )
        self.assertEqual(("safety-policy-1",), records[0].evidence)

        report = audit_records(records, Policy(fail_on="critical"))

        self.assertEqual(
            {"score_instability", "threshold_flip", "verdict_conflict"},
            {issue.detector for issue in report.issues},
        )
        self.assertFalse(report.failed())

    def test_rubric_csv_mapping_loads_retrieval_export(self) -> None:
        records = load_rubric_csv_records(
            ROOT / "examples/judgments/rubric_retrieval.csv",
            {
                "case_id": "question_id",
                "candidate_id": "answer_id",
                "run_id": "judge_id",
                "verdict": "decision",
                "rationale": "why",
                "evidence": "source_ids",
                "score_columns": "groundedness:grounded,coverage:coverage",
            },
        )

        self.assertEqual(4, len(records))
        self.assertEqual(
            ["groundedness", "coverage", "groundedness", "coverage"],
            [record.rubric for record in records],
        )
        self.assertEqual(("chunk-12", "chunk-17"), records[0].evidence)

        report = audit_records(records, Policy(fail_on="critical"))

        self.assertEqual(
            {"score_instability", "threshold_flip", "verdict_conflict"},
            {issue.detector for issue in report.issues},
        )

    def test_rubric_csv_error_identifies_row_column_and_expected_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rubric.csv"
            path.write_text(
                "case_id,candidate_id,run_id,safety_score\n"
                "case-1,answer-a,judge-1,secret-score\n",
                encoding="utf-8",
            )

            with self.assertRaises(InputError) as caught:
                load_rubric_csv_records(path)

        message = str(caught.exception)
        self.assertIn("rubric.csv:2 column 'safety_score'", message)
        self.assertIn("safety must be a number", message)
        self.assertNotIn("secret-score", message)

    def test_cli_audit_json_and_exit_code(self) -> None:
        command = [
            sys.executable,
            "-m",
            "rubrictrace",
            "audit",
            "--records",
            str(ROOT / "examples/judgments/records.jsonl"),
            "--policy",
            str(ROOT / "examples/judgments/policy.json"),
            "--format",
            "json",
            "--fail-on",
            "critical",
        ]

        result = subprocess.run(
            command,
            check=False,
            cwd=ROOT,
            env={"PYTHONPATH": "src"},
            text=True,
            capture_output=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(8, payload["records_scanned"])
        self.assertGreaterEqual(payload["issue_count"], 1)
        self.assertFalse(payload["failed"])

    def test_cli_audit_markdown_summary(self) -> None:
        command = [
            sys.executable,
            "-m",
            "rubrictrace",
            "audit",
            "--records",
            str(ROOT / "examples/judgments/records.jsonl"),
            "--policy",
            str(ROOT / "examples/judgments/policy.json"),
            "--format",
            "markdown",
            "--fail-on",
            "critical",
        ]

        result = subprocess.run(
            command,
            check=False,
            cwd=ROOT,
            env={"PYTHONPATH": "src"},
            text=True,
            capture_output=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("# RubricTrace Audit", result.stdout)
        self.assertIn("| Status | Records | Active issues | Suppressed | Fail on |", result.stdout)
        self.assertIn("score_instability", result.stdout)
        self.assertIn("fingerprint", result.stdout.lower())

    def test_cli_audit_csv_mapping(self) -> None:
        command = [
            sys.executable,
            "-m",
            "rubrictrace",
            "audit",
            "--records",
            str(ROOT / "examples/judgments/records.csv"),
            "--input-format",
            "csv",
            "--format",
            "json",
            "--fail-on",
            "critical",
        ]
        for field_name, column in CSV_MAPPING.items():
            command.extend(["--map", f"{field_name}={column}"])

        result = subprocess.run(
            command,
            check=False,
            cwd=ROOT,
            env={"PYTHONPATH": "src"},
            text=True,
            capture_output=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(4, payload["records_scanned"])
        self.assertEqual(
            ["position_bias", "score_instability", "threshold_flip", "verdict_conflict"],
            sorted(issue["detector"] for issue in payload["issues"]),
        )
        self.assertFalse(payload["failed"])

    def test_cli_audit_pairwise_csv_preset(self) -> None:
        command = [
            sys.executable,
            "-m",
            "rubrictrace",
            "audit",
            "--records",
            str(ROOT / "examples/judgments/pairwise.csv"),
            "--input-format",
            "pairwise-csv",
            "--format",
            "json",
            "--fail-on",
            "critical",
        ]

        result = subprocess.run(
            command,
            check=False,
            cwd=ROOT,
            env={"PYTHONPATH": "src"},
            text=True,
            capture_output=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(4, payload["records_scanned"])
        self.assertIn(
            "position_bias",
            {issue["detector"] for issue in payload["issues"]},
        )
        self.assertFalse(payload["failed"])

    def test_cli_audit_rubric_csv_preset(self) -> None:
        command = [
            sys.executable,
            "-m",
            "rubrictrace",
            "audit",
            "--records",
            str(ROOT / "examples/judgments/rubric_safety.csv"),
            "--input-format",
            "rubric-csv",
            "--format",
            "json",
            "--fail-on",
            "critical",
        ]

        result = subprocess.run(
            command,
            check=False,
            cwd=ROOT,
            env={"PYTHONPATH": "src"},
            text=True,
            capture_output=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(6, payload["records_scanned"])
        self.assertIn(
            "verdict_conflict",
            {issue["detector"] for issue in payload["issues"]},
        )
        self.assertFalse(payload["failed"])

    def test_cli_fails_on_high_threshold(self) -> None:
        command = [
            sys.executable,
            "-m",
            "rubrictrace",
            "audit",
            "--records",
            str(ROOT / "examples/judgments/records.jsonl"),
            "--policy",
            str(ROOT / "examples/judgments/policy.json"),
            "--fail-on",
            "high",
        ]

        result = subprocess.run(
            command,
            check=False,
            cwd=ROOT,
            env={"PYTHONPATH": "src"},
            text=True,
            capture_output=True,
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("score_instability", result.stdout)

    def test_cli_ci_format_suppresses_reviewed_fingerprint(self) -> None:
        records = load_records(ROOT / "examples/judgments/records.jsonl")
        policy = load_policy(ROOT / "examples/judgments/policy.json")
        report = audit_records(records, policy)
        score_fingerprint = next(
            issue.fingerprint for issue in report.issues if issue.detector == "score_instability"
        )
        command = [
            sys.executable,
            "-m",
            "rubrictrace",
            "audit",
            "--records",
            str(ROOT / "examples/judgments/records.jsonl"),
            "--policy",
            str(ROOT / "examples/judgments/policy.json"),
            "--format",
            "ci",
            "--fail-on",
            "critical",
            "--severity-override",
            "threshold_flip=critical",
            "--suppress-fingerprint",
            score_fingerprint,
        ]

        result = subprocess.run(
            command,
            check=False,
            cwd=ROOT,
            env={"PYTHONPATH": "src"},
            text=True,
            capture_output=True,
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("RubricTrace: fail", result.stdout)
        self.assertIn("suppressed=1", result.stdout)
        self.assertIn("threshold_flip", result.stdout)
        self.assertNotIn(score_fingerprint, result.stdout)

    def test_evaluation_suite_matches_expected_issues(self) -> None:
        suite = json.loads((ROOT / "examples/judgments/suite.json").read_text(encoding="utf-8"))
        result = evaluate_suite(suite)

        self.assertEqual(1.0, result["precision"])
        self.assertEqual(1.0, result["recall"])
        self.assertEqual(1.0, result["f1"])
        self.assertEqual(0, result["false_positive"])
        self.assertEqual(0, result["false_negative"])

    def test_evaluation_false_positive_notes_include_review_context(self) -> None:
        suite = {
            "name": "review-context",
            "policy": {
                "require_evidence": True,
                "require_rationale": True,
            },
            "records": [
                {
                    "case_id": "safety-001",
                    "candidate_id": "answer-a",
                    "run_id": "judge-run-1",
                    "rubric": "safety",
                    "score": 4.0,
                    "verdict": "pass",
                    "rationale": "The answer declines unsafe instructions.",
                    "evidence": [],
                }
            ],
            "expected_issues": [],
        }

        result = evaluate_suite(suite)

        self.assertEqual(1, result["false_positive"])
        self.assertEqual(1, len(result["false_positive_notes"]))
        note = result["false_positive_notes"][0]
        self.assertEqual("missing_evidence", note["detector"])
        self.assertEqual("safety-001", note["case_id"])
        self.assertEqual("answer-a", note["candidate_id"])
        self.assertEqual("safety", note["rubric"])
        self.assertRegex(note["fingerprint"], r"^[0-9a-f]{16}$")
        self.assertEqual({"run_id": "judge-run-1"}, note["evidence"])
        self.assertIn("missing evidence handles", note["message"])
        self.assertIn("expected_issues", note["review_note"])

        rendered = render_evaluation(result)
        self.assertIn("false_positive_review:", rendered)
        self.assertIn("missing_evidence", rendered)
        self.assertIn("fingerprint=", rendered)

    def test_cli_eval(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "rubrictrace",
                "eval",
                "--suite",
                str(ROOT / "examples/judgments/suite.json"),
            ],
            check=False,
            cwd=ROOT,
            env={"PYTHONPATH": "src"},
            text=True,
            capture_output=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("mismatches: none", result.stdout)
        self.assertIn("detectors:", result.stdout)

    def test_cli_metrics_json(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "rubrictrace",
                "metrics",
                "--records",
                str(ROOT / "examples/judgments/records.jsonl"),
                "--policy",
                str(ROOT / "examples/judgments/policy.json"),
                "--format",
                "json",
            ],
            check=False,
            cwd=ROOT,
            env={"PYTHONPATH": "src"},
            text=True,
            capture_output=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(8, payload["records_scanned"])
        self.assertEqual(
            {
                "agreement",
                "confidence_intervals",
                "policy_thresholds",
                "position_effects",
                "records_scanned",
                "threshold_sensitivity",
            },
            set(payload),
        )
        self.assertEqual("wilson_score", payload["confidence_intervals"]["method"])
        refund_row = next(row for row in payload["agreement"] if row["case_id"] == "refund-001")
        self.assertEqual("answer-a", refund_row["candidate_id"])
        self.assertEqual(0.094531, refund_row["verdict_agreement_ci95"]["lower"])
        self.assertEqual("refund-pair", payload["position_effects"][0]["pair_id"])
        self.assertIn(
            {
                "score_delta": 1.5,
                "groups_flagged": 1,
                "groups_total": 3,
                "groups_flagged_rate": 0.333333,
                "groups_flagged_ci95": {
                    "lower": 0.061492,
                    "upper": 0.79234,
                    "successes": 1,
                    "total": 3,
                },
            },
            payload["threshold_sensitivity"]["score_instability"],
        )


if __name__ == "__main__":
    unittest.main()
