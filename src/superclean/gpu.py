"""GPU/VRAM visibility: nvidia-smi when present, AMD sysfs otherwise.

Report-only and fail-quiet: machines without a discoverable GPU produce an
empty list, never an error. NVIDIA is preferred when nvidia-smi exists
because it also covers used-vs-total; AMD/integrated GPUs are read from
/sys/class/drm (amdgpu exposes mem_info_vram_used/_total).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_SMI_ARGS = ["--query-gpu=name,memory.used,memory.total", "--format=csv,noheader,nounits"]


def _nvidia() -> list[dict]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        proc = subprocess.run(
            [exe, *_SMI_ARGS], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    out = []
    for line in (proc.stdout or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3:
            continue
        try:
            used_mb, total_mb = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        out.append(
            {
                "name": parts[0],
                "vram_used": used_mb * 1024 * 1024,
                "vram_total": total_mb * 1024 * 1024,
                "source": "nvidia-smi",
            }
        )
    return out


def _amd_sysfs(root: Path = Path("/sys/class/drm")) -> list[dict]:
    out: list[dict] = []
    if not root.exists():
        return out
    for card in sorted(root.glob("card[0-9]*")):
        dev = card / "device"
        used_f = dev / "mem_info_vram_used"
        total_f = dev / "mem_info_vram_total"
        if not used_f.exists() or not total_f.exists():
            continue  # connector dirs (card0-DP-1) and non-amdgpu cards land here
        try:
            used = int(used_f.read_text().strip())
            total = int(total_f.read_text().strip())
        except (OSError, ValueError):
            continue
        name = card.name
        try:
            for ln in (dev / "uevent").read_text().splitlines():
                if ln.startswith("DRIVER="):
                    name = f"{card.name} ({ln.split('=', 1)[1]})"
                    break
        except OSError:
            pass
        out.append({"name": name, "vram_used": used, "vram_total": total, "source": "sysfs"})
    return out


def gpus() -> list[dict]:
    """[{name, vram_used, vram_total, source}]; empty when nothing discoverable."""
    found = _nvidia()
    if found:
        return found
    return _amd_sysfs()
