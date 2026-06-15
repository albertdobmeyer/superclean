# core/common.ps1 - shared utilities for superclean

$script:LogPath = $null
$script:NoColor = $false
$script:Quiet = $false
$script:DryRun = $false

# Repo root (the folder containing superclean.ps1). core/ -> parent.
$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

# Per-user data directory for logs + lockfile. Override-friendly, never on a
# drive that only exists on one machine.
function Get-SupercleanDataDir {
    $base = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME '.superclean' }
    $dir = Join-Path $base 'superclean'
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    return $dir
}

# Resolve an optional config file that lives next to superclean.ps1.
function Get-ConfPath {
    param([Parameter(Mandatory)][string]$Name)
    return (Join-Path $script:RepoRoot $Name)
}

# Read non-empty, non-comment lines from a config file. Returns @() if missing.
function Read-ConfLines {
    param([Parameter(Mandatory)][string]$Path)
    $lines = @()
    if (Test-Path -LiteralPath $Path) {
        Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith('#')) { $lines += $line }
        }
    }
    return $lines
}

# Discover all Python interpreters on this machine (no hardcoded user paths).
function Get-InstalledPythons {
    $found = @()
    # 1) Common install roots, any 3.x
    $roots = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)},
        'C:\'
    ) | Where-Object { $_ -and (Test-Path $_) }
    foreach ($root in $roots) {
        Get-ChildItem -Path $root -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue | ForEach-Object {
            $exe = Join-Path $_.FullName 'python.exe'
            if (Test-Path -LiteralPath $exe) { $found += $exe }
        }
    }
    # 2) Whatever is on PATH (py launcher, python, python3)
    foreach ($name in @('python', 'python3')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -and (Test-Path -LiteralPath $cmd.Source)) {
            $found += $cmd.Source
        }
    }
    return ($found | Sort-Object -Unique)
}

function Initialize-Common {
    param(
        [string]$LogPath,
        [switch]$NoColor,
        [switch]$Quiet,
        [switch]$DryRun
    )
    $script:LogPath = $LogPath
    $script:NoColor = [bool]$NoColor
    $script:Quiet = [bool]$Quiet
    $script:DryRun = [bool]$DryRun

    $logDir = Split-Path -Parent $LogPath
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
}

function Write-Log {
    param(
        [Parameter(Position=0)][string]$Message = '',
        [Parameter(Position=1)][string]$Level = 'INFO',
        [switch]$NoConsole,
        [switch]$NoFile
    )
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$ts] [$Level] $Message"

    if (-not $NoConsole -and -not $script:Quiet) {
        if ($script:NoColor) {
            Write-Host $Message
        } else {
            switch ($Level) {
                'ERROR' { Write-Host $Message -ForegroundColor Red }
                'WARN'  { Write-Host $Message -ForegroundColor Yellow }
                'OK'    { Write-Host $Message -ForegroundColor Green }
                'DRY'   { Write-Host $Message -ForegroundColor Cyan }
                'SKIP'  { Write-Host $Message -ForegroundColor DarkGray }
                'HEAD'  { Write-Host $Message -ForegroundColor Cyan }
                default { Write-Host $Message }
            }
        }
    }

    if (-not $NoFile -and $script:LogPath) {
        try { Add-Content -Path $script:LogPath -Value $line -ErrorAction SilentlyContinue } catch {}
    }
}

function Write-Section {
    param([string]$Title)
    $bar = '=' * 60
    Write-Log $bar 'HEAD'
    Write-Log $Title 'HEAD'
    Write-Log $bar 'HEAD'
}

function Get-FriendlySize {
    param([Parameter(Position=0)][long]$Bytes)
    if ($Bytes -ge 1GB) { return ('{0:N2} GB' -f ($Bytes / 1GB)) }
    if ($Bytes -ge 1MB) { return ('{0:N2} MB' -f ($Bytes / 1MB)) }
    if ($Bytes -ge 1KB) { return ('{0:N2} KB' -f ($Bytes / 1KB)) }
    return "$Bytes B"
}

