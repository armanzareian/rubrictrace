"""Offline audits for LLM-as-judge result logs."""

from .ci import CiTemplateOptions, render_github_actions_steps
from .io import (
    InputError,
    load_baseline,
    load_csv_records,
    load_pairwise_csv_records,
    load_policy,
    load_records,
    load_rubric_csv_records,
)
from .metrics import render_metrics, summarize_records
from .models import (
    REPORT_SCHEMA_VERSION,
    AuditReport,
    Issue,
    JudgeRecord,
    Policy,
    RubricThresholds,
)
from .scanner import CustomDetector, CustomDetectorError, DetectorContext, audit_records

__all__ = [
    "AuditReport",
    "CiTemplateOptions",
    "InputError",
    "Issue",
    "JudgeRecord",
    "Policy",
    "REPORT_SCHEMA_VERSION",
    "RubricThresholds",
    "CustomDetector",
    "CustomDetectorError",
    "DetectorContext",
    "audit_records",
    "load_baseline",
    "load_csv_records",
    "load_pairwise_csv_records",
    "load_policy",
    "load_records",
    "load_rubric_csv_records",
    "render_github_actions_steps",
    "render_metrics",
    "summarize_records",
]

__version__ = "0.1.0"
