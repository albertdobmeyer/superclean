# levels/clean.ps1 - Standard maintenance: cache purges, idle Ollama unload, weekly-cleanup logic

function Invoke-LevelClean {
    param(
        [hashtable]$ProtectedPids,
        [switch]$DryRun,
        [switch]$Yes
    )

    Invoke-LevelBrush -ProtectedPids $ProtectedPids -DryRun:$DryRun -Yes:$Yes

    Write-Section 'LEVEL: --clean (additive on top of --brush)'

    # 1. pip cache purge across all discovered Pythons
    Write-Log ''
    Write-Log '== pip cache purge (all Pythons) ==' 'HEAD'
    $pythons = Get-InstalledPythons
    if ($pythons.Count -eq 0) {
        Write-Log '  No Python interpreters found. Skip.' 'SKIP'
    }
    foreach ($py in $pythons) {
        if (Test-Path -LiteralPath $py) {
            if ($DryRun) {
                Write-Log "  [DRY] Would run: $py -m pip cache purge" 'DRY'
            } else {
                Write-Log "  $py -m pip cache purge"
                & $py -m pip cache purge 2>&1 | Out-Null
            }
        }
    }
    Write-Log '  pip purge complete.' 'OK'

    # 2. npm cache clean
    Write-Log ''
    Write-Log '== npm cache clean ==' 'HEAD'
    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
    if ($npmCmd) {
        if ($DryRun) {
            Write-Log '  [DRY] Would run: npm cache clean --force' 'DRY'
        } else {
            & npm cache clean --force 2>&1 | Out-Null
            Write-Log '  npm cache cleaned.' 'OK'
        }
    } else { Write-Log '  npm not on PATH. Skip.' 'SKIP' }

    # 3. uv cache clean
    Write-Log ''
    Write-Log '== uv cache clean (if present) ==' 'HEAD'
    $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($uvCmd) {
        if ($DryRun) {
            Write-Log '  [DRY] Would run: uv cache clean' 'DRY'
        } else {
            & uv cache clean 2>&1 | Out-Null
            Write-Log '  uv cache cleaned.' 'OK'
        }
    } else { Write-Log '  uv not on PATH. Skip.' 'SKIP' }

    # 4. pnpm store prune
    Write-Log ''
    Write-Log '== pnpm store prune (if present) ==' 'HEAD'
    $pnpmCmd = Get-Command pnpm -ErrorAction SilentlyContinue
    if ($pnpmCmd) {
        if ($DryRun) {
            Write-Log '  [DRY] Would run: pnpm store prune' 'DRY'
        } else {
            & pnpm store prune 2>&1 | Out-Null
            Write-Log '  pnpm store pruned.' 'OK'
        }
    } else { Write-Log '  pnpm not on PATH. Skip.' 'SKIP' }

    # 5. Idle Ollama unload
    Write-Log ''
    Write-Log '== Idle Ollama model unload ==' 'HEAD'
    Invoke-OllamaIdleUnload -DryRun:$DryRun | Out-Null

    # 6. Prune superclean's own logs >14 days
    Write-Log ''
    Write-Log '== superclean logs older than 14 days ==' 'HEAD'
    $logDir = Get-SupercleanDataDir
    $cutoffLogs = (Get-Date).AddDays(-14)
    $logBytes = 0L
    $logCount = 0
    if (Test-Path $logDir) {
        Get-ChildItem -Path $logDir -File -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -lt $cutoffLogs -and $_.Name -notlike 'superclean.lock' } |
            ForEach-Object {
                $sz = $_.Length
                if ($DryRun) { $logBytes += $sz; $logCount++ }
                else {
                    try { Remove-Item -LiteralPath $_.FullName -Force; $logBytes += $sz; $logCount++ } catch {}
                }
            }
    }
    Write-Log ("  Log files removed: {0}  ({1})" -f $logCount, (Get-FriendlySize $logBytes)) 'OK'

    # 7. $env:TEMP older than 7 days
    Write-Log ''
    Write-Log '== $env:TEMP older than 7 days ==' 'HEAD'
    $cutoff7 = (Get-Date).AddDays(-7)
    $tBytes = 0L; $tCount = 0; $tSkip = 0
    Get-ChildItem -Path $env:TEMP -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoff7 } | ForEach-Object {
            $sz = $_.Length
            if ($DryRun) { $tBytes += $sz; $tCount++ }
            else {
                try { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop; $tBytes += $sz; $tCount++ }
                catch { $tSkip++ }
            }
        }
    Write-Log ("  Files: {0}  Reclaimed: {1}  Skipped: {2}" -f $tCount, (Get-FriendlySize $tBytes), $tSkip) 'OK'

    # 8. Recycle Bin full empty (now, not just >7d)
    Write-Log ''
    Write-Log '== Recycle Bin (full empty) ==' 'HEAD'
    if ($DryRun) {
        Write-Log '  [DRY] Would empty Recycle Bin completely.' 'DRY'
    } else {
        try {
            Clear-RecycleBin -Force -ErrorAction Stop
            Write-Log '  Recycle Bin emptied.' 'OK'
        } catch {
            Write-Log ("  Recycle Bin empty failed or already empty: {0}" -f $_.Exception.Message) 'INFO'
        }
    }

    # 9. Optional: user-defined output folders (targets.conf), prompt unless --yes
    Write-Log ''
    Write-Log '== Optional: user-defined output folders (targets.conf) ==' 'HEAD'
    # Each targets.conf line: path|days|label  (e.g. F:\renders|30|My renders)
    $optTargets = @()
    foreach ($line in (Read-ConfLines -Path (Get-ConfPath 'targets.conf'))) {
        $parts = $line -split '\|'
        if ($parts.Count -ge 1 -and $parts[0].Trim()) {
            $days = if ($parts.Count -ge 2 -and ($parts[1].Trim() -as [int])) { [int]$parts[1].Trim() } else { 30 }
            $label = if ($parts.Count -ge 3 -and $parts[2].Trim()) { $parts[2].Trim() } else { $parts[0].Trim() }
            $optTargets += @{ Path = $parts[0].Trim(); Days = $days; Name = $label }
        }
    }
    if ($optTargets.Count -eq 0) {
        Write-Log '  None configured (see targets.conf). Skip.' 'SKIP'
    }
    foreach ($tgt in $optTargets) {
        if (-not (Test-Path -LiteralPath $tgt.Path)) {
            Write-Log ("  {0}: not found, skip." -f $tgt.Name) 'SKIP'
            continue
        }
        $cutoff30 = (Get-Date).AddDays(-$tgt.Days)
        $files = Get-ChildItem -Path $tgt.Path -File -Recurse -Force -ErrorAction SilentlyContinue |
                 Where-Object { $_.LastWriteTime -lt $cutoff30 }
        $total = ($files | Measure-Object -Property Length -Sum).Sum
        $cnt = ($files | Measure-Object).Count
        if ($cnt -eq 0) {
            Write-Log ("  {0}: nothing to clean." -f $tgt.Name) 'OK'
            continue
        }
        $do = $false
        if ($Yes) { $do = $true }
        else { $do = Confirm-YesNo -Question ("  Delete {0} files in {1} ({2})?" -f $cnt, $tgt.Name, (Get-FriendlySize $total)) -DefaultNo }

        if ($do) {
            if ($DryRun) {
                Write-Log ("  [DRY] Would delete {0} files ({1})." -f $cnt, (Get-FriendlySize $total)) 'DRY'
            } else {
                $files | ForEach-Object { try { Remove-Item -LiteralPath $_.FullName -Force } catch {} }
                Write-Log ("  Deleted {0} files ({1})." -f $cnt, (Get-FriendlySize $total)) 'OK'
            }
        } else {
            Write-Log "  Skipped." 'SKIP'
        }
    }
}
