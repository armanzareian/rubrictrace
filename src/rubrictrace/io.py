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
PAIRWISE_CSV_FIELDS: tuple[str, ...] = (
    "case_id",
    "pair_id",
    "run_id",
    "rubric",
    "left_candidate",
    "right_candidate",
    "left_score",
    "right_score",
    "winner",
    "rationale",
    "evidence",
)
REQUIRED_PAIRWISE_CSV_FIELDS: tuple[str, ...] = (
    "case_id",
    "pair_id",
    "run_id",
    "rubric",
    "left_candidate",
    "right_candidate",
    "left_score",
    "right_score",
)
PAIRWISE_CSV_DEFAULT_COLUMNS: Mapping[str, str] = {
    field_name: field_name for field_name in PAIRWISE_CSV_FIELDS
}
RUBRIC_CSV_FIELDS: tuple[str, ...] = (
    "case_id",
    "candidate_id",
    "run_id",
    "verdict",
    "position",
    "pair_id",
    "rationale",
    "evidence",
    "score_columns",
)
REQUIRED_RUBRIC_CSV_FIELDS: tuple[str, ...] = ("case_id", "candidate_id", "run_id")
RUBRIC_CSV_DEFAULT_COLUMNS: Mapping[str, str] = {
    "case_id": "case_id",
    "candidate_id": "candidate_id",
    "run_id": "run_id",
    "verdict": "verdict",
    "position": "position",
    "pair_id": "pair_id",
    "rationale": "rationale",
    "evidence": "evidence",
}


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


def load_pairwise_csv_records(
    path: Path,
    field_mapping: Mapping[str, str] | None = None,
) -> tuple[JudgeRecord, ...]:
    _check_file(path)
    overrides = dict(field_mapping or {})
    _validate_pairwise_csv_overrides(overrides)

    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = reader.fieldnames
            if headers is None:
                raise InputError(f"{path}: CSV header row is required")
            resolved_mapping = _resolve_pairwise_csv_mapping(tuple(headers), overrides)
            _validate_csv_headers(path, tuple(headers), resolved_mapping)

            records: list[JudgeRecord] = []
            for row_index, row in enumerate(reader, start=2):
                records.extend(
                    _pairwise_csv_records(
                        path,
                        row_index,
                        cast(dict[str, str | None], row),
                        resolved_mapping,
                    )
                )
    except csv.Error as exc:
        raise InputError(f"{path}: invalid CSV: {exc}") from exc

    if not records:
        raise InputError(f"{path}: no judgment records found")
    return tuple(records)


