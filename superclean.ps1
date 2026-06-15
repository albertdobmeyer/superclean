# superclean.ps1 - Main entry point
# Agentic-dev garbage collector: one command, tiered intensity, never kills your
# active editors, terminals, or AI tooling.
#
# Usage:
#   superclean --help
#   superclean --report
#   superclean --dust | --brush | --clean | --wipe | --nuke
#   superclean --ram | --gpu-reset | --last | --list-protected
#
# Modifiers:
#   --dry-run --yes -y --i-know --quiet -q --log <path> --no-color --force-unlock

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RawArgs = @()
)

$ErrorActionPreference = 'Continue'
$script:Root = $PSScriptRoot

# --- Dot-source all components ---
. (Join-Path $script:Root 'core\common.ps1')
. (Join-Path $script:Root 'core\protect.ps1')
. (Join-Path $script:Root 'core\orphans.ps1')
. (Join-Path $script:Root 'core\memory.ps1')
. (Join-Path $script:Root 'core\ollama.ps1')
. (Join-Path $script:Root 'core\report.ps1')
. (Join-Path $script:Root 'core\ram-mode.ps1')
. (Join-Path $script:Root 'levels\dust.ps1')
. (Join-Path $script:Root 'levels\brush.ps1')
. (Join-Path $script:Root 'levels\clean.ps1')
. (Join-Path $script:Root 'levels\wipe.ps1')
. (Join-Path $script:Root 'levels\nuke.ps1')

function Show-Help {
    @'
superclean -- agentic-dev garbage collector for Windows

Reclaims RAM, VRAM, and disk left behind by heavy parallel development:
orphaned dev servers, idle model loads, build/test caches, and browser junk.
Your open editors, terminals, and AI tools are never touched.

USAGE:
  superclean <LEVEL or MODE> [MODIFIERS]

LEVELS (additive -- higher includes everything below):
  --report, -r        Read-only diagnostic. No changes.
  --dust              Gentle: Recycle Bin >7d, tiny sub-caches
  --brush             + smart-orphan kill, standby flush, working-set trim, Cursor/Claude renewable caches
  --clean             + pip/npm/uv purge, idle Ollama unload, log prune, $TEMP >7d
  --wipe              + browser caches (skip if running), Playwright bins, full Temp wipe
  --nuke              + Docker WSL reset, Windows.old removal  [requires typing NUKE]

STANDALONE MODES:
  --ram               RAM relief only: standby flush, working-set trim, smart-orphan kill, idle Ollama
  --gpu-reset         GPU device tree re-enumeration (admin only)
  --last              Print summary of last run from log
  --list-protected    Print protected process list + which are currently running
  --help, -h          This help

MODIFIERS (combine with any level/mode):
  --dry-run           No changes; print what would happen
  --yes, -y           Skip y/N prompts (does NOT bypass NUKE typed confirm alone)
  --i-know            With --yes: bypass NUKE typed confirm (unattended only)
  --quiet, -q         Minimal stdout (full detail still logged)
  --log <path>        Override log file path
  --no-color          Disable ANSI color
  --force-unlock      Override stuck lockfile

NEVER KILLED: Cursor, VS Code, Antigravity, Claude Desktop, Claude Code (this session),
opencode, Windows Terminal, ollama daemon, plus their descendants.
Add custom names in: protect.conf (next to superclean.ps1)

LOG: %LOCALAPPDATA%\superclean\superclean-YYYY-MM-DD.log

Examples:
  superclean --report
  superclean --ram
  superclean --brush
  superclean --clean --dry-run
  superclean --wipe --yes
  superclean --nuke
'@
}

# --- Parse args ---
$wantHelp = $false
$wantReport = $false
$wantRam = $false
$wantGpuReset = $false
$wantLast = $false
$wantListProtected = $false
$level = $null
$dryRun = $false
$yes = $false
$iKnow = $false
$quiet = $false
$noColor = $false
$forceUnlock = $false
$customLog = $null

$i = 0
while ($i -lt $RawArgs.Count) {
    $a = $RawArgs[$i]
    switch -regex ($a) {
        '^(--help|-h)$'           { $wantHelp = $true }
        '^(--report|-r)$'         { $wantReport = $true }
        '^--ram$'                 { $wantRam = $true }
        '^--gpu-reset$'           { $wantGpuReset = $true }
        '^--last$'                { $wantLast = $true }
        '^--list-protected$'      { $wantListProtected = $true }
        '^--dust$'                { $level = 'dust' }
        '^--brush$'               { $level = 'brush' }
        '^--clean$'               { $level = 'clean' }
        '^--wipe$'                { $level = 'wipe' }
        '^--nuke$'                { $level = 'nuke' }
        '^--dry-run$'             { $dryRun = $true }
        '^(--yes|-y)$'            { $yes = $true }
        '^--i-know$'              { $iKnow = $true }
        '^(--quiet|-q)$'          { $quiet = $true }
        '^--no-color$'            { $noColor = $true }
        '^--force-unlock$'        { $forceUnlock = $true }
        '^--log$'                 {
            $i++
            if ($i -lt $RawArgs.Count) { $customLog = $RawArgs[$i] }
        }
        default {
            Write-Host "Unknown argument: $a" -ForegroundColor Red
            Write-Host "Run 'superclean --help' for usage." -ForegroundColor Yellow
            exit 1
        }
    }
    $i++
}

