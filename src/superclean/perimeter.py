"""The safety perimeter: the set of PIDs superclean must never kill.

Ported from the PowerShell backend (core/protect.ps1), with the same four
pillars and a fail-closed posture: anything we cannot classify is treated as
protected, never as a target.

  Pillar 1  process whose name matches the protected baseline or protect.conf
  Pillar 2  any process whose command line shows it belongs to an AI agent or
            to superclean's own launcher (claude/opencode/mcp, uvx/pipx)
  Pillar 3  every descendant of an already-protected process
  Pillar 4  the running superclean process and its entire ancestor chain
"""

from __future__ import annotations

import os
import re

import psutil

# Lowercased, no .exe. Generous on purpose: over-protecting is safe, under-
# protecting is not. Note that "node"/"python" are deliberately ABSENT here
# (they are orphan candidates) and earn protection only via pillars 2-4.
BASELINE_NAMES = {
    # editors and IDEs
    "cursor", "code", "code - insiders", "codium", "antigravity", "windsurf",
    "zed", "subl", "sublime_text", "goland", "rider", "pycharm", "pycharm64",
    "webstorm", "idea", "idea64", "clion", "fleet",
    "nvim", "vim", "emacs", "nano", "micro", "hx", "helix",
    # AI coding tools
    "claude", "opencode", "aider", "cody", "continue",
    # terminals and multiplexers
    "windowsterminal", "wt", "alacritty", "kitty", "wezterm", "wezterm-gui",
    "iterm2", "iterm", "warp", "ghostty", "gnome-terminal", "konsole",
    "tmux", "zellij", "screen", "terminal",
    # shells (an interactive shell is a live tool, not garbage)
    "pwsh", "powershell", "cmd", "bash", "zsh", "fish", "nu",
    # local model daemon and container CLI
    "ollama", "ollama_llama_server", "ollamaapp", "docker", "dockerd",
    # superclean's own launchers: never flag ourselves
    "uv", "uvx", "pipx", "superclean",
}

# Command-line signatures that protect a process regardless of its exe name.
_AGENT_RE = re.compile(r"(?i)claude|opencode|@anthropic|@modelcontextprotocol")
_LAUNCHER_RE = re.compile(r"(?i)\b(uvx|pipx|superclean)\b")

_MAX_ANCESTOR_DEPTH = 20


def _norm(name: str | None) -> str:
    if not name:
        return ""
    return name.lower().removesuffix(".exe")


def all_protected_names(extra_names: list[str] | None = None) -> list[str]:
    from superclean import config

    names = set(BASELINE_NAMES) | set(config.protect_names())
    if extra_names:
        names |= {_norm(n) for n in extra_names}
    return sorted(names)


def _snapshot() -> dict[int, dict]:
    """One pass over all processes. Returns pid -> info dict (fail-tolerant)."""
    procs: dict[int, dict] = {}
    for p in psutil.process_iter(["pid", "name", "ppid", "cmdline", "create_time"]):
        try:
            procs[p.info["pid"]] = p.info
        except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
            continue
    return procs


def build_protected_pids(extra_names: list[str] | None = None) -> set[int]:
    """Compute the full protected-PID set. Fail-closed on any error."""
    names = set(all_protected_names(extra_names))
    procs = _snapshot()
    protected: set[int] = set()

    # Pillar 1: name match.
    for pid, info in procs.items():
        if _norm(info.get("name")) in names:
            protected.add(pid)

    # Pillar 2: command-line signatures (agent processes, our own launcher).
    for pid, info in procs.items():
        cmdline = " ".join(info.get("cmdline") or [])
        if not cmdline:
            continue
        name = _norm(info.get("name"))
        if name in ("node", "node.exe") and _AGENT_RE.search(cmdline):
            protected.add(pid)
        elif _LAUNCHER_RE.search(cmdline):
            protected.add(pid)

    # Pillar 3: descendants of every protected process (BFS over ppid map).
    children: dict[int, list[int]] = {}
    for pid, info in procs.items():
        ppid = info.get("ppid")
        if ppid is not None:
            children.setdefault(ppid, []).append(pid)
    queue = list(protected)
    while queue:
        parent = queue.pop()
        for child in children.get(parent, ()):
            if child not in protected:
                protected.add(child)
                queue.append(child)

    # Pillar 4: ourselves and our full ancestor chain (the uvx/python that runs
    # this code, the shell, the terminal). Critical so we never self-flag.
    me = os.getpid()
    protected.add(me)
    try:
        cur = psutil.Process(me)
        for _ in range(_MAX_ANCESTOR_DEPTH):
            parent = cur.parent()
            if parent is None or parent.pid in protected:
                if parent is not None:
                    protected.add(parent.pid)
                break
            protected.add(parent.pid)
            cur = parent
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    return protected


def running_protected_summary(extra_names: list[str] | None = None) -> dict[str, list[int]]:
    """name -> [pids] for protected names that are currently running."""
    names = set(all_protected_names(extra_names))
    summary: dict[str, list[int]] = {}
    for p in psutil.process_iter(["pid", "name"]):
        try:
            nm = _norm(p.info.get("name"))
        except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
            continue
        if nm in names:
            summary.setdefault(nm, []).append(p.info["pid"])
    return summary
