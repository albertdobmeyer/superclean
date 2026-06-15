# core/report.ps1 - read-only diagnostic for --report

function Get-MemorySnapshot {
    $os = Get-CimInstance Win32_OperatingSystem
    return [PSCustomObject]@{
        TotalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
        FreeGB  = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
        UsedGB  = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1MB, 1)
    }
}

function Get-WslState {
    $vm = Get-Process -Name 'vmmemWSL' -ErrorAction SilentlyContinue
    $vmMB = if ($vm) { [math]::Round($vm.WorkingSet64 / 1MB, 1) } else { 0 }
    $distros = @()
    try {
        $out = & wsl --list --quiet 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) {
            $distros = ($out -split "`r?`n") | Where-Object { $_ -and $_.Trim() } | ForEach-Object { ($_ -replace "`0", '').Trim() }
        }
    } catch {}
    $wslExe = (Get-Process -Name 'wsl' -ErrorAction SilentlyContinue | Measure-Object).Count
    return [PSCustomObject]@{
        VmMB         = $vmMB
        Distros      = $distros
        InteractiveSessions = $wslExe
    }
}

function Get-DockerVhdxSize {
    $dockerLocal = Join-Path $env:LOCALAPPDATA 'Docker'
    $candidates = @(
        (Join-Path $dockerLocal 'wsl\disk\docker_data.vhdx'),
        (Join-Path $dockerLocal 'wsl\data\ext4.vhdx'),
        (Join-Path $dockerLocal 'wsl\distro\ext4.vhdx')
    )
    $total = 0L
    $paths = @()
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) {
            $sz = (Get-Item -LiteralPath $c).Length
            $total += $sz
            $paths += @{ Path = $c; Size = $sz }
        }
    }
    # Also count the wsl folder generally
    $wslFolder = Join-Path $dockerLocal 'wsl'
    $folderSize = if (Test-Path $wslFolder) { Get-FolderSizeFast -Path $wslFolder } else { 0L }
    return @{ TotalBytes = $folderSize; Paths = $paths }
}

function Get-WindowsOldSize {
    if (-not (Test-Path 'C:\Windows.old')) { return 0L }
    return (Get-FolderSizeFast -Path 'C:\Windows.old')
}

function Get-RecycleBinSize {
    $shell = New-Object -ComObject Shell.Application
    $bin = $shell.Namespace(10)
    if (-not $bin) { return 0L }
    $size = 0L
    try {
        foreach ($item in $bin.Items()) {
            try { $size += $item.Size } catch {}
        }
    } catch {}
    return $size
}

function Get-ServiceHealth {
    # Default health check: the local model daemon most agentic devs run.
    $services = [ordered]@{
        'Ollama (11434)' = 'http://localhost:11434/api/tags'
    }
    # Optional user-defined services from services.conf ("label|url" per line).
    foreach ($line in (Read-ConfLines -Path (Get-ConfPath 'services.conf'))) {
        $parts = $line -split '\|', 2
        if ($parts.Count -eq 2) {
            $services[$parts[0].Trim()] = $parts[1].Trim()
        }
    }
    $results = [ordered]@{}
    foreach ($name in $services.Keys) {
        try {
            $r = Invoke-WebRequest -Uri $services[$name] -Method Get -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
            $results[$name] = if ($r.StatusCode -eq 200) { 'Running' } else { "HTTP $($r.StatusCode)" }
        } catch {
            $results[$name] = 'Not running'
        }
    }
    return $results
}

