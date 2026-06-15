# core/ollama.ps1 - Ollama-aware idle model unload (never breaks active clients)

function Test-OllamaRunning {
    try {
        $r = Invoke-WebRequest -Uri 'http://localhost:11434/api/tags' -Method Get -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        return $r.StatusCode -eq 200
    } catch { return $false }
}

# Returns array of @{ Name; SizeBytes; ExpiresAt; ProcessorPct } via /api/ps
function Get-OllamaLoadedModels {
    if (-not (Test-OllamaRunning)) { return @() }
    try {
        $r = Invoke-RestMethod -Uri 'http://localhost:11434/api/ps' -Method Get -TimeoutSec 5 -ErrorAction Stop
        if (-not $r.models) { return @() }
        $list = @()
        foreach ($m in $r.models) {
            $exp = $null
            if ($m.expires_at) { try { $exp = [DateTime]$m.expires_at } catch {} }
            $list += [PSCustomObject]@{
                Name      = $m.name
                SizeBytes = [int64]($m.size_vram + $m.size)
                SizeVram  = [int64]$m.size_vram
                ExpiresAt = $exp
            }
        }
        return $list
    } catch { return @() }
}

function Invoke-OllamaIdleUnload {
    param(
        [int]$IdleThresholdMinutes = 10,
        [switch]$DryRun
    )
    if (-not (Test-OllamaRunning)) {
        Write-Log '  Ollama daemon not running. Skipping.' 'SKIP'
        return @{ Unloaded = 0; ReclaimedBytes = 0 }
    }

    $loaded = Get-OllamaLoadedModels
    if ($loaded.Count -eq 0) {
        Write-Log '  No Ollama models loaded.' 'OK'
        return @{ Unloaded = 0; ReclaimedBytes = 0 }
    }

    # Conservative: only unload models whose expires_at is FAR in the future,
    # which means Ollama just refreshed their keep-alive (could be active).
    # Better signal: if expires_at is close (model is about to auto-expire), let it; otherwise leave alone.
    # Even more conservative: never auto-unload. We'll do this - make it opt-in.
    # For now: only unload models that have NO expires_at (orphaned load).
    $unloaded = 0
    $reclaimed = 0L
    foreach ($m in $loaded) {
        $shouldUnload = $false
        $reason = ''

        if (-not $m.ExpiresAt) {
            $shouldUnload = $true
            $reason = 'no expiry (orphaned)'
        } else {
            $minsUntilExpire = ($m.ExpiresAt - (Get-Date)).TotalMinutes
            # If model is set to live for <2 min, just let it expire naturally
            if ($minsUntilExpire -lt 2) {
                Write-Log ("  {0}: auto-expiring in {1:N1} min, leaving alone." -f $m.Name, $minsUntilExpire) 'SKIP'
                continue
            }
            # Otherwise: this model has been kept alive recently - likely active. Skip.
            Write-Log ("  {0}: keep-alive {1:N0} min from now, likely active. Skipping." -f $m.Name, $minsUntilExpire) 'SKIP'
            continue
        }

        if ($shouldUnload) {
            if ($DryRun) {
                Write-Log ("  [DRY] Would unload {0} (~{1}, {2})." -f $m.Name, (Get-FriendlySize $m.SizeBytes), $reason) 'DRY'
                $unloaded++
                $reclaimed += $m.SizeBytes
            } else {
                try {
                    & ollama stop $m.Name 2>&1 | Out-Null
                    Write-Log ("  Unloaded {0} (~{1}, {2})." -f $m.Name, (Get-FriendlySize $m.SizeBytes), $reason) 'OK'
                    $unloaded++
                    $reclaimed += $m.SizeBytes
                } catch {
                    Write-Log ("  Failed to unload {0}: {1}" -f $m.Name, $_.Exception.Message) 'WARN'
                }
            }
        }
    }

    return @{ Unloaded = $unloaded; ReclaimedBytes = $reclaimed }
}
