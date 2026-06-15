# core/orphans.ps1 - smart orphan dev-process detection and removal

$script:OrphanCandidateNames = @(
    'node', 'python', 'python3', 'tsx', 'ts-node',
    'esbuild', 'vite', 'next-server', 'webpack',
    'pnpm', 'yarn', 'rollup'
)

# A process is an orphan if:
#   1. Its name matches a dev-server candidate
#   2. NOT in the protected PID set
#   3. Has been alive for >= 60 seconds (avoid race with new spawns)
#   4. Its parent process is GONE (PID no longer exists), OR parent's StartTime
#      doesn't match what was recorded (PID reuse - old parent died)
function Find-OrphanProcs {
    param(
        [hashtable]$ProtectedPids
    )

    $allProcs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue
    # Build PID -> StartTime map for quick lookup
    $procByPid = @{}
    foreach ($p in $allProcs) { $procByPid[[int]$p.ProcessId] = $p }

    $now = Get-Date
    $orphans = @()

    foreach ($p in $allProcs) {
        $procName = ($p.Name -replace '\.exe$', '').ToLower()
        if ($script:OrphanCandidateNames -notcontains $procName) { continue }

        $procPid = [int]$p.ProcessId
        if ($ProtectedPids.ContainsKey($procPid)) { continue }

        # Get StartTime for age check
        $startTime = $null
        try {
            $proc = Get-Process -Id $procPid -ErrorAction SilentlyContinue
            if ($proc) { $startTime = $proc.StartTime }
        } catch {}
        if (-not $startTime) { continue }

        $ageSec = ($now - $startTime).TotalSeconds
        if ($ageSec -lt 60) { continue }

        # Parent check
        $parentPid = [int]$p.ParentProcessId
        $parentGone = $true
        if ($parentPid -and $procByPid.ContainsKey($parentPid)) {
            # Parent PID exists right now - but is it the SAME parent as when this proc started?
            # If parent's StartTime is later than this proc's StartTime, it's a recycled PID.
            try {
                $parentProc = Get-Process -Id $parentPid -ErrorAction SilentlyContinue
                if ($parentProc -and $parentProc.StartTime -le $startTime) {
                    $parentGone = $false  # Real parent is still alive
                }
            } catch {}
        }

        if ($parentGone) {
            $cmdLine = $p.CommandLine
            $workDir = $null
            try {
                # Best-effort working dir from command line
                if ($cmdLine -match '"?([A-Z]:\\[^"]+?)\\node_modules') {
                    $workDir = $Matches[1]
                }
            } catch {}

            $cmdShort = if ($cmdLine -and $cmdLine.Length -gt 140) {
                $cmdLine.Substring(0, 140) + '...'
            } else { $cmdLine }

            $orphans += [PSCustomObject]@{
                ProcId      = $procPid
                Name        = $p.Name
                StartTime   = $startTime
                ParentPid   = $parentPid
                CommandLine = $cmdShort
                WorkingDir  = $workDir
            }
        }
    }

    return $orphans
}

function Remove-OrphanProcs {
    param(
        [AllowNull()][AllowEmptyCollection()][object[]]$Orphans,
        [switch]$DryRun
    )

    if (-not $Orphans -or $Orphans.Count -eq 0) {
        Write-Log '  No orphan dev processes found.' 'OK'
        return @{ Killed = 0; Failed = 0; WorkDirs = @() }
    }

    Write-Log ("  Found {0} orphan dev process(es):" -f $Orphans.Count) 'INFO'
    foreach ($o in $Orphans) {
        $tag = if ($DryRun) { '[DRY] ' } else { '' }
        Write-Log ("    {0}PID {1,-7} {2,-12} {3}" -f $tag, $o.ProcId, $o.Name, $o.CommandLine) 'INFO'
    }

    if ($DryRun) {
        return @{ Killed = 0; Failed = 0; WorkDirs = @($Orphans | Where-Object { $_.WorkingDir } | Select-Object -ExpandProperty WorkingDir -Unique) }
    }

    $killed = 0
    $failed = 0
    $dirs = @()
    foreach ($o in $Orphans) {
        # Re-validate just before kill: same PID, same StartTime?
        $cur = Get-Process -Id $o.ProcId -ErrorAction SilentlyContinue
        if (-not $cur) {
            Write-Log ("    PID {0} already gone, skipping." -f $o.ProcId) 'SKIP'
            continue
        }
        if ($cur.StartTime -ne $o.StartTime) {
            Write-Log ("    PID {0} reused by another process, skipping." -f $o.ProcId) 'SKIP'
            continue
        }
        try {
            Stop-Process -Id $o.ProcId -Force -ErrorAction Stop
            $killed++
            if ($o.WorkingDir) { $dirs += $o.WorkingDir }
            Write-Log ("    Killed PID {0}" -f $o.ProcId) 'OK'
        } catch {
            $failed++
            Write-Log ("    Failed to kill PID {0}: {1}" -f $o.ProcId, $_.Exception.Message) 'ERROR'
        }
    }

    $uniqueDirs = $dirs | Sort-Object -Unique
    if ($uniqueDirs.Count -gt 0) {
        Write-Log "  Killed dev servers in:" 'INFO'
        foreach ($d in $uniqueDirs) { Write-Log "    $d" 'INFO' }
    }

    return @{ Killed = $killed; Failed = $failed; WorkDirs = @($uniqueDirs) }
}
