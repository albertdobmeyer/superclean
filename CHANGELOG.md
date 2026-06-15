# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-06-15

First public release.

### Added
- Tiered cleanup levels: `--report`, `--dust`, `--brush`, `--clean`, `--wipe`, `--nuke` (additive).
- Standalone modes: `--ram`, `--gpu-reset`, `--last`, `--list-protected`.
- Modifiers: `--dry-run`, `--yes`, `--i-know`, `--quiet`, `--log`, `--no-color`, `--force-unlock`.
- Protected-process perimeter for editors, terminals, and AI tooling, including
  descendant and ancestor process trees, with `protect.conf` for custom names.
- Smart orphan detection for dead-parent dev servers (node, vite, esbuild, and more).
- RAM/VRAM relief: standby-list flush, working-set trim, idle Ollama model unload.
- Optional config-driven cleanup (`targets.conf`) and health checks (`services.conf`).
- Per-run logging to `%LOCALAPPDATA%\superclean`.
