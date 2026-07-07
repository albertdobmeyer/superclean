"""OLLAMA_HOST normalization (mirrors the ollama CLI's own rules)."""
from __future__ import annotations

from superclean.ollama import base_url


def test_default(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert base_url() == "http://localhost:11434"


def test_bare_host(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "192.168.1.50")
    assert base_url() == "http://192.168.1.50:11434"


def test_host_and_port(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "myhost:1234")
    assert base_url() == "http://myhost:1234"


def test_scheme_without_port(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "https://ollama.example.com")
    assert base_url() == "https://ollama.example.com:11434"


def test_full_url_passes_through(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:8080")
    assert base_url() == "http://127.0.0.1:8080"