function Invoke-Report {
    param([hashtable]$ProtectedPids)

    Write-Section 'SUPERCLEAN -- REPORT'

    # 1. Protected processes
    Write-Log ''
    Write-Log '== PROTECTED PROCESSES (will not be killed) ==' 'HEAD'
    $summary = Get-ProtectedRunningSummary
    foreach ($name in $summary.Keys) {
        $pids = $summary[$name]
        if ($pids.Count -gt 0) {
            Write-Log ("  {0,-22} {1} running (PIDs: {2})" -f $name, $pids.Count, ($pids -join ', '))
        }
    }
    Write-Log ("  Total protected PIDs (incl descendants): {0}" -f $ProtectedPids.Count) 'INFO'

    # 2. Memory
    Write-Log ''
    Write-Log '== MEMORY ==' 'HEAD'
    $mem = Get-MemorySnapshot
    Write-Log ("  RAM: {0} / {1} GB used ({2:N1}% , {3} GB free)" -f $mem.UsedGB, $mem.TotalGB, (($mem.UsedGB / $mem.TotalGB) * 100), $mem.FreeGB)
    $standby = Get-StandbyListSizeMB
    if ($standby -ge 0) {
        Write-Log ("  Standby (cached) memory: {0} MB" -f $standby)
    }
    $cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
    Write-Log ("  CPU load: {0}%" -f $cpu)
    $gpu = Get-GpuUtilization
    if ($gpu -ge 0) {
        Write-Log ("  GPU compute: {0}%" -f $gpu)
    }

    # 3. Top consumers
    Write-Log ''
    Write-Log '== TOP 10 PROCESSES BY RAM ==' 'HEAD'
    Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 10 | ForEach-Object {
        $tag = if ($ProtectedPids.ContainsKey($_.Id)) { '[PROT]' } else { '      ' }
        Write-Log ("  {0} PID {1,-7} {2,-25} {3,8} MB" -f $tag, $_.Id, $_.ProcessName, [math]::Round($_.WorkingSet64/1MB, 1))
    }

    # 4. Orphans
    Write-Log ''
    Write-Log '== ORPHAN DEV PROCESSES ==' 'HEAD'
    $orphans = @(Find-OrphanProcs -ProtectedPids $ProtectedPids)
    if ($orphans.Count -eq 0) {
        Write-Log '  None found.' 'OK'
    } else {
        Write-Log ("  Found {0} orphan(s):" -f $orphans.Count) 'WARN'
        foreach ($o in $orphans) {
            $cmd = if ($o.CommandLine -and $o.CommandLine.Length -gt 100) { $o.CommandLine.Substring(0,100) + '...' } else { $o.CommandLine }
            Write-Log ("    PID {0,-7} {1,-12} {2}" -f $o.ProcId, $o.Name, $cmd)
        }
    }

    # 5. Ollama
    Write-Log ''
    Write-Log '== OLLAMA ==' 'HEAD'
    $models = Get-OllamaLoadedModels
    if ($models.Count -eq 0) {
        if (Test-OllamaRunning) {
            Write-Log '  Daemon running, no models loaded.' 'OK'
        } else {
            Write-Log '  Daemon not running.' 'INFO'
        }
    } else {
        foreach ($m in $models) {
            $exp = if ($m.ExpiresAt) { "until $($m.ExpiresAt.ToString('HH:mm'))" } else { 'no expiry' }
            Write-Log ("  {0,-30} {1,8}  {2}" -f $m.Name, (Get-FriendlySize $m.SizeBytes), $exp)
        }
    }

    # 6. Drives
    Write-Log ''
    Write-Log '== FIXED DRIVES ==' 'HEAD'
    foreach ($d in Get-FixedDrives) {
        $totalGB = [math]::Round($d.Size / 1GB, 1)
        $freeGB  = [math]::Round($d.FreeSpace / 1GB, 1)
        $usedPct = if ($d.Size -gt 0) { [math]::Round((($d.Size - $d.FreeSpace) / $d.Size) * 100, 1) } else { 0 }
        $level = 'OK'
        if ($usedPct -gt 90) { $level = 'ERROR' }
        elseif ($usedPct -gt 80) { $level = 'WARN' }
        Write-Log ("  {0}  {1,5}% used  ({2,7} / {3,7} GB free)" -f $d.DeviceID, $usedPct, $freeGB, $totalGB) $level
    }

    # 7. WSL
    Write-Log ''
    Write-Log '== WSL ==' 'HEAD'
    $wsl = Get-WslState
    Write-Log ("  VmmemWSL: {0} MB" -f $wsl.VmMB)
    Write-Log ("  Distros: {0}" -f ($wsl.Distros -join ', '))
    Write-Log ("  Interactive wsl.exe sessions: {0}" -f $wsl.InteractiveSessions)

    # 8. Docker bloat
    Write-Log ''
    Write-Log '== DOCKER BLOAT ==' 'HEAD'
    $docker = Get-DockerVhdxSize
    if ($docker.TotalBytes -eq 0) {
        Write-Log '  No Docker WSL data found.' 'OK'
    } else {
        Write-Log ("  Total: {0}" -f (Get-FriendlySize $docker.TotalBytes))
        foreach ($p in $docker.Paths) {
            Write-Log ("    {0}  {1}" -f $p.Path, (Get-FriendlySize $p.Size))
        }
    }

    # 9. Windows.old
    Write-Log ''
    Write-Log '== WINDOWS.OLD ==' 'HEAD'
    $woSize = Get-WindowsOldSize
    if ($woSize -eq 0) {
        Write-Log '  Not present.' 'OK'
    } else {
        Write-Log ("  Present: {0}" -f (Get-FriendlySize $woSize)) 'WARN'
    }

    # 10. Recycle Bin
    Write-Log ''
    Write-Log '== RECYCLE BIN ==' 'HEAD'
    $rb = Get-RecycleBinSize
    Write-Log ("  Size: {0}" -f (Get-FriendlySize $rb))

    # 11. Services
    Write-Log ''
    Write-Log '== SERVICE HEALTH ==' 'HEAD'
    $svcs = Get-ServiceHealth
    foreach ($name in $svcs.Keys) {
        $level = if ($svcs[$name] -eq 'Running') { 'OK' } else { 'INFO' }
        Write-Log ("  {0,-22} {1}" -f $name, $svcs[$name]) $level
    }

    # 12. Estimated reclaim per level
    Write-Log ''
    Write-Log '== ESTIMATED RECLAIM PER LEVEL ==' 'HEAD'
    Write-Log '  --dust   : Recycle Bin (>7d) + tiny caches    < 2 GB'
    Write-Log '  --brush  : + standby flush + working-set trim + orphans + Cursor/Claude sub-caches'
    $standbyDisp = if ($standby -ge 0) { $standby } else { '?' }
    Write-Log ("           : standby ~{0} MB, orphans {1}" -f $standbyDisp, $orphans.Count)
    Write-Log '  --clean  : + pip/npm purge + idle Ollama unload + logs + targets.conf folders'
    Write-Log '  --wipe   : + browser caches + Playwright + full Temp'
    if ($docker.TotalBytes -gt 0 -or $woSize -gt 0) {
        Write-Log ("  --nuke   : + Docker {0} + Windows.old {1}" -f (Get-FriendlySize $docker.TotalBytes), (Get-FriendlySize $woSize)) 'WARN'
    } else {
        Write-Log '  --nuke   : nothing major to nuke (Docker empty, no Windows.old)'
    }
    Write-Log ''
}