# --- Validate exactly one mode ---
$modes = @($wantHelp, $wantReport, $wantRam, $wantGpuReset, $wantLast, $wantListProtected, ($null -ne $level))
$modeCount = ($modes | Where-Object { $_ }).Count

if ($modeCount -eq 0) {
    Show-Help
    exit 1
}
if ($modeCount -gt 1) {
    Write-Host "ERROR: Pick exactly one of: --help, --report, --dust, --brush, --clean, --wipe, --nuke, --ram, --gpu-reset, --last, --list-protected" -ForegroundColor Red
    exit 1
}

# --- Help / Last / List-protected don't need lockfile ---
if ($wantHelp) { Show-Help; exit 0 }

# --- Initialize logging ---
$today = Get-Date -Format 'yyyy-MM-dd'
$defaultLog = Join-Path (Get-SupercleanDataDir) "superclean-$today.log"
$logPath = if ($customLog) { $customLog } else { $defaultLog }
Initialize-Common -LogPath $logPath -NoColor:$noColor -Quiet:$quiet -DryRun:$dryRun

# --- Last / List-protected (still log lightly) ---
if ($wantLast) { Invoke-Last; exit 0 }
if ($wantListProtected) { Invoke-ListProtected; exit 0 }

# --- Acquire lockfile ---
$gotLock = Acquire-Lockfile -Force:$forceUnlock
if (-not $gotLock) {
    Write-Host "ERROR: Another superclean run is in progress. Use --force-unlock to override." -ForegroundColor Red
    exit 1
}

try {
    # --- Build protected PID set ---
    Write-Log ''
    $argSummary = ($RawArgs -join ' ')
    Write-Log "==================== RUN START ====================" 'HEAD'
    Write-Log "Args:    $argSummary"
    Write-Log "PID:     $PID"
    Write-Log "Admin:   $(Test-IsAdmin)"
    Write-Log "DryRun:  $dryRun"

    $beforeSnap = Get-FreeSpaceSnapshot
    foreach ($k in $beforeSnap.Keys) {
        Write-Log ("Before:  {0} free = {1}" -f $k, (Get-FriendlySize $beforeSnap[$k]))
    }

    $protectedPids = Get-ProtectedPids
    Write-Log "Protected PIDs: $($protectedPids.Count)"

    $startTime = Get-Date

    # --- Dispatch ---
    if ($wantReport) {
        Invoke-Report -ProtectedPids $protectedPids
    } elseif ($wantRam) {
        Invoke-RamMode -ProtectedPids $protectedPids -DryRun:$dryRun
    } elseif ($wantGpuReset) {
        Invoke-GpuReset
    } elseif ($level) {
        switch ($level) {
            'dust'  { Invoke-LevelDust -DryRun:$dryRun }
            'brush' { Invoke-LevelBrush -ProtectedPids $protectedPids -DryRun:$dryRun -Yes:$yes }
            'clean' { Invoke-LevelClean -ProtectedPids $protectedPids -DryRun:$dryRun -Yes:$yes }
            'wipe'  { Invoke-LevelWipe  -ProtectedPids $protectedPids -DryRun:$dryRun -Yes:$yes | Out-Null }
            'nuke'  { Invoke-LevelNuke  -ProtectedPids $protectedPids -DryRun:$dryRun -Yes:$yes -IKnow:$iKnow | Out-Null }
        }
    }

    $elapsed = (Get-Date) - $startTime
    $afterSnap = Get-FreeSpaceSnapshot

    Write-Log ''
    Write-Log '==================== RUN END ====================' 'HEAD'
    Write-Log ("Elapsed: {0:N1}s" -f $elapsed.TotalSeconds)
    foreach ($k in $afterSnap.Keys) {
        $delta = $afterSnap[$k] - $beforeSnap[$k]
        Write-Log ("After:   {0} free = {1}  (delta {2:+0;-#}{3} bytes / {4})" -f $k, (Get-FriendlySize $afterSnap[$k]), $delta, '', (Get-FriendlySize ([math]::Abs($delta))))
    }
    Write-Log "Log:     $logPath"

    exit 0
}
catch {
    Write-Log ("FATAL: $($_.Exception.Message)") 'ERROR'
    Write-Log ($_.ScriptStackTrace) 'ERROR'
    exit 3
}
finally {
    Release-Lockfile
}
