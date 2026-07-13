# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's
[Report a vulnerability](https://github.com/albertdobmeyer/superclean/security/advisories/new)
form, not as a public issue. I aim to acknowledge within 72 hours and to ship a fix or a
written assessment within 14 days. If a report is valid and you would like credit, you
will get it in the advisory and the changelog.

Only the latest released version is supported. Fixes ship in a new release rather than as
patches to older ones.

| Version | Supported |
| ------- | --------- |
| 2.1.x   | yes       |
| < 2.1   | no        |

## Threat model

superclean's whole job is to kill processes and delete files. Please read this section
before you run anything above `report`, and treat any deviation from it as a bug worth
reporting.

**What it assumes.** superclean runs locally, with your privileges, on your machine, and
trusts three things: the OS, your config files, and you. It has no daemon, no server, no
listening socket, and it does not elevate. It cannot do anything to your system that your
own shell could not already do.

**Network.** The only network I/O is to a local Ollama daemon (`localhost:11434` by
default, overridable via `OLLAMA_HOST`), used to list loaded models and ask it to unload
them. There is no telemetry, no analytics, no update check, and nothing is ever sent off
the machine. The tool works fully offline; if Ollama is absent, that step is skipped.

**Privileges.** Run it as yourself. Running as root or as an elevated Administrator widens
the blast radius to processes and files you would not otherwise be able to touch, and the
safety perimeter is not designed to compensate for that.

### Guarantees

- **Read-only by default.** Bare `superclean`, plus `report`, `protected` and `last`, take
  no lock and change nothing. Every destructive tier is opt-in by name, and every one of
  them accepts `--dry-run`.
- **The perimeter is fail-closed.** Any process superclean cannot confidently classify is
  treated as protected, never as a target. It protects editors and IDEs, terminals and
  multiplexers, interactive shells, AI coding tools, the Ollama daemon, its own launcher,
  every descendant of anything protected, and its own entire ancestor chain. `node` and
  `python` are deliberately *not* protected by name, since those are the usual orphans, so
  they survive only by being descendants of something that is.
- **Kills are re-validated at kill time.** A process is re-checked against its recorded
  start time immediately before being signalled, so a PID reused between the scan and the
  kill is skipped rather than terminated.
- **One run at a time.** Mutating runs take a lock arbitrated by the operating system, so
  two runs cannot race each other into the same processes and directories.
- **Destructive tiers escalate deliberately.** `nuke` requires typing `NUKE` unless you
  pass `--i-know`.

### Non-guarantees

These are known and accepted, not oversights:

- **Your config is trusted input.** `protect.conf`, `targets.conf` and `services.conf` are
  read as instructions. Anything listed in `targets.conf` will be deleted at the tier that
  reads it. If an attacker can already write to your config directory, they can already run
  code as you, and superclean is not your problem.
- **`--force-unlock` defeats the run lock** by design. It exists to let a run proceed
  alongside another; nothing good comes of using it routinely.
- **Killing a process can lose unsaved work in it.** That is what killing a process means.
  The perimeter is what keeps that from being *your editor*, and `--dry-run` is how you
  check before it happens.
- **Deleted files are deleted.** Nothing moves to a recycle bin or a trash directory.
