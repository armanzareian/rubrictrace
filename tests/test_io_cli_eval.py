from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rubrictrace.evaluation import evaluate_suite
from rubrictrace.io import InputError, load_policy, load_records
from rubrictrace.models import Policy, RubricThresholds
from rubrictrace.scanner import audit_records

ROOT = Path(__file__).resolve().parents[1]


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


if __name__ == "__main__":
    unittest.main()
