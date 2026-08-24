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
from .models import AuditReport, Issue, JudgeRecord, Policy, RubricThresholds
from .scanner import audit_records

__all__ = [
    "AuditReport",
    "CiTemplateOptions",
    "InputError",
    "Issue",
    "JudgeRecord",
    "Policy",
    "RubricThresholds",
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
