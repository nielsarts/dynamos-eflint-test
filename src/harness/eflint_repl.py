"""Minimal eflint-repl driver used by the oracle.

The driver speaks the same protocol as eflint-test.py's ``Reasoner``: a fresh
trigger Fact whose state is toggled after each submission, so each phrase's
output is bracketed by a known sentinel line. This is the only reliable way
to know that eflint-repl finished processing a phrase, because the REPL emits
prompts (``#N > ``) inline with output.

The driver does NOT parse eFLINT instances — it just records the raw output
captured between sentinels. The oracle then scans that output for specific
markers (``violated invariant!: <name>``, ``+<name>()``).
"""
from __future__ import annotations

import os
import random
import string
import subprocess
import threading
from collections.abc import Iterable
from pathlib import Path


READY_MARKER = " or just type a <PHRASE>"


class EflintReplError(RuntimeError):
    """The eflint-repl subprocess produced an unrecoverable error or exited."""


class EflintRepl:
    """Driver around an eflint-repl process.

    Usage:
        with EflintRepl(include_dirs=[scenarios_dir]) as repl:
            repl.submit_many(flatten_files([...]))
            output = repl.submit("Invariant q_a When permitted-request(Niels).")
            assert "violated invariant!: q_a" not in output
    """

    def __init__(
        self,
        *,
        executable: str | None = None,
        include_dirs: Iterable[str | Path] = (),
        startup_timeout_s: float = 10.0,
    ) -> None:
        exe = executable or os.environ.get("EFLINT_REPL_EXE", "eflint-repl")
        cmd: list[str] = [exe]
        for d in include_dirs:
            cmd.extend(["-i", str(Path(d).resolve())])
        self._cmd = cmd

        self._proc = subprocess.Popen(  # noqa: S603 - controlled command
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )

        suffix = "".join(random.choices(string.ascii_lowercase, k=16))
        self._trigger_fact = f"unitcheck{suffix}"
        self._trigger_state = False  # current logical state of the fact

        self._wait_for_ready(startup_timeout_s)

        self._raw_submit(f"Fact {self._trigger_fact} Identified by Int.")
        self._drain_until_sentinel(initial=True)

    def __enter__(self) -> "EflintRepl":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def trigger_fact(self) -> str:
        return self._trigger_fact

    def close(self) -> None:
        if self._proc.poll() is None:
            try:
                if self._proc.stdin and not self._proc.stdin.closed:
                    try:
                        self._proc.stdin.write(b":quit\n")
                        self._proc.stdin.flush()
                    except (BrokenPipeError, OSError):
                        pass
                    try:
                        self._proc.stdin.close()
                    except OSError:
                        pass
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=2)

    def submit_many(self, phrases: Iterable[str]) -> str:
        """Submit a batch of phrases. Returns the concatenated captured output."""
        captured: list[str] = []
        for p in phrases:
            p = p.strip()
            if not p:
                continue
            captured.append(self.submit(p))
        return "".join(captured)

    def submit(self, phrase: str) -> str:
        """Submit one eFLINT phrase and return the captured output.

        The output does NOT include the prompt prefixes (``#N > ``) or the
        sentinel line.
        """
        phrase = phrase.strip()
        if not phrase:
            return ""
        if self._proc.poll() is not None:
            raise EflintReplError(
                f"eflint-repl exited unexpectedly with code {self._proc.returncode}"
            )
        self._raw_submit(phrase)
        self._raw_submit(self._next_trigger_phrase())
        self._trigger_state = not self._trigger_state
        return self._drain_until_sentinel(initial=False)

    def _raw_submit(self, phrase: str) -> None:
        assert self._proc.stdin is not None
        try:
            self._proc.stdin.write(phrase.encode("utf-8") + b"\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise EflintReplError(f"failed to write to eflint-repl: {e}") from e

    def _wait_for_ready(self, timeout_s: float) -> None:
        """Consume the help banner until the 'or just type a <PHRASE>' line."""
        deadline = threading.Event()
        timer = threading.Timer(timeout_s, deadline.set)
        timer.start()
        try:
            assert self._proc.stdout is not None
            while True:
                if deadline.is_set():
                    raise EflintReplError(
                        f"eflint-repl did not become ready within {timeout_s}s"
                    )
                line = self._proc.stdout.readline()
                if not line:
                    raise EflintReplError(
                        "eflint-repl closed stdout before becoming ready"
                    )
                text = line.decode("utf-8", errors="replace")
                if text.startswith(READY_MARKER):
                    return
        finally:
            timer.cancel()

    def _next_trigger_phrase(self) -> str:
        """The phrase that flips the trigger fact's state."""
        sign = "~" if self._trigger_state else "+"
        return f"{sign}{self._trigger_fact}(0)."

    def _expected_sentinel_token(self) -> str:
        """The fragment we expect to appear on the trigger-echo line."""
        sign = "~" if not self._trigger_state else "+"
        return f"{sign}{self._trigger_fact}(0)"

    def _drain_until_sentinel(self, *, initial: bool) -> str:
        """Read output lines until we see the trigger-echo line.

        For ``initial=True`` we're consuming the first trigger-fact setup,
        whose echo is ``+<trigger>(0)`` (since the state we just transitioned
        to is True). The output between prompts is discarded.

        For subsequent calls, we strip the prompts and return everything
        between them up to (excluding) the sentinel echo.
        """
        assert self._proc.stdout is not None
        out_lines: list[str] = []

        if initial:
            # First setup: declare Fact + plant first sentinel (`+(0)`).
            self._raw_submit(self._next_trigger_phrase())
            self._trigger_state = True
            sentinel_token = f"+{self._trigger_fact}(0)"
        else:
            sentinel_token = self._expected_sentinel_token()

        while True:
            raw = self._proc.stdout.readline()
            if not raw:
                raise EflintReplError(
                    "eflint-repl closed stdout while waiting for sentinel"
                )
            line = raw.decode("utf-8", errors="replace")
            stripped = _strip_prompts(line)
            for piece in stripped:
                if sentinel_token in piece:
                    return "".join(out_lines)
                out_lines.append(piece)


def _strip_prompts(line: str) -> list[str]:
    """Remove leading ``#N > `` prompts; an output line may contain several."""
    pieces: list[str] = []
    rest = line
    while True:
        if not rest:
            break
        if rest.startswith("#"):
            gt = rest.find(" > ")
            if gt < 0:
                pieces.append(rest)
                break
            rest = rest[gt + 3 :]
            continue
        pieces.append(rest)
        break
    return pieces
