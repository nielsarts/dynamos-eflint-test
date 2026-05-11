"""Vendored copy of the flatten algorithm from flatten.py.

flatten.py at the repository root is a CLI we want to keep using from the
command line and from eflint-test.py, but the harness needs the same logic
callable as a function. This module duplicates the trivial algorithm; the
duplication is intentional — the CLI script stays self-contained.
"""
from __future__ import annotations

from pathlib import Path


def flatten_file(path: str | Path) -> list[str]:
    """Return one eFLINT phrase per element, joining indented continuations.

    Skips blank lines, ``//`` comments, and ``#require`` / ``#include``
    directives. Files are combined in load order by the caller, so these
    directives are redundant and cause double-loading when eflint-repl
    encounters the same definitions twice.
    """
    phrases: list[str] = []
    current = ""
    with Path(path).open() as f:
        for raw in f:
            line = raw.rstrip("\n")
            stripped = line.lstrip()
            if not stripped or stripped.startswith("//"):
                continue
            if stripped.startswith("#require") or stripped.startswith("#include"):
                continue
            is_continuation = bool(line) and line[0] in (" ", "\t")
            if is_continuation and current:
                current += " " + stripped
            else:
                if current:
                    phrases.append(current)
                current = stripped
    if current:
        phrases.append(current)
    return phrases


def flatten_files(paths: list[str | Path]) -> list[str]:
    """Flatten multiple eFLINT files in order."""
    out: list[str] = []
    for p in paths:
        out.extend(flatten_file(p))
    return out
