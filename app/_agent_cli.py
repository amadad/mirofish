"""Agent-friendly CLI helpers.

Single-file reference implementation of the conventions in
~/agents/_rules/general/cli.md. Copy this into your repo (e.g.
src/<pkg>/_agent_cli.py) and import from it. No dependencies beyond
stdlib; Rich is optional and only used if already installed.

Usage:
    from _agent_cli import (
        doctor_runner, create_console, read_stdin_or_file,
        confirm_or_abort, emit_json, emit_path,
    )
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

__all__ = [
    "DoctorCheck",
    "doctor_runner",
    "create_console",
    "read_stdin_or_file",
    "confirm_or_abort",
    "emit_json",
    "emit_path",
    "is_tty",
    "no_color",
]


def is_tty() -> bool:
    """True if stdout is a real terminal."""
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def no_color() -> bool:
    """Honor the NO_COLOR env var (https://no-color.org/) or a non-tty stdout."""
    return bool(os.environ.get("NO_COLOR")) or not is_tty()


def create_console():
    """Return a Rich Console that auto-disables ANSI on non-tty / NO_COLOR.

    Falls back to a tiny stdlib shim if Rich isn't installed.
    """
    try:
        from rich.console import Console  # type: ignore
        return Console(
            force_terminal=not no_color(),
            no_color=no_color(),
            highlight=False,
            soft_wrap=True,
        )
    except Exception:
        class _Shim:
            def print(self, *args: Any, **kwargs: Any) -> None:  # noqa: A003
                print(*args)
        return _Shim()


# ---------- doctor ----------

@dataclass
class DoctorCheck:
    name: str
    check: Callable[[], bool]
    hint: Optional[str] = None  # printed on failure


def doctor_runner(checks: Iterable[DoctorCheck | tuple], *, exit_on_fail: bool = True) -> int:
    """Run doctor checks, print status, exit nonzero on any failure.

    Each check is a DoctorCheck or a tuple (name, check_fn[, hint]).
    Returns the exit code (0 = all pass).
    """
    normalized: list[DoctorCheck] = []
    for item in checks:
        if isinstance(item, DoctorCheck):
            normalized.append(item)
        else:
            name = item[0]
            fn = item[1]
            hint = item[2] if len(item) > 2 else None
            normalized.append(DoctorCheck(name=name, check=fn, hint=hint))

    failures = 0
    width = max((len(c.name) for c in normalized), default=0)
    for c in normalized:
        try:
            ok = bool(c.check())
        except Exception as e:
            ok = False
            err_hint = f"{c.hint or ''} ({e})".strip()
        else:
            err_hint = c.hint or ""
        mark = "PASS" if ok else "FAIL"
        line = f"  [{mark}] {c.name.ljust(width)}"
        if not ok and err_hint:
            line += f"  — {err_hint}"
        print(line, file=sys.stderr)
        if not ok:
            failures += 1

    if failures:
        print(f"\ndoctor: {failures} check(s) failed", file=sys.stderr)
        if exit_on_fail:
            sys.exit(1)
        return 1
    print("\ndoctor: all checks passed", file=sys.stderr)
    return 0


# ---------- stdin / file ----------

def read_stdin_or_file(arg: str) -> str:
    """Return the contents of `arg`, treating "-" as stdin.

    Raises FileNotFoundError if a real path is given and doesn't exist.
    """
    if arg == "-":
        return sys.stdin.read()
    with open(arg, "r", encoding="utf-8") as f:
        return f.read()


# ---------- mutation gate ----------

class MutationAborted(SystemExit):
    """Raised (via SystemExit) when the user declines a mutation prompt."""


def confirm_or_abort(
    prompt: str,
    *,
    dry_run: bool = False,
    yes: bool = False,
    force: bool = False,
    destructive: bool = False,
    preview: Optional[str] = None,
    cost_estimate: Optional[str] = None,
) -> bool:
    """Gate a mutation.

    - dry_run=True: print the preview + intended action to stderr, return False
      (caller should NOT execute).
    - yes=True: bypass interactive prompt, return True (execute).
    - destructive=True: refuse to run without force=True even when yes=True.
    - Otherwise: print prompt (+ optional cost), read y/N from stdin.

    Returns True when the caller should proceed.
    """
    if preview:
        print(f"[preview]\n{preview}", file=sys.stderr)
    if cost_estimate:
        print(f"[cost] {cost_estimate}", file=sys.stderr)

    if dry_run:
        print(f"[dry-run] would: {prompt}", file=sys.stderr)
        return False

    if destructive and not force:
        print(
            f"[refused] {prompt} — destructive op requires --force",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if yes:
        return True

    # interactive
    if not is_tty():
        print(
            f"[refused] {prompt} — non-interactive shell; pass --yes to confirm",
            file=sys.stderr,
        )
        raise SystemExit(2)
    try:
        reply = input(f"{prompt} [y/N] ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n[aborted]", file=sys.stderr)
        raise SystemExit(130)
    if reply not in {"y", "yes"}:
        print("[aborted]", file=sys.stderr)
        raise SystemExit(130)
    return True


# ---------- output ----------

def emit_json(
    *,
    status: str = "ok",
    command: str,
    data: Any = None,
    error: Optional[str] = None,
) -> None:
    """Write a {status, command, data} envelope to stdout.

    Canonical shape lifted from phantom-loom. No ANSI, no indent by default
    (agents parse, humans pipe to `jq`).
    """
    payload: dict[str, Any] = {"status": status, "command": command}
    if data is not None:
        payload["data"] = data
    if error is not None:
        payload["error"] = error
    sys.stdout.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
    sys.stdout.flush()


def emit_path(path: str | os.PathLike, label: Optional[str] = None) -> None:
    """Echo a file path to STDERR so stdout stays parseable.

    When --json is set, stdout carries the envelope; path goes to stderr.
    """
    prefix = f"{label}: " if label else "wrote: "
    print(f"{prefix}{os.fspath(path)}", file=sys.stderr)