function Invoke-ListProtected {
    Write-Section 'PROTECTED PROCESS LIST'
    Write-Log 'Hardcoded protected names:'
    foreach ($n in (Get-AllProtectedProcessNames)) {
        $procs = Get-Process -Name $n -ErrorAction SilentlyContinue
        $count = if ($procs) { $procs.Count } else { 0 }
        $tag = if ($count -gt 0) { '*' } else { ' ' }
        Write-Log ("  {0} {1,-22} {2} running" -f $tag, $n, $count)
    }
    Write-Log ''
    Write-Log "User additions ($(Get-ConfPath 'protect.conf')):"
    $extra = Read-ProtectConf
    if ($extra.Count -eq 0) {
        Write-Log '  (none)'
    } else {
        foreach ($n in $extra) { Write-Log "  $n" }
    }
}

function Invoke-Last {
    # Find most recent log file
    $logDir = Get-SupercleanDataDir
    if (-not (Test-Path $logDir)) {
        Write-Log 'No logs found.' 'WARN'
        return
    }
    $latest = Get-ChildItem -Path $logDir -Filter 'superclean-*.log' -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) {
        Write-Log 'No previous superclean runs found.' 'WARN'
        return
    }
    Write-Section ("LAST RUN: " + $latest.Name)
    Write-Log ("  File:  $($latest.FullName)")
    Write-Log ("  When:  $($latest.LastWriteTime)")
    Write-Log ''
    # Print last "RUN START" block to end
    $lines = Get-Content -LiteralPath $latest.FullName -ErrorAction SilentlyContinue
    $lastStartIdx = -1
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        if ($lines[$i] -match 'RUN START') { $lastStartIdx = $i; break }
    }
    if ($lastStartIdx -ge 0) {
        $tail = $lines[$lastStartIdx..($lines.Count - 1)]
        foreach ($l in $tail) { Write-Host $l }
    } else {
        $tail = if ($lines.Count -gt 50) { $lines[-50..-1] } else { $lines }
        foreach ($l in $tail) { Write-Host $l }
    }
}
