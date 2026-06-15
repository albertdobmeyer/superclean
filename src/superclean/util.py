"""Shared helpers: sizes, the per-user data dir, logging, color, run context."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ANSI colors, keyed by log level. Disabled when not a TTY or --no-color.
_COLORS = {
    "ERROR": "\033[31m",
    "WARN": "\033[33m",
    "OK": "\033[32m",
    "DRY": "\033[36m",
    "SKIP": "\033[90m",
    "HEAD": "\033[36m",
}
_RESET = "\033[0m"


def friendly_size(num_bytes: int) -> str:
    """Human-readable byte size, matching the PowerShell backend's format."""
    n = float(num_bytes)
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.2f} KB"
    return f"{int(n)} B"


def data_dir() -> Path:
    """Per-user data directory for logs and the lockfile. Created on demand."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    d = Path(base) / "superclean"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class RunContext:
    """Carries flags + presentation state through a single run."""

    dry_run: bool = False
    yes: bool = False
    i_know: bool = False
    quiet: bool = False
    json: bool = False
    no_color: bool = False
    force_unlock: bool = False
    log_path: Path | None = None
    _color: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self._color = (
            not self.no_color
            and not self.json
            and sys.stdout.isatty()
            and os.environ.get("NO_COLOR") is None
        )
        if self.log_path is None:
            today = datetime.now().strftime("%Y-%m-%d")
            self.log_path = data_dir() / f"superclean-{today}.log"

    def log(self, message: str = "", level: str = "INFO") -> None:
        """Print to console (unless quiet/json) and always append to the log file."""
        if not self.quiet and not self.json:
            # flush so our lines stay ordered relative to subprocess (PS) output.
            if self._color and level in _COLORS:
                print(f"{_COLORS[level]}{message}{_RESET}", flush=True)
            else:
                print(message, flush=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(f"[{ts}] [{level}] {message}\n")
        except OSError:
            pass

    def section(self, title: str) -> None:
        bar = "=" * 60
        self.log(bar, "HEAD")
        self.log(title, "HEAD")
        self.log(bar, "HEAD")

    def confirm(self, question: str, default_no: bool = True) -> bool:
        """Yes/No prompt. Honors --yes; returns False in quiet/json mode."""
        if self.yes:
            return True
        if self.quiet or self.json:
            return False
        suffix = "[y/N]" if default_no else "[Y/n]"
        try:
            resp = input(f"{question} {suffix} ").strip().lower()
        except EOFError:
            return False
        if not resp:
            return not default_no
        return resp == "y"
