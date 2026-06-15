# Contributing

Thanks for your interest in superclean.

## Ground rules

- **Safety first.** Anything that deletes files or stops processes must honor
  `--dry-run`, respect the protected-process perimeter, and fail closed (skip,
  do not guess) when it is unsure. New destructive behavior belongs behind a
  prompt or an explicit flag.
- **No hardcoded machine-specific paths.** Use environment variables, discovery,
  or a config file. Personal setup goes in `targets.conf` / `services.conf`,
  never in the core.
- **No em dashes in any source, comment, or doc.** Use a hyphen.

## Project layout

```
src/superclean/    portable Python core (cross-platform)
  cli.py           argparse surface, tier dispatch, lockfile, exit codes, --json
  perimeter.py     the safety perimeter (psutil)
  orphans.py       orphan detection + kill with re-validation
  caches.py        package-manager cache purge
  ollama.py        idle model unload
  tempprune.py     temp + targets.conf age-out
  report.py        read-only diagnostic
  config.py        shared conf discovery + parsers
  backends/        windows.py (PowerShell passthrough), posix.py (universal engine)
windows/           the PowerShell deep-clean backend (Windows depth)
  superclean.ps1   core/  levels/ (dust, sweep, scrub, wipe, nuke)
*.conf             optional user configuration (shared by both runtimes)
```

The portable core runs everywhere. On Windows, tiers delegate to the PowerShell
backend; on macOS/Linux they run the Python universal engine.

## Before you open a PR

1. Compile the Python: `python -m py_compile src/superclean/*.py src/superclean/backends/*.py`.
2. Parse-check the PowerShell:
   ```powershell
   Get-ChildItem windows -Recurse -Filter *.ps1 | ForEach-Object {
     $e=$null; [System.Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$null,[ref]$e) | Out-Null
     if ($e.Count) { Write-Host "FAIL $($_.Name)"; $e }
   }
   ```
3. Run `superclean report` and the tier you changed with `--dry-run`.
4. Confirm no new hardcoded user paths and no em dashes.

Open an issue first for anything large so we can agree on the approach.
