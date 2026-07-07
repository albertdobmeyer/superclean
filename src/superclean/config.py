"""Config discovery and parsing.

The same three optional files used by the PowerShell backend, shared verbatim:
  protect.conf   one process name per line (extra protected names)
  targets.conf   path|days|label   (extra folders to age out)
  services.conf  label|url         (extra health checks)

Discovery precedence: first existing dir that holds any conf file wins for conf_dir();
each FILE is then resolved independently through the same chain.
  1. SUPERCLEAN_CONF_DIR env var
  2. per-user config dir (platform-specific)
  3. bundled examples shipped in the wheel
  4. repo root (dev checkout)
"""

from __future__ import annotations

import os
from pathlib import Path

_CONF_NAMES = ("protect.conf", "targets.conf", "services.conf")


def _user_config_dir() -> Path:
    from superclean.util import user_dir

    return user_dir("config") / "superclean"


def _bundled_conf_dir() -> Path:
    # Inside the wheel: superclean/_backend/conf/
    return Path(__file__).resolve().parent / "_backend" / "conf"


def _repo_root_dir() -> Path:
    # Dev checkout: src/superclean/config.py -> repo root is three parents up.
    return Path(__file__).resolve().parents[2]


def _candidate_dirs() -> "list[Path]":
    env = os.environ.get("SUPERCLEAN_CONF_DIR")
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.extend([_user_config_dir(), _bundled_conf_dir(), _repo_root_dir()])
    return candidates


def _find_conf_file(name: str) -> "Path | None":
    """First existing instance of this conf file across the candidate chain."""
    for c in _candidate_dirs():
        if (c / name).exists():
            return c / name
    return None


def conf_dir() -> Path:
    """First candidate dir holding ANY of the three conf files (see precedence)."""
    for c in _candidate_dirs():
        if any((c / n).exists() for n in _CONF_NAMES):
            return c
    # Nothing found: prefer the per-user dir so a first run has a stable home.
    return _user_config_dir()


def export_conf_dir_env() -> None:
    """Make the chosen conf dir visible to the PowerShell backend."""
    os.environ["SUPERCLEAN_CONF_DIR"] = str(conf_dir())


def read_conf_lines(name: str) -> list[str]:
    """Non-empty, non-comment lines from a conf file. Empty list if missing.

    Each file is resolved independently, so a user dir holding only
    targets.conf still gets protect.conf/services.conf from the examples.
    """
    path = _find_conf_file(name)
    if path is None:
        return []
    out = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                out.append(line)
    except OSError:
        return []
    return out


def protect_names() -> list[str]:
    """Extra protected process names from protect.conf (lowercased, no .exe)."""
    names = []
    for line in read_conf_lines("protect.conf"):
        names.append(line.lower().removesuffix(".exe"))
    return names


def targets() -> list[tuple[str, int, str]]:
    """(path, days, label) tuples from targets.conf."""
    out = []
    for line in read_conf_lines("targets.conf"):
        parts = [p.strip() for p in line.split("|")]
        path = parts[0]
        if not path:
            continue
        days = 30
        if len(parts) >= 2 and parts[1].isdigit():
            days = int(parts[1])
        label = parts[2] if len(parts) >= 3 and parts[2] else path
        out.append((path, days, label))
    return out


def services() -> dict[str, str]:
    """label -> url from services.conf (Ollama is added by the report itself)."""
    out: dict[str, str] = {}
    for line in read_conf_lines("services.conf"):
        parts = line.split("|", 1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            out[parts[0].strip()] = parts[1].strip()
    return out


def init_user_conf() -> dict:
    """Copy the example conf files into the per-user config dir.

    Never overwrites: existing files are reported as "exists" and left
    untouched. Examples come from the bundled wheel dir, falling back to a
    dev checkout's repo root. Filesystem failures are reported, not raised.
    """
    dest = _user_config_dir()
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"dir": str(dest), "files": {}, "error": str(exc)}
    examples = (_bundled_conf_dir(), _repo_root_dir())
    files: dict = {}
    for name in _CONF_NAMES:
        target = dest / name
        if target.exists():
            files[name] = "exists"
            continue
        src = None
        for c in examples:
            if (c / name).exists():
                src = c / name
                break
        if src is None:
            files[name] = "missing-example"
            continue
        try:
            target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            files[name] = "write-failed"
            continue
        files[name] = "created"
    return {"dir": str(dest), "files": files}
