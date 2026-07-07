"""One-pass process snapshot shared by perimeter, orphans, and the report.

A single psutil sweep is expensive; before this module the report triggered
about four of them. Every consumer accepts a `procs` mapping so one snapshot
can feed the whole run. Fail-tolerant: unreadable processes are skipped and
unreadable attributes are None.
"""

from __future__ import annotations

import psutil

_ATTRS = ["pid", "name", "ppid", "cmdline", "create_time", "username", "memory_info"]


def norm(name: "str | None") -> str:
    """Lowercased process name without a trailing .exe. '' for None."""
    if not name:
        return ""
    return name.lower().removesuffix(".exe")


def snapshot() -> "dict[int, dict]":
    """pid -> info dict from a single pass over all processes."""
    procs: dict[int, dict] = {}
    for p in psutil.process_iter(_ATTRS):
        try:
            procs[p.info["pid"]] = p.info
        except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
            continue
    return procs
