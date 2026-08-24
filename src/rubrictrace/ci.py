from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from shlex import quote, split

from .models import SEVERITIES

INPUT_FORMATS: tuple[str, ...] = ("jsonl", "csv", "pairwise-csv", "rubric-csv")
CI_TEMPLATE_MODES: tuple[str, ...] = ("advisory", "strict", "both")


@dataclass(frozen=True)
class CiTemplateOptions:
    records: str
    input_format: str = "jsonl"
    field_mapping: tuple[str, ...] = ()
    policy: str | None = None
    baseline: str | None = None
    advisory_fail_on: str = "low"
    strict_fail_on: str = "high"
    python_command: str = "python -m rubrictrace"


@dataclass(frozen=True)
class CiStep:
    name: str
    command: tuple[str, ...]
    redirect_to_step_summary: bool = False
    continue_on_error: bool = False


def render_github_actions_steps(
    options: CiTemplateOptions,
    *,
    mode: str = "both",
) -> str:
    """Render baseline-aware GitHub Actions steps for advisory and strict gates."""

    _validate_options(options, mode)
    lines: list[str] = []
    for step in _steps_for(options, mode):
        lines.append(f"- name: {step.name}")
        if step.continue_on_error:
            lines.append("  continue-on-error: true")
        lines.append("  run: |")
        wrapped = _wrapped_command_lines(step.command)
        for index, command_line in enumerate(wrapped):
            if step.redirect_to_step_summary and index == len(wrapped) - 1:
                command_line = f'{command_line} >> "$GITHUB_STEP_SUMMARY"'
            lines.append(f"    {command_line}")
    return "\n".join(lines) + "\n"


def _steps_for(options: CiTemplateOptions, mode: str) -> tuple[CiStep, ...]:
    steps: list[CiStep] = []
    baseline_label = " with baseline" if options.baseline else ""
    if mode in {"advisory", "both"}:
        steps.append(
            CiStep(
                name=f"RubricTrace advisory audit{baseline_label}",
                command=_audit_command(
                    options,
                    output_format="markdown",
                    fail_on=options.advisory_fail_on,
                ),
                redirect_to_step_summary=True,
                continue_on_error=True,
            )
        )
    if mode in {"strict", "both"}:
        steps.append(
            CiStep(
                name=f"RubricTrace strict audit gate{baseline_label}",
                command=_audit_command(
                    options,
                    output_format="ci",
                    fail_on=options.strict_fail_on,
                ),
            )
        )
    return tuple(steps)


def _audit_command(
    options: CiTemplateOptions,
    *,
    output_format: str,
    fail_on: str,
) -> tuple[str, ...]:
    command = [
        *split(options.python_command),
        "audit",
        "--records",
        options.records,
        "--input-format",
        options.input_format,
    ]
    if options.policy:
        command.extend(["--policy", options.policy])
    if options.baseline:
        command.extend(["--baseline", options.baseline])
    for mapping in options.field_mapping:
        command.extend(["--map", mapping])
    command.extend(["--format", output_format, "--fail-on", fail_on])
    return tuple(command)


def _wrapped_command_lines(command: Sequence[str]) -> tuple[str, ...]:
    if len(command) <= 4:
        return (" ".join(quote(token) for token in command),)

    groups = [" ".join(quote(token) for token in command[:4])]
    index = 4
    while index < len(command):
        token = command[index]
        if token.startswith("--") and index + 1 < len(command):
            groups.append(f"  {quote(token)} {quote(command[index + 1])}")
            index += 2
        else:
            groups.append(f"  {quote(token)}")
            index += 1

    return tuple(
        f"{line} \\" if index < len(groups) - 1 else line
        for index, line in enumerate(groups)
    )


def _validate_options(options: CiTemplateOptions, mode: str) -> None:
    if mode not in CI_TEMPLATE_MODES:
        raise ValueError("CI template mode must be advisory, strict, or both")
    if options.input_format not in INPUT_FORMATS:
        raise ValueError(
            "CI template input format must be jsonl, csv, pairwise-csv, or rubric-csv"
        )
    if options.advisory_fail_on not in SEVERITIES:
        raise ValueError("advisory fail_on must be low, medium, high, or critical")
    if options.strict_fail_on not in SEVERITIES:
        raise ValueError("strict fail_on must be low, medium, high, or critical")
    if not options.records.strip():
        raise ValueError("records path must be non-empty")
    if not split(options.python_command):
        raise ValueError("python command must be non-empty")