def load_rubric_csv_records(
    path: Path,
    field_mapping: Mapping[str, str] | None = None,
) -> tuple[JudgeRecord, ...]:
    _check_file(path)
    overrides = dict(field_mapping or {})
    _validate_rubric_csv_overrides(overrides)

    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = reader.fieldnames
            if headers is None:
                raise InputError(f"{path}: CSV header row is required")
            resolved_mapping, score_columns = _resolve_rubric_csv_mapping(
                tuple(headers),
                overrides,
            )
            _validate_csv_headers(path, tuple(headers), resolved_mapping)

            records: list[JudgeRecord] = []
            for row_index, row in enumerate(reader, start=2):
                records.extend(
                    _rubric_csv_records(
                        path,
                        row_index,
                        cast(dict[str, str | None], row),
                        resolved_mapping,
                        score_columns,
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


def _validate_pairwise_csv_overrides(field_mapping: Mapping[str, str]) -> None:
    unknown = sorted(set(field_mapping) - set(PAIRWISE_CSV_FIELDS))
    if unknown:
        raise InputError(f"pairwise CSV mapping: unsupported field {unknown[0]!r}")
    for field_name, column in field_mapping.items():
        if not column.strip():
            raise InputError(f"pairwise CSV mapping: {field_name} column must be non-empty")


def _validate_rubric_csv_overrides(field_mapping: Mapping[str, str]) -> None:
    unknown = sorted(set(field_mapping) - set(RUBRIC_CSV_FIELDS))
    if unknown:
        raise InputError(f"rubric CSV mapping: unsupported field {unknown[0]!r}")
    for field_name, column in field_mapping.items():
        if not column.strip():
            raise InputError(f"rubric CSV mapping: {field_name} column must be non-empty")


def _resolve_pairwise_csv_mapping(
    headers: Sequence[str],
    overrides: Mapping[str, str],
) -> dict[str, str]:
    header_set = set(headers)
    mapping = {
        field_name: PAIRWISE_CSV_DEFAULT_COLUMNS[field_name]
        for field_name in REQUIRED_PAIRWISE_CSV_FIELDS
    }
    for field_name in ("winner", "rationale", "evidence"):
        default_column = PAIRWISE_CSV_DEFAULT_COLUMNS[field_name]
        if default_column in header_set:
            mapping[field_name] = default_column
    mapping.update(overrides)

    for field_name in REQUIRED_PAIRWISE_CSV_FIELDS:
        if field_name not in mapping:
            raise InputError(f"pairwise CSV mapping: missing required field {field_name!r}")
    return mapping


def _resolve_rubric_csv_mapping(
    headers: Sequence[str],
    overrides: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    header_set = set(headers)
    mapping: dict[str, str] = {}
    for field_name in REQUIRED_RUBRIC_CSV_FIELDS:
        default_column = RUBRIC_CSV_DEFAULT_COLUMNS[field_name]
        mapping[field_name] = default_column

    for field_name in ("verdict", "position", "pair_id", "rationale", "evidence"):
        default_column = RUBRIC_CSV_DEFAULT_COLUMNS[field_name]
        if default_column in header_set:
            mapping[field_name] = default_column

    score_columns = _default_rubric_score_columns(headers)
    for field_name, column in overrides.items():
        if field_name == "score_columns":
            score_columns = _parse_rubric_score_columns(column)
        else:
            mapping[field_name] = column

    for field_name in REQUIRED_RUBRIC_CSV_FIELDS:
        if field_name not in mapping:
            raise InputError(f"rubric CSV mapping: missing required field {field_name!r}")
    if not score_columns:
        raise InputError(
            "rubric CSV mapping: no rubric score columns found; "
            "use --map score_columns=rubric:column[,rubric:column]"
    )
    missing_score_columns = sorted(set(score_columns.values()) - header_set)
    if missing_score_columns:
        raise InputError(
            f"rubric CSV mapping: score column {missing_score_columns[0]!r} is missing"
        )
    return mapping, score_columns


def _default_rubric_score_columns(headers: Sequence[str]) -> dict[str, str]:
    score_columns: dict[str, str] = {}
    for header in headers:
        if header.endswith("_score") and len(header) > len("_score"):
            rubric = header[: -len("_score")].strip()
            if rubric:
                score_columns[rubric] = header
    return score_columns


def _parse_rubric_score_columns(value: str) -> dict[str, str]:
    score_columns: dict[str, str] = {}
    for item in value.split(","):
        if not item.strip():
            continue
        if ":" not in item:
            raise InputError("rubric CSV mapping: score_columns must use rubric:column pairs")
        rubric, column = item.split(":", 1)
        if not rubric.strip() or not column.strip():
            raise InputError("rubric CSV mapping: score_columns must use rubric:column pairs")
        score_columns[rubric.strip()] = column.strip()
    if not score_columns:
        raise InputError("rubric CSV mapping: score_columns must include at least one pair")
    return score_columns


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


def _pairwise_csv_records(
    path: Path,
    row_index: int,
    row: dict[str, str | None],
    field_mapping: Mapping[str, str],
) -> tuple[JudgeRecord, JudgeRecord]:
    case_id = _csv_text(path, row_index, row, field_mapping, "case_id")
    pair_id = _csv_text(path, row_index, row, field_mapping, "pair_id")
    run_id = _csv_text(path, row_index, row, field_mapping, "run_id")
    rubric = _csv_text(path, row_index, row, field_mapping, "rubric")
    left_candidate = _csv_text(path, row_index, row, field_mapping, "left_candidate")
    right_candidate = _csv_text(path, row_index, row, field_mapping, "right_candidate")
    left_score = _csv_number(
        row.get(field_mapping["left_score"]),
        "left_score",
        _csv_source(path, row_index, field_mapping["left_score"]),
    )
    right_score = _csv_number(
        row.get(field_mapping["right_score"]),
        "right_score",
        _csv_source(path, row_index, field_mapping["right_score"]),
    )
    rationale = _csv_optional_text(path, row_index, row, field_mapping, "rationale")
    evidence = _csv_evidence(
        row.get(field_mapping["evidence"]) if "evidence" in field_mapping else None
    )
    left_verdict, right_verdict = _pairwise_verdicts(
        row.get(field_mapping["winner"]) if "winner" in field_mapping else None,
        left_candidate=left_candidate,
        right_candidate=right_candidate,
        source=(
            _csv_source(path, row_index, field_mapping["winner"])
            if "winner" in field_mapping
            else f"{path}:{row_index}"
        ),
    )

    common: dict[str, Any] = {
        "case_id": case_id,
        "run_id": run_id,
        "rubric": rubric,
        "pair_id": pair_id,
        "evidence": evidence,
    }
    if rationale is not None:
        common["rationale"] = rationale

    return (
        _pairwise_record(
            path,
            row_index,
            {**common, "candidate_id": left_candidate, "score": left_score, "position": "left"},
            left_verdict,
        ),
        _pairwise_record(
            path,
            row_index,
            {
                **common,
                "candidate_id": right_candidate,
                "score": right_score,
                "position": "right",
            },
            right_verdict,
        ),
    )


def _rubric_csv_records(
    path: Path,
    row_index: int,
    row: dict[str, str | None],
    field_mapping: Mapping[str, str],
    score_columns: Mapping[str, str],
) -> tuple[JudgeRecord, ...]:
    common: dict[str, Any] = {
        "case_id": _csv_text(path, row_index, row, field_mapping, "case_id"),
        "candidate_id": _csv_text(path, row_index, row, field_mapping, "candidate_id"),
        "run_id": _csv_text(path, row_index, row, field_mapping, "run_id"),
        "evidence": _csv_evidence(
            row.get(field_mapping["evidence"]) if "evidence" in field_mapping else None
        ),
    }
    for optional_field in ("verdict", "position", "pair_id", "rationale"):
        value = _csv_optional_text(path, row_index, row, field_mapping, optional_field)
        if value is not None:
            common[optional_field] = value

    records: list[JudgeRecord] = []
    for rubric, column in score_columns.items():
        score = _csv_number(row.get(column), rubric, _csv_source(path, row_index, column))
        data = {**common, "rubric": rubric, "score": score}
        try:
            records.append(JudgeRecord.from_mapping(data, source=f"{path}:{row_index}"))
        except ModelError as exc:
            raise InputError(str(exc)) from exc
    return tuple(records)


def _pairwise_record(
    path: Path,
    row_index: int,
    data: dict[str, Any],
    verdict: str | None,
) -> JudgeRecord:
    if verdict is not None:
        data["verdict"] = verdict
    try:
        return JudgeRecord.from_mapping(data, source=f"{path}:{row_index}")
    except ModelError as exc:
        raise InputError(str(exc)) from exc


def _csv_text(
    path: Path,
    row_index: int,
    row: dict[str, str | None],
    field_mapping: Mapping[str, str],
    field_name: str,
) -> str:
    column = field_mapping[field_name]
    value = row.get(column)
    if value is None or not value.strip():
        raise InputError(f"{_csv_source(path, row_index, column)}: {field_name} must be non-empty")
    return value.strip()


def _csv_optional_text(
    path: Path,
    row_index: int,
    row: dict[str, str | None],
    field_mapping: Mapping[str, str],
    field_name: str,
) -> str | None:
    if field_name not in field_mapping:
        return None
    value = row.get(field_mapping[field_name])
    if value is None or not value.strip():
        return None
    return value.strip()


def _pairwise_verdicts(
    value: str | None,
    *,
    left_candidate: str,
    right_candidate: str,
    source: str,
) -> tuple[str | None, str | None]:
    if value is None or not value.strip():
        return (None, None)
    winner = value.strip().lower()
    if winner in {"tie", "draw", "equal", "both"}:
        return (None, None)

    left_aliases = {"left", "first", "a", "1", left_candidate.lower()}
    right_aliases = {"right", "second", "b", "2", right_candidate.lower()}
    if winner in left_aliases:
        return ("win", "lose")
    if winner in right_aliases:
        return ("lose", "win")
    raise InputError(f"{source}: winner must identify left, right, tie, or a candidate_id")


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


def _csv_source(path: Path, row_index: int, column: str) -> str:
    return f"{path}:{row_index} column {column!r}"