function Get-FixedDrives {
    Get-CimInstance Win32_LogicalDisk -Filter 'DriveType = 3' -ErrorAction SilentlyContinue
}

function Get-FreeSpaceSnapshot {
    $snap = @{}
    foreach ($d in Get-FixedDrives) {
        $snap[$d.DeviceID] = [int64]$d.FreeSpace
    }
    return $snap
}

function Get-FolderSizeFast {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return 0L }
    $sum = 0L
    $stack = New-Object System.Collections.Stack
    $stack.Push($Path)
    while ($stack.Count -gt 0) {
        $cur = $stack.Pop()
        try {
            $di = [System.IO.DirectoryInfo]::new($cur)
            if (($di.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq [IO.FileAttributes]::ReparsePoint) { continue }
            foreach ($f in $di.EnumerateFiles()) { $sum += $f.Length }
            foreach ($d in $di.EnumerateDirectories()) {
                if (($d.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne [IO.FileAttributes]::ReparsePoint) {
                    $stack.Push($d.FullName)
                }
            }
        } catch {}
    }
    return $sum
}

function Test-IsAdmin {
    $id = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object System.Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Lockfile management
$script:LockPath = Join-Path (Get-SupercleanDataDir) 'superclean.lock'

function Acquire-Lockfile {
    param([switch]$Force)
    $lockDir = Split-Path -Parent $script:LockPath
    if (-not (Test-Path $lockDir)) {
        New-Item -ItemType Directory -Path $lockDir -Force | Out-Null
    }
    if (Test-Path $script:LockPath) {
        $existing = Get-Content $script:LockPath -ErrorAction SilentlyContinue | Select-Object -First 1
        $existingPid = 0
        [int]::TryParse($existing, [ref]$existingPid) | Out-Null
        $alive = $false
        if ($existingPid -gt 0) {
            $alive = $null -ne (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)
        }
        if ($alive -and -not $Force) {
            return $false
        }
        Remove-Item $script:LockPath -Force -ErrorAction SilentlyContinue
    }
    $PID | Out-File -FilePath $script:LockPath -Encoding ascii -Force
    return $true
}

function Release-Lockfile {
    if (Test-Path $script:LockPath) {
        Remove-Item $script:LockPath -Force -ErrorAction SilentlyContinue
    }
}

# Lock-aware deletion
function Remove-DirContents {
    param(
        [string]$Path,
        [switch]$DryRun
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return @{ DeletedBytes = 0L; SkippedFiles = 0; DeletedFiles = 0 }
    }
    $deletedBytes = 0L
    $deletedFiles = 0
    $skippedFiles = 0
    Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $item = $_
        try {
            $size = if ($item.PSIsContainer) { Get-FolderSizeFast -Path $item.FullName } else { $item.Length }
            if ($DryRun) {
                $deletedBytes += $size
                $deletedFiles++
            } else {
                Remove-Item -LiteralPath $item.FullName -Recurse -Force -ErrorAction Stop
                $deletedBytes += $size
                $deletedFiles++
            }
        } catch {
            $skippedFiles++
        }
    }
    return @{ DeletedBytes = $deletedBytes; SkippedFiles = $skippedFiles; DeletedFiles = $deletedFiles }
}

# Tries to delete a single file; returns $true on success
function Try-RemoveFile {
    param([string]$Path, [switch]$DryRun)
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    if ($DryRun) { return $true }
    try {
        Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
        return $true
    } catch { return $false }
}

# Color-aware Yes/No prompt
function Confirm-YesNo {
    param([string]$Question, [switch]$DefaultNo)
    if ($script:Quiet) { return $false }
    $suffix = if ($DefaultNo) { '[y/N]' } else { '[Y/n]' }
    $resp = Read-Host "$Question $suffix"
    if ([string]::IsNullOrWhiteSpace($resp)) { return -not $DefaultNo }
    return ($resp.Trim().ToLower() -eq 'y')
}
