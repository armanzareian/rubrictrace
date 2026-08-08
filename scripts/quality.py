from __future__ import annotations

import compileall
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]


def main() -> int:
    checks = [
        check_compile(),
        check_json_files(),
        check_whitespace(),
        check_public_boundary(),
        check_secret_patterns(),
    ]
    failed = [name for name, ok in checks if not ok]
    if failed:
        for name in failed:
            print(f"quality check failed: {name}", file=sys.stderr)
        return 1
    print("quality checks passed")
    return 0


def check_compile() -> tuple[str, bool]:
    ok = compileall.compile_dir(ROOT / "src", quiet=1)
    ok = compileall.compile_dir(ROOT / "tests", quiet=1) and ok
    return ("compile", ok)


def check_json_files() -> tuple[str, bool]:
    ok = True
    for path in sorted(ROOT.rglob("*.json")):
        if _ignored_path(path):
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"{path}: invalid JSON: {exc}", file=sys.stderr)
            ok = False
    for path in sorted(ROOT.rglob("*.jsonl")):
        if _ignored_path(path):
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"{path}:{line_number}: invalid JSONL: {exc}", file=sys.stderr)
                ok = False
    return ("json", ok)


def check_whitespace() -> tuple[str, bool]:
    ok = True
    for path in _text_files():
        text = path.read_text(encoding="utf-8")
        if "\r\n" in text:
            print(f"{path}: CRLF line endings", file=sys.stderr)
            ok = False
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.rstrip() != line:
                print(f"{path}:{line_number}: trailing whitespace", file=sys.stderr)
                ok = False
        if text and not text.endswith("\n"):
            print(f"{path}: missing final newline", file=sys.stderr)
            ok = False
    return ("whitespace", ok)


def check_public_boundary() -> tuple[str, bool]:
    ignored_names = {
        "active_project.json",
        "project_registry.json",
        "roadmap.md",
        "ROADMAP.md",
        "TODO.private.md",
    }
    ok = True
    for path in ROOT.rglob("*"):
        if _ignored_path(path):
            continue
        if path.name in ignored_names and path.name != ".gitignore":
            print(f"{path}: private coordination name should not be in the tree", file=sys.stderr)
            ok = False
        if path.is_dir() and path.name == ".project-control":
            print(f"{path}: private control directory should not be in the tree", file=sys.stderr)
            ok = False
    return ("public-boundary", ok)


def check_secret_patterns() -> tuple[str, bool]:
    ok = True
    for path in _text_files():
        text = path.read_text(encoding="utf-8")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                print(f"{path}: high-confidence credential-like pattern", file=sys.stderr)
                ok = False
    return ("secret-patterns", ok)


def _text_files() -> list[Path]:
    result: list[Path] = []
    for path in ROOT.rglob("*"):
        if _ignored_path(path) or not path.is_file():
            continue
        if path.suffix in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico"}:
            continue
        result.append(path)
    return result


def _ignored_path(path: Path) -> bool:
    if ".git" in path.parts:
        return True
    if "build" in path.parts:
        return True
    if "__pycache__" in path.parts:
        return True
    return any(part.endswith(".egg-info") for part in path.parts)


if __name__ == "__main__":
    raise SystemExit(main())
