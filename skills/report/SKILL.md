---
name: report
description: Diagnose what is eating this machine - orphaned dev servers, models pinned in VRAM, stuck ports, bloated package caches, filling disks. Read-only, changes nothing. Use when the machine feels slow, the GPU is full, a port is already in use, the disk is filling up, or the user asks what is consuming their resources.
allowed-tools: ["Bash"]
---

# superclean report

Diagnose the machine. **This is read-only. Do not clean anything from this skill.**

## Run it

```bash
uvx superclean-cli report --json
```

`uvx` needs no install. If `uv` is missing, fall back to `superclean report --json`, and
if that is also missing tell the user they can install it with `pipx install superclean-cli`.

This is safe to run from inside Claude Code. superclean's perimeter protects editors,
terminals, shells, the Ollama daemon, AI coding tools, every descendant of those, and its
own entire ancestor chain, so it cannot kill the session running it. `report` does not
kill anything regardless.

## Interpret it

Read the JSON and tell the user what is actually wrong, in prose. Do not dump the JSON at
them. Walk the fields and report only what is notable:

- `orphans` - dev servers (node, vite, esbuild, python) whose parent is dead. Each entry
  has `rss`, so give the total RAM they are holding and name the worst offenders. On
  Windows these accumulate because closing an editor does not kill its children.
- `ollama_models` - models currently resident in VRAM. If one is loaded with no work in
  flight, that is gigabytes sitting idle. A model pinned with `keep_alive: -1` never
  expires on its own.
- `gpus` - VRAM used versus total. Cross-reference with `ollama_models` to explain it.
- `ports` - listening TCP ports and their owning process. Ports held by orphaned servers
  are flagged; this is what "address already in use" actually means.
- `memory` - system RAM.
- `drives` - free space. Flag anything tight.
- `service_health` - whether expected services are up.
- `protected_count` - how many processes superclean is shielding. Worth a mention, since
  it is the number a naive `pkill` would have destroyed.

## Then

State the total reclaimable, and stop. If there is nothing worth cleaning, say so plainly
rather than manufacturing a recommendation.

If cleanup is warranted, tell the user to run `/superclean:clean` and say which tier you
would pick and why. Do not run it for them from this skill.
