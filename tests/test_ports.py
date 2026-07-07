"""Listening-port discovery: LISTEN-only, deduped, owner-attributed."""
from __future__ import annotations

from collections import namedtuple

import psutil

from superclean import ports

Conn = namedtuple("Conn", ["fd", "family", "type", "laddr", "raddr", "status", "pid"])
Addr = namedtuple("Addr", ["ip", "port"])


def _conns():
    return [
        Conn(1, 2, 1, Addr("0.0.0.0", 3000), (), psutil.CONN_LISTEN, 10),
        Conn(2, 2, 1, Addr("::", 3000), (), psutil.CONN_LISTEN, 10),  # dual-stack dup
        Conn(3, 2, 1, Addr("127.0.0.1", 5432), ("1.2.3.4", 55), "ESTABLISHED", 11),
        Conn(4, 2, 1, Addr("0.0.0.0", 8080), (), psutil.CONN_LISTEN, None),  # owner hidden
    ]


def test_listen_only_dedup_and_attribution(monkeypatch):
    monkeypatch.setattr(ports.psutil, "net_connections", lambda kind="tcp": _conns())
    procs = {10: {"name": "node"}, 11: {"name": "postgres"}}
    out = ports.listening_ports(procs, protected={11})
    assert [p["port"] for p in out] == [3000, 8080]  # 5432 not LISTEN; 3000 deduped
    node = out[0]
    assert node["pid"] == 10 and node["name"] == "node" and node["protected"] is False
    hidden = out[1]
    assert hidden["pid"] is None and hidden["name"] is None and hidden["protected"] is None


def test_protected_owner_marked(monkeypatch):
    conns = [Conn(1, 2, 1, Addr("127.0.0.1", 11434), (), psutil.CONN_LISTEN, 42)]
    monkeypatch.setattr(ports.psutil, "net_connections", lambda kind="tcp": conns)
    out = ports.listening_ports({42: {"name": "ollama"}}, protected={42})
    assert out[0]["protected"] is True


def test_access_denied_degrades_to_empty(monkeypatch):
    def boom(kind="tcp"):
        raise psutil.AccessDenied(pid=1)

    monkeypatch.setattr(ports.psutil, "net_connections", boom)
    assert ports.listening_ports({}, protected=set()) == []
