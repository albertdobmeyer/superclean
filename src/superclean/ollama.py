"""Ollama-aware idle model unload, to reclaim VRAM without breaking active use.

Ported from the PowerShell backend (core/ollama.ps1), stdlib only (urllib).
Conservative by design: only models with no keep-alive expiry (orphaned loads)
are unloaded. A model with a live expiry was recently used and is left alone.
If the daemon is not running, every call is a no-op, never an error.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit

_DEFAULT_PORT = 11434
_TIMEOUT = 2.0


def base_url() -> str:
    """Ollama endpoint from OLLAMA_HOST (bare host, host:port, or full URL)."""
    host = (os.environ.get("OLLAMA_HOST") or "").strip().rstrip("/")
    if not host:
        return f"http://localhost:{_DEFAULT_PORT}"
    if "://" not in host:
        host = "http://" + host
    parts = urlsplit(host)
    netloc = parts.netloc
    if ":" not in netloc:
        netloc = f"{netloc}:{_DEFAULT_PORT}"
    return f"{parts.scheme}://{netloc}"


def _get(path: str):
    try:
        with urllib.request.urlopen(base_url() + path, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def _post(path: str, payload: dict) -> bool:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url() + path, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def is_running() -> bool:
    return _get("/api/tags") is not None


def _parse_expiry(value: str | None) -> datetime | None:
    """Return a tz-aware datetime, or None for 'no expiry' / unparseable."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.year < 2000:  # Ollama uses a zero date to mean "no expiry"
        return None
    return dt


def loaded_models() -> list[dict]:
    """[{name, size_bytes, expires_at}] for currently loaded models."""
    data = _get("/api/ps")
    if not data or "models" not in data:
        return []
    out = []
    for m in data["models"]:
        out.append(
            {
                "name": m.get("name", "?"),
                "size_bytes": int(m.get("size", 0)) + int(m.get("size_vram", 0)),
                "expires_at": _parse_expiry(m.get("expires_at")),
            }
        )
    return out


def idle_unload(ctx) -> dict:
    """Unload only orphaned (no-expiry) model loads. Honors dry-run."""
    if not is_running():
        ctx.log("  Ollama daemon not running. Skipping.", "SKIP")
        return {"unloaded": 0, "reclaimed_bytes": 0}

    models = loaded_models()
    if not models:
        ctx.log("  No Ollama models loaded.", "OK")
        return {"unloaded": 0, "reclaimed_bytes": 0}

    unloaded = 0
    reclaimed = 0
    now = datetime.now(timezone.utc)
    for m in models:
        if m["expires_at"] is not None:
            mins = (m["expires_at"] - now).total_seconds() / 60
            ctx.log(
                f"  {m['name']}: keep-alive {mins:.0f} min from now, likely active. Skipping.",
                "SKIP",
            )
            continue
        # No expiry: orphaned load, safe to unload.
        from superclean.util import friendly_size

        if ctx.dry_run:
            ctx.log(
                f"  [DRY] Would unload {m['name']} (~{friendly_size(m['size_bytes'])}, no expiry).",
                "DRY",
            )
            unloaded += 1
            reclaimed += m["size_bytes"]
            continue
        if _post("/api/generate", {"model": m["name"], "keep_alive": 0}):
            ctx.log(f"  Unloaded {m['name']} (~{friendly_size(m['size_bytes'])}).", "OK")
            unloaded += 1
            reclaimed += m["size_bytes"]
        else:
            ctx.log(f"  Failed to unload {m['name']}.", "WARN")

    return {"unloaded": unloaded, "reclaimed_bytes": reclaimed}
