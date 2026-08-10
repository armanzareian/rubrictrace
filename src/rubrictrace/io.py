from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from .models import JudgeRecord, ModelError, Policy

MAX_INPUT_BYTES = 10 * 1024 * 1024
CSV_FIELDS: tuple[str, ...] = (
    "case_id",
    "candidate_id",
    "run_id",
    "rubric",
    "score",
    "verdict",
    "position",
    "pair_id",
    "rationale",
    "evidence",
)
REQUIRED_CSV_FIELDS: tuple[str, ...] = ("case_id", "candidate_id", "run_id", "rubric", "score")


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


def load_csv_records(path: Path, field_mapping: Mapping[str, str]) -> tuple[JudgeRecord, ...]:
    _check_file(path)
    _validate_csv_mapping(field_mapping)

    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = reader.fieldnames
            if headers is None:
                raise InputError(f"{path}: CSV header row is required")
            _validate_csv_headers(path, tuple(headers), field_mapping)

            records: list[JudgeRecord] = []
            for row_index, row in enumerate(reader, start=2):
                records.append(
                    _csv_record(
                        path,
                        row_index,
                        cast(dict[str, str | None], row),
                        field_mapping,
                    )
                )
    except csv.Error as exc:
        raise InputError(f"{path}: invalid CSV: {exc}") from exc

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


def _validate_csv_mapping(field_mapping: Mapping[str, str]) -> None:
    unknown = sorted(set(field_mapping) - set(CSV_FIELDS))
    if unknown:
        raise InputError(f"CSV mapping: unsupported field {unknown[0]!r}")
    for field_name in REQUIRED_CSV_FIELDS:
        if field_name not in field_mapping:
            raise InputError(f"CSV mapping: missing required field {field_name!r}")
    for field_name, column in field_mapping.items():
        if not column.strip():
            raise InputError(f"CSV mapping: {field_name} column must be non-empty")


def _validate_csv_headers(
    path: Path,
    headers: Sequence[str],
    field_mapping: Mapping[str, str],
) -> None:
    missing = sorted(set(field_mapping.values()) - set(headers))
    if missing:
        raise InputError(f"{path}: CSV header missing mapped column {missing[0]!r}")


def _csv_record(
    path: Path,
    row_index: int,
    row: dict[str, str | None],
    field_mapping: Mapping[str, str],
) -> JudgeRecord:
    data: dict[str, Any] = {}
    for field_name, column in field_mapping.items():
        value = row.get(column)
        source = f"{path}:{row_index} column {column!r}"
        if field_name in REQUIRED_CSV_FIELDS and (value is None or not value.strip()):
            raise InputError(f"{source}: {field_name} must be non-empty")
        if field_name == "score":
            data[field_name] = _csv_number(value, field_name, source)
        elif field_name == "evidence":
            data[field_name] = _csv_evidence(value)
        elif value is not None and value.strip():
            data[field_name] = value.strip()

    try:
        return JudgeRecord.from_mapping(data, source=f"{path}:{row_index}")
    except ModelError as exc:
        raise InputError(str(exc)) from exc


def _csv_number(value: str | None, field_name: str, source: str) -> float:
    if value is None or not value.strip():
        raise InputError(f"{source}: {field_name} must be a number")
    try:
        return float(value)
    except ValueError as exc:
        raise InputError(f"{source}: {field_name} must be a number") from exc


def _csv_evidence(value: str | None) -> list[str]:
    if value is None or not value.strip():
        return []
    return [item.strip() for item in value.split(";") if item.strip()]
