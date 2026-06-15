# levels/wipe.ps1 - Heavy: browser caches (skip if running), Playwright bins, full Temp wipe

function Test-AppRunning {
    param([string[]]$ExeNames)
    foreach ($n in $ExeNames) {
        $p = Get-Process -Name $n -ErrorAction SilentlyContinue
        if ($p -and $p.Count -gt 0) { return $true }
    }
    return $false
}

function Clear-BrowserCache {
    param(
        [string]$BrowserName,
        [string[]]$ProcessNames,
        [string]$BasePath,
        [string[]]$SubPaths,
        [switch]$DryRun
    )
    if (Test-AppRunning -ExeNames $ProcessNames) {
        Write-Log ("  {0}: SKIP (currently running)." -f $BrowserName) 'SKIP'
        return @{ Skipped = $true; Bytes = 0L }
    }
    if (-not (Test-Path -LiteralPath $BasePath)) {
        Write-Log ("  {0}: not installed." -f $BrowserName) 'SKIP'
        return @{ Skipped = $true; Bytes = 0L }
    }
    $total = 0L
    foreach ($sub in $SubPaths) {
        $p = Join-Path $BasePath $sub
        if (Test-Path -LiteralPath $p) {
            $r = Remove-DirContents -Path $p -DryRun:$DryRun
            $total += $r.DeletedBytes
        }
    }
    Write-Log ("  {0}: {1}" -f $BrowserName, (Get-FriendlySize $total)) 'OK'
    return @{ Skipped = $false; Bytes = $total }
}

