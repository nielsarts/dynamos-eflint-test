"""Scenario self-test consistency gate.

Wraps the existing ``eflint-test.py`` CLI as a subprocess so the harness can
verify that a scenario's ``//#assert`` / ``//#violated`` comments still hold
against the eFLINT reasoner BEFORE we compare its derived expected outcome
against the SUT. A scenario whose self-tests fail is *inconsistent*: the
problem lies in the eFLINT specification or the assertions themselves, not
in the Policy Enforcer.

This module deliberately runs ``eflint-test.py`` as an external process
rather than importing it: the script's filename contains a dash (``-``)
which makes it awkward to import, and the unit-tester explicitly advertises
itself as a stand-alone tool ([docs/eflint-unit-test.md](docs/eflint-unit-test.md)).
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from harness.manifest import Manifest


# The unit-tester script lives at the repository root (NOT inside src/).
_DEFAULT_TESTER = Path(__file__).resolve().parents[2] / "eflint-test.py"


@dataclass(frozen=True)
class ConsistencyResult:
    consistent: bool
    returncode: int
    stdout: str
    stderr: str

    def render(self) -> str:
        if self.consistent:
            return f"scenario self-test: OK (exit {self.returncode})"
        return (
            f"scenario self-test: FAILED (exit {self.returncode})\n"
            f"--- eflint-test.py stdout ---\n{self.stdout}\n"
            f"--- eflint-test.py stderr ---\n{self.stderr}"
        )


def check_scenario_consistency(
    manifest: Manifest,
    *,
    tester_path: str | Path | None = None,
    eflint_repl_exe: str | None = None,
    timeout_s: float = 60.0,
) -> ConsistencyResult:
    """Run eflint-test.py against the manifest's scenario file.

    The scenario file already contains ``//#violated`` / ``//#assert``
    comments that pin down the expected reasoner behaviour. The unit-tester
    walks the file phrase-by-phrase against eflint-repl and exits non-zero
    if any assertion fails.

    The harness invokes the tester on just the scenario file: ``#require``
    directives at the top of the scenario pick up the interface, shared
    rules, and per-steward agreements via the include path
    (``-i <scenarios_dir>``).
    """
    tester = Path(tester_path or os.environ.get("EFLINT_TEST_PY") or _DEFAULT_TESTER)
    if not tester.is_file():
        raise FileNotFoundError(f"eflint-test.py not found at {tester}")

    # ``-i`` in eflint-test.py uses ``nargs='*'`` which would greedily
    # consume the following FILE positional. Pass FILE first, options after.
    cmd: list[str] = ["python3", str(tester), str(manifest.scenario_file)]
    repl = eflint_repl_exe or os.environ.get("EFLINT_REPL_EXE")
    if repl:
        cmd.extend(["--exec", repl])
    cmd.extend(["-i", str(manifest.scenarios_dir)])

    proc = subprocess.run(  # noqa: S603 - controlled command
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        cwd=str(manifest.scenarios_dir),
    )
    return ConsistencyResult(
        consistent=proc.returncode == 0,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )
