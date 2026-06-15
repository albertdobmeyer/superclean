# levels/sweep.ps1 - Light maintenance, no IDE interruption
# Adds: smart orphan kill, standby flush, working-set trim, DNS/ARP, Cursor/Claude renewable caches

function Invoke-LevelSweep {
    param(
        [hashtable]$ProtectedPids,
        [switch]$DryRun,
        [switch]$Yes
    )

    # Run dust first (additive levels)
    Invoke-LevelDust -DryRun:$DryRun

    Write-Section 'LEVEL: --sweep (additive on top of --dust)'

    # 1. Standby list flush (with GPU/IO guard)
    Write-Log ''
    Write-Log '== Standby list flush ==' 'HEAD'
    Invoke-StandbyFlush -DryRun:$DryRun | Out-Null

    # 2. Working-set trim
    Write-Log ''
    Write-Log '== Working-set trim ==' 'HEAD'
    Invoke-WorkingSetTrim -ProtectedPids $ProtectedPids -DryRun:$DryRun | Out-Null

    # 3. DNS + ARP flush
    Write-Log ''
    Write-Log '== DNS + ARP flush ==' 'HEAD'
    Invoke-DnsArpFlush -DryRun:$DryRun

    # 4. Smart orphan kill
    Write-Log ''
    Write-Log '== Smart orphan dev procs ==' 'HEAD'
    $orphans = @(Find-OrphanProcs -ProtectedPids $ProtectedPids)
    Remove-OrphanProcs -Orphans $orphans -DryRun:$DryRun | Out-Null

    # 5. Cursor renewable sub-caches (lock-aware)
    Write-Log ''
    Write-Log '== Cursor renewable sub-caches ==' 'HEAD'
    $cursorTargets = @(
        'CachedData', 'Code Cache', 'Service Worker', 'WebStorage', 'Cache', 'logs'
    )
    $totalCursor = 0L
    foreach ($sub in $cursorTargets) {
        $p = Join-Path $env:APPDATA "Cursor\$sub"
        if (Test-Path -LiteralPath $p) {
            $r = Remove-DirContents -Path $p -DryRun:$DryRun
            $totalCursor += $r.DeletedBytes
            $note = if ($r.SkippedFiles -gt 0) { " (skipped $($r.SkippedFiles) locked)" } else { '' }
            Write-Log ("  {0}  {1}{2}" -f $sub, (Get-FriendlySize $r.DeletedBytes), $note)
        }
    }
    Write-Log ("  Cursor total: {0}" -f (Get-FriendlySize $totalCursor)) 'OK'

    # 6. Claude desktop sub-caches (lock-aware)
    Write-Log ''
    Write-Log '== Claude desktop sub-caches ==' 'HEAD'
    $claudeTargets = @('Cache', 'Code Cache', 'logs')
    $totalClaude = 0L
    foreach ($sub in $claudeTargets) {
        $p = Join-Path $env:APPDATA "Claude\$sub"
        if (Test-Path -LiteralPath $p) {
            $r = Remove-DirContents -Path $p -DryRun:$DryRun
            $totalClaude += $r.DeletedBytes
            $note = if ($r.SkippedFiles -gt 0) { " (skipped $($r.SkippedFiles) locked)" } else { '' }
            Write-Log ("  {0}  {1}{2}" -f $sub, (Get-FriendlySize $r.DeletedBytes), $note)
        }
    }
    Write-Log ("  Claude total: {0}" -f (Get-FriendlySize $totalClaude)) 'OK'

    # 7. WSL shutdown - only if safe
    Write-Log ''
    Write-Log '== WSL shutdown check ==' 'HEAD'
    $wsl = Get-WslState
    $dockerContainers = $false
    try {
        $cnt = & docker ps -q 2>$null
        if ($LASTEXITCODE -eq 0 -and $cnt) { $dockerContainers = $true }
    } catch {}
    if ($wsl.VmMB -le 0) {
        Write-Log '  VmmemWSL not running. Skip.' 'SKIP'
    } elseif ($wsl.InteractiveSessions -gt 0) {
        Write-Log ("  Skip: {0} interactive wsl.exe session(s) attached." -f $wsl.InteractiveSessions) 'SKIP'
    } elseif ($dockerContainers) {
        Write-Log '  Skip: Docker containers are running.' 'SKIP'
    } else {
        $doIt = $false
        if ($Yes) {
            $doIt = $true
        } else {
            $doIt = Confirm-YesNo -Question ("  VmmemWSL is using {0} MB. Shutdown WSL to reclaim?" -f $wsl.VmMB) -DefaultNo
        }
        if ($doIt) {
            if ($DryRun) {
                Write-Log "  [DRY] Would run: wsl --shutdown" 'DRY'
            } else {
                & wsl --shutdown 2>&1 | Out-Null
                Write-Log '  WSL shut down.' 'OK'
            }
        } else {
            Write-Log '  Skipped per user.' 'SKIP'
        }
    }
}
