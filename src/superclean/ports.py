"""Listening TCP ports and the processes that own them. Report-only.

Agentic dev leaves orphaned dev servers holding ports; this section makes
them visible. Owners come from the shared process snapshot; where the OS
hides a socket's owner (other users' processes without privileges), the
entry is kept with pid/name/protected set to None. Fail-quiet: any probe
error degrades to an empty list, never an exception.
"""

from __future__ import annotations

import psutil


def listening_ports(procs: "dict[int, dict]", protected: "set[int]") -> list[dict]:
    """[{port, ip, pid, name, protected}] for LISTEN TCP sockets.

    Deduped by (port, pid) so dual-stack listeners show once; sorted by port.
    """
    try:
        conns = psutil.net_connections(kind="tcp")
    except (psutil.Error, OSError):
        return []
    seen = set()
    out = []
    for c in conns:
        if c.status != psutil.CONN_LISTEN or not c.laddr:
            continue
        key = (c.laddr.port, c.pid)
        if key in seen:
            continue
        seen.add(key)
        info = procs.get(c.pid) if c.pid is not None else None
        out.append(
            {
                "port": c.laddr.port,
                "ip": c.laddr.ip,
                "pid": c.pid,
                "name": info.get("name") if info else None,
                "protected": (c.pid in protected) if c.pid is not None else None,
            }
        )
    out.sort(key=lambda p: (p["port"], str(p["ip"])))
    return out
