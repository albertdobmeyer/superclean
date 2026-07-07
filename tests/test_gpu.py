"""GPU/VRAM discovery: nvidia-smi parsing, AMD sysfs, silent absence."""
from __future__ import annotations

import subprocess

from superclean import gpu


def test_nvidia_parse(monkeypatch):
    monkeypatch.setattr(gpu.shutil, "which", lambda exe: "/usr/bin/nvidia-smi")

    def fake_run(*a, **k):
        return subprocess.CompletedProcess(
            a[0], returncode=0,
            stdout="NVIDIA GeForce RTX 3060, 1024, 12288\n", stderr="")

    monkeypatch.setattr(gpu.subprocess, "run", fake_run)
    out = gpu._nvidia()
    assert out == [{
        "name": "NVIDIA GeForce RTX 3060",
        "vram_used": 1024 * 1024 * 1024,
        "vram_total": 12288 * 1024 * 1024,
        "source": "nvidia-smi",
    }]


def test_nvidia_absent(monkeypatch):
    monkeypatch.setattr(gpu.shutil, "which", lambda exe: None)
    assert gpu._nvidia() == []


def test_amd_sysfs(tmp_path):
    dev = tmp_path / "card0" / "device"
    dev.mkdir(parents=True)
    (dev / "mem_info_vram_used").write_text("536870912\n")
    (dev / "mem_info_vram_total").write_text("4294967296\n")
    (dev / "uevent").write_text("DRIVER=amdgpu\nPCI_ID=1002:9874\n")
    # connector dir must not double-count
    (tmp_path / "card0-DP-1").mkdir()
    out = gpu._amd_sysfs(root=tmp_path)
    assert out == [{
        "name": "card0 (amdgpu)",
        "vram_used": 536870912,
        "vram_total": 4294967296,
        "source": "sysfs",
    }]


def test_gpus_prefers_nvidia(monkeypatch):
    nv = [{"name": "n", "vram_used": 1, "vram_total": 2, "source": "nvidia-smi"}]
    monkeypatch.setattr(gpu, "_nvidia", lambda: nv)
    monkeypatch.setattr(gpu, "_amd_sysfs", lambda root=None: [{"name": "amd"}])
    assert gpu.gpus() == nv


def test_gpus_empty_when_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(gpu, "_nvidia", lambda: [])
    monkeypatch.setattr(gpu, "_amd_sysfs", lambda root=None: [])
    assert gpu.gpus() == []
