"""Platform detection and dispatch.

On Windows, tiers delegate to the bundled PowerShell deep-clean backend. On
macOS/Linux, tiers run the portable universal engine. The read-only `report`
and `protected` commands always use the cross-platform Python implementation.
"""

from __future__ import annotations

import sys

from superclean.backends import posix as _posix
from superclean.backends import windows as _windows


def is_windows() -> bool:
    return sys.platform == "win32"


def run_tier(ctx, tier: str) -> dict:
    if is_windows():
        return _windows.run_tier(ctx, tier)
    return _posix.run_tier(ctx, tier)


def run_ram(ctx) -> dict:
    if is_windows():
        return _windows.run_tier(ctx, "ram")
    return _posix.run_ram(ctx)
