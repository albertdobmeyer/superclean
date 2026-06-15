# levels/nuke.ps1 - Destructive: Docker WSL reset + Windows.old removal
# Requires typing the word NUKE (or --yes --i-know for unattended)
# Per spec: NEVER touches Cursor workspaceStorage (removed from spec for safety)

function Invoke-LevelNuke {
    param(
        [hashtable]$ProtectedPids,
        [switch]$DryRun,
        [switch]$Yes,
        [switch]$IKnow
    )

    Invoke-LevelWipe -ProtectedPids $ProtectedPids -DryRun:$DryRun -Yes:$Yes | Out-Null

    Write-Section 'LEVEL: --nuke (DESTRUCTIVE)'

    # Build manifest
    $manifest = @()
    $dockerSize = 0L
    $dockerPath = Join-Path $env:LOCALAPPDATA 'Docker\wsl'
    if (Test-Path $dockerPath) {
        $dockerSize = Get-FolderSizeFast -Path $dockerPath
    }
    if ($dockerSize -gt 0) {
        $manifest += "  - Docker WSL distros + leftovers ($([math]::Round($dockerSize/1GB,2)) GB)  [all images, containers, volumes, build cache]"
    }
    $woSize = 0L
    if (Test-Path 'C:\Windows.old') {
        $woSize = Get-FolderSizeFast -Path 'C:\Windows.old'
    }
    if ($woSize -gt 0) {
        $manifest += "  - C:\Windows.old ($([math]::Round($woSize/1GB,2)) GB)  [previous Windows installation]"
    }

    if ($manifest.Count -eq 0) {
        Write-Log 'Nothing to nuke (Docker empty, no Windows.old). Exiting.' 'OK'
        return $true
    }

    Write-Log ''
    Write-Log 'NUKE MANIFEST - the following will be PERMANENTLY DELETED:' 'WARN'
    foreach ($m in $manifest) { Write-Log $m 'WARN' }
    Write-Log ''

    # Confirmation
    $confirmed = $false
    if ($Yes -and $IKnow) {
        Write-Log 'Confirmation bypassed via --yes --i-know.' 'WARN'
        $confirmed = $true
    } else {
        Write-Log 'Type NUKE (uppercase, exact) to proceed; anything else aborts:'
        $resp = Read-Host '  >'
        if ($resp -ceq 'NUKE') {
            $confirmed = $true
        } else {
            Write-Log 'Confirmation not given. Aborting.' 'WARN'
            return $false
        }
    }

    if (-not $confirmed) { return $false }

    if ($DryRun) {
        Write-Log '[DRY RUN - no actions taken below]' 'DRY'
    }

    # 1. Docker reset
    if ($dockerSize -gt 0) {
        Write-Log ''
        Write-Log '== Docker WSL distro reset ==' 'HEAD'

        if (-not $DryRun) {
            # Stop Docker Desktop processes (NOT in protected list)
            Write-Log '  Stopping Docker Desktop processes...'
            $dockerProcs = @('Docker Desktop', 'com.docker.backend', 'com.docker.build', 'com.docker.cli', 'com.docker.proxy', 'dockerd')
            foreach ($pn in $dockerProcs) {
                Get-Process -Name $pn -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
            }
            Start-Sleep -Seconds 3

            # WSL distros
            Write-Log '  Unregistering Docker WSL distros...'
            foreach ($d in @('docker-desktop-data', 'docker-desktop')) {
                & wsl --unregister $d 2>&1 | Out-Null
            }

            # Leftover folders
            $leftovers = @(
                (Join-Path $env:LOCALAPPDATA 'Docker\wsl'),
                (Join-Path $env:LOCALAPPDATA 'Docker\log')
            )
            foreach ($p in $leftovers) {
                if (Test-Path -LiteralPath $p) {
                    try {
                        Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop
                        Write-Log ("  Removed {0}" -f $p) 'OK'
                    } catch {
                        Write-Log ("  Failed to remove {0}: {1}" -f $p, $_.Exception.Message) 'WARN'
                    }
                }
            }
            Write-Log "  Docker reset complete. Docker Desktop is still installed but empty." 'OK'
        } else {
            Write-Log '  [DRY] Would stop Docker, wsl --unregister docker-desktop(-data), remove wsl/ + log/' 'DRY'
        }
    }

    # 2. Windows.old removal
    if ($woSize -gt 0) {
        Write-Log ''
        Write-Log '== Windows.old removal ==' 'HEAD'
        if (-not (Test-IsAdmin)) {
            Write-Log '  Skip: requires Administrator. Re-run elevated.' 'WARN'
        } else {
            if ($DryRun) {
                Write-Log '  [DRY] Would takeown + icacls + rd /s /q C:\Windows.old' 'DRY'
            } else {
                Write-Log '  Taking ownership (this can take a few minutes)...'
                & takeown /F 'C:\Windows.old' /R /A /D Y 2>&1 | Out-Null
                & icacls 'C:\Windows.old' /grant 'Administrators:F' /T /C /Q 2>&1 | Out-Null
                Write-Log '  Removing C:\Windows.old...'
                Remove-Item -Path 'C:\Windows.old' -Recurse -Force -ErrorAction SilentlyContinue
                if (Test-Path 'C:\Windows.old') {
                    & cmd.exe /c 'rd /s /q C:\Windows.old' 2>&1 | Out-Null
                }
                if (Test-Path 'C:\Windows.old') {
                    Write-Log '  Some files remain (TrustedInstaller-locked). Use Settings > Storage > Cleanup recommendations.' 'WARN'
                } else {
                    Write-Log '  Windows.old removed.' 'OK'
                }
            }
        }
    }

    return $true
}
