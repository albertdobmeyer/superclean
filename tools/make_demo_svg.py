#!/usr/bin/env python3
"""Render a terminal-style SVG from a small tagged text file.

Input lines may start with a one-token color tag; the rest is the text:
  @p    prompt line: a green "$" then the command in bright white
  @h    section header (cyan)
  @ok   success (green)
  @warn warning (yellow)
  @dim  muted (gray)
  (no tag) default foreground

Usage: python tools/make_demo_svg.py tools/demo.txt assets/demo.svg
"""

from __future__ import annotations

import sys
from pathlib import Path

# GitHub-dark palette
BG = "#0d1117"
BAR = "#161b22"
COLORS = {
    "default": "#c9d1d9",
    "p_dollar": "#3fb950",
    "p_cmd": "#e6edf3",
    "h": "#56d4dd",
    "ok": "#3fb950",
    "warn": "#d29922",
    "dim": "#8b949e",
    "title": "#8b949e",
}
DOTS = ["#ff5f56", "#ffbd2e", "#27c93f"]

FONT = "ui-monospace, 'Cascadia Code', 'JetBrains Mono', Menlo, Consolas, monospace"
FS = 14          # font size
LH = 21          # line height
CW = 8.4         # approx monospace char width at 14px
PAD = 18
BAR_H = 38


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def parse(line: str) -> tuple[str, str]:
    for tag in ("@p", "@h", "@ok", "@warn", "@dim"):
        if line.startswith(tag + " "):
            return tag[1:], line[len(tag) + 1 :]
        if line == tag:
            return tag[1:], ""
    return "default", line


def build(lines: list[str], title: str) -> str:
    parsed = [parse(ln) for ln in lines]
    max_chars = max((len(t) for _, t in parsed), default=40)
    max_chars = max(max_chars, len(title) + 4, 52)
    width = int(PAD * 2 + max_chars * CW)
    height = int(BAR_H + PAD + len(parsed) * LH + PAD)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{FONT}" font-size="{FS}">',
        f'<rect width="{width}" height="{height}" rx="10" fill="{BG}"/>',
        f'<rect width="{width}" height="{BAR_H}" rx="10" fill="{BAR}"/>',
        f'<rect y="{BAR_H - 10}" width="{width}" height="10" fill="{BAR}"/>',
    ]
    for i, color in enumerate(DOTS):
        out.append(f'<circle cx="{20 + i * 20}" cy="{BAR_H / 2}" r="6" fill="{color}"/>')
    out.append(
        f'<text x="{width / 2}" y="{BAR_H / 2 + 4}" text-anchor="middle" '
        f'fill="{COLORS["title"]}">{esc(title)}</text>'
    )

    y = BAR_H + PAD + FS
    for kind, text in parsed:
        x = PAD
        if kind == "p":
            # "$" in green, command in bright white
            out.append(f'<text x="{x}" y="{y}" fill="{COLORS["p_dollar"]}">$</text>')
            out.append(
                f'<text x="{x + CW * 2:.1f}" y="{y}" fill="{COLORS["p_cmd"]}">{esc(text)}</text>'
            )
        else:
            fill = COLORS.get(kind, COLORS["default"])
            if text:
                out.append(f'<text x="{x}" y="{y}" fill="{fill}" xml:space="preserve">{esc(text)}</text>')
        y += LH

    out.append("</svg>")
    return "\n".join(out)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    lines = src.read_text(encoding="utf-8").splitlines()
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(build(lines, "superclean"), encoding="utf-8")
    print(f"wrote {dst} ({dst.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