function Invoke-LevelWipe {
    param(
        [hashtable]$ProtectedPids,
        [switch]$DryRun,
        [switch]$Yes
    )

    Invoke-LevelScrub -ProtectedPids $ProtectedPids -DryRun:$DryRun -Yes:$Yes

    Write-Section 'LEVEL: --wipe (additive on top of --scrub)'

    if (-not $Yes) {
        Write-Log ''
        Write-Log 'WIPE will additionally clear browser caches (skip if browser open),'
        Write-Log 'Playwright old binaries, full $env:TEMP, and Discord/Slack caches.'
        if (-not (Confirm-YesNo -Question 'Proceed with --wipe?' -DefaultNo)) {
            Write-Log 'Wipe declined.' 'WARN'
            return $false
        }
    }

    # Browser caches
    Write-Log ''
    Write-Log '== Browser caches (skip if running) ==' 'HEAD'

    $browserSubs = @('Cache', 'Code Cache', 'GPUCache', 'Service Worker\CacheStorage')

    Clear-BrowserCache -BrowserName 'Brave' `
        -ProcessNames @('brave') `
        -BasePath (Join-Path $env:LOCALAPPDATA 'BraveSoftware\Brave-Browser\User Data\Default') `
        -SubPaths $browserSubs `
        -DryRun:$DryRun | Out-Null

    Clear-BrowserCache -BrowserName 'Chrome' `
        -ProcessNames @('chrome') `
        -BasePath (Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data\Default') `
        -SubPaths $browserSubs `
        -DryRun:$DryRun | Out-Null

    Clear-BrowserCache -BrowserName 'Edge' `
        -ProcessNames @('msedge') `
        -BasePath (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\User Data\Default') `
        -SubPaths $browserSubs `
        -DryRun:$DryRun | Out-Null

    # Playwright old browser binaries
    Write-Log ''
    Write-Log '== Playwright old browser versions ==' 'HEAD'
    $pw = Join-Path $env:LOCALAPPDATA 'ms-playwright'
    if (Test-Path -LiteralPath $pw) {
        # Group by family (chromium/firefox/webkit), keep latest
        $byFamily = @{}
        Get-ChildItem -LiteralPath $pw -Directory -Force -ErrorAction SilentlyContinue | ForEach-Object {
            $name = $_.Name  # e.g., chromium-1234, firefox-5678, webkit-9012
            if ($name -match '^(.+?)-(\d+)$') {
                $fam = $Matches[1]
                if (-not $byFamily.ContainsKey($fam)) { $byFamily[$fam] = @() }
                $byFamily[$fam] += $_
            }
        }
        $pwTotal = 0L
        foreach ($fam in $byFamily.Keys) {
            $sorted = $byFamily[$fam] | Sort-Object Name -Descending
            $keep = $sorted[0]
            $del = $sorted | Select-Object -Skip 1
            foreach ($d in $del) {
                $sz = Get-FolderSizeFast -Path $d.FullName
                $pwTotal += $sz
                if ($DryRun) {
                    Write-Log ("  [DRY] Would delete {0} ({1})" -f $d.FullName, (Get-FriendlySize $sz)) 'DRY'
                } else {
                    try {
                        Remove-Item -LiteralPath $d.FullName -Recurse -Force -ErrorAction Stop
                        Write-Log ("  Deleted {0} ({1})" -f $d.FullName, (Get-FriendlySize $sz)) 'OK'
                    } catch {
                        Write-Log ("  Failed to delete {0}: {1}" -f $d.FullName, $_.Exception.Message) 'WARN'
                    }
                }
            }
            Write-Log ("  Kept {0}" -f $keep.FullName) 'INFO'
        }
        Write-Log ("  Playwright total reclaimed: {0}" -f (Get-FriendlySize $pwTotal)) 'OK'
    } else {
        Write-Log '  Playwright not present.' 'SKIP'
    }

    # Full $env:TEMP wipe (older than 1 day)
    Write-Log ''
    Write-Log '== $env:TEMP older than 1 day ==' 'HEAD'
    $cutoff1 = (Get-Date).AddDays(-1)
    $tBytes = 0L; $tCount = 0; $tSkip = 0
    Get-ChildItem -Path $env:TEMP -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoff1 } | ForEach-Object {
            $sz = $_.Length
            if ($DryRun) { $tBytes += $sz; $tCount++ }
            else {
                try { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop; $tBytes += $sz; $tCount++ }
                catch { $tSkip++ }
            }
        }
    Write-Log ("  Files: {0}  Reclaimed: {1}  Skipped: {2}" -f $tCount, (Get-FriendlySize $tBytes), $tSkip) 'OK'

    # C:\Windows\Temp >7 days (admin only)
    Write-Log ''
    Write-Log '== C:\Windows\Temp older than 7 days (admin only) ==' 'HEAD'
    if (-not (Test-IsAdmin)) {
        Write-Log '  Skip: not running as Administrator.' 'SKIP'
    } else {
        $cutoff7 = (Get-Date).AddDays(-7)
        $wBytes = 0L; $wCount = 0; $wSkip = 0
        Get-ChildItem -Path 'C:\Windows\Temp' -File -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -lt $cutoff7 } | ForEach-Object {
                $sz = $_.Length
                if ($DryRun) { $wBytes += $sz; $wCount++ }
                else {
                    try { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop; $wBytes += $sz; $wCount++ }
                    catch { $wSkip++ }
                }
            }
        Write-Log ("  Files: {0}  Reclaimed: {1}  Skipped: {2}" -f $wCount, (Get-FriendlySize $wBytes), $wSkip) 'OK'
    }

    # Discord cache
    Write-Log ''
    Write-Log '== Discord cache (skip if running) ==' 'HEAD'
    if (Test-AppRunning -ExeNames @('Discord')) {
        Write-Log '  Discord running, skip.' 'SKIP'
    } else {
        $dcBase = Join-Path $env:APPDATA 'discord'
        if (Test-Path $dcBase) {
            $totalDc = 0L
            foreach ($sub in @('Cache', 'Code Cache', 'GPUCache')) {
                $p = Join-Path $dcBase $sub
                if (Test-Path -LiteralPath $p) {
                    $r = Remove-DirContents -Path $p -DryRun:$DryRun
                    $totalDc += $r.DeletedBytes
                }
            }
            Write-Log ("  Discord: {0}" -f (Get-FriendlySize $totalDc)) 'OK'
        } else { Write-Log '  Discord not found.' 'SKIP' }
    }

    # Slack cache
    Write-Log ''
    Write-Log '== Slack cache (skip if running) ==' 'HEAD'
    if (Test-AppRunning -ExeNames @('slack')) {
        Write-Log '  Slack running, skip.' 'SKIP'
    } else {
        $slBase = Join-Path $env:APPDATA 'Slack'
        if (Test-Path $slBase) {
            $totalSl = 0L
            foreach ($sub in @('Cache', 'Code Cache', 'GPUCache')) {
                $p = Join-Path $slBase $sub
                if (Test-Path -LiteralPath $p) {
                    $r = Remove-DirContents -Path $p -DryRun:$DryRun
                    $totalSl += $r.DeletedBytes
                }
            }
            Write-Log ("  Slack: {0}" -f (Get-FriendlySize $totalSl)) 'OK'
        } else { Write-Log '  Slack not found.' 'SKIP' }
    }

    # SquirrelTemp
    Write-Log ''
    Write-Log '== SquirrelTemp ==' 'HEAD'
    $sq = Join-Path $env:LOCALAPPDATA 'SquirrelTemp'
    if (Test-Path -LiteralPath $sq) {
        $r = Remove-DirContents -Path $sq -DryRun:$DryRun
        Write-Log ("  {0}" -f (Get-FriendlySize $r.DeletedBytes)) 'OK'
    } else { Write-Log '  SquirrelTemp not present.' 'SKIP' }

    return $true
}
