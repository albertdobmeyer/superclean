# Contributing

Thanks for your interest in superclean.

## Ground rules

- **Safety first.** Anything that deletes files or stops processes must honor
  `--dry-run`, respect the protected-process perimeter, and fail closed (skip,
  do not guess) when it is unsure. New destructive behavior belongs behind a
  prompt or an explicit flag.
- **No hardcoded machine-specific paths.** Use `$env:LOCALAPPDATA`,
  `$env:APPDATA`, discovery globs, or a config file. Personal setup goes in
  `targets.conf` / `services.conf`, never in the core scripts.
- **No em dashes in any source, comment, or doc.** Use a hyphen.

## Project layout

```
superclean.ps1     entry point: arg parsing, dispatch, logging, lockfile
core/              shared utilities, protected-process logic, memory, ollama, report
levels/            one file per cleanup level (dust, brush, clean, wipe, nuke)
*.conf             optional user configuration
```

## Before you open a PR

1. Parse-check every script:
   ```powershell
   Get-ChildItem -Recurse -Filter *.ps1 | ForEach-Object {
     $e=$null; [System.Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$null,[ref]$e) | Out-Null
     if ($e.Count) { Write-Host "FAIL $($_.Name)"; $e }
   }
   ```
2. Run `superclean --report` and the level you changed with `--dry-run`.
3. Confirm no new hardcoded user paths: a search for `C:\Users\` should come back empty.

Open an issue first for anything large so we can agree on the approach.
