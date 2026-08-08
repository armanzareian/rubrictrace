from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import JudgeRecord, ModelError, Policy

MAX_INPUT_BYTES = 10 * 1024 * 1024


class InputError(ValueError):
    """Raised when a user-supplied input file cannot be loaded."""


def load_records(path: Path) -> tuple[JudgeRecord, ...]:
    _check_file(path)
    records: list[JudgeRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            source = f"{path}:{line_number}"
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise InputError(f"{source}: invalid JSON: {exc.msg}") from exc
            if not isinstance(row, dict):
                raise InputError(f"{source}: expected a JSON object")
            try:
                records.append(JudgeRecord.from_mapping(row, source=source))
            except ModelError as exc:
                raise InputError(str(exc)) from exc
    if not records:
        raise InputError(f"{path}: no judgment records found")
    return tuple(records)


def load_policy(path: Path | None) -> Policy:
    if path is None:
        return Policy()
    _check_file(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputError(f"{path}: invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise InputError(f"{path}: expected a JSON object")
    try:
        return Policy.from_mapping(data)
    except ModelError as exc:
        raise InputError(str(exc)) from exc


def load_suite(path: Path) -> dict[str, Any]:
    _check_file(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputError(f"{path}: invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise InputError(f"{path}: expected a JSON object")
    return data


def _check_file(path: Path) -> None:
    if not path.exists():
        raise InputError(f"{path}: file does not exist")
    if not path.is_file():
        raise InputError(f"{path}: expected a file")
    size = path.stat().st_size
    if size > MAX_INPUT_BYTES:
        raise InputError(f"{path}: file exceeds {MAX_INPUT_BYTES} bytes")
