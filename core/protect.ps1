# core/protect.ps1 - protected process detection (the safety perimeter)

$script:ProtectConfPath = Join-Path $PSScriptRoot '..\protect.conf'

# Hardcoded baseline of process names that must never be touched
$script:HardcodedProtectedNames = @(
    'Cursor',           # Cursor IDE
    'Code',             # VS Code
    'Antigravity',      # Antigravity IDE
    'claude',           # Claude Desktop (MS Store app)
    'opencode',         # opencode CLI
    'ollama',           # Ollama daemon - never stop
    'ollama_llama_server',
    'WindowsTerminal',  # User's terminal
    'wt',               # Windows Terminal alias
    'pwsh',             # PowerShell 7
    'powershell',       # PowerShell 5.1 (interactive will be filtered)
    'cmd',              # Command prompt (interactive)
    'docker',           # Docker CLI (when actively running a command)
    'OllamaApp'         # Ollama tray app
)

function Get-CommandLineByPid {
    param([int]$ProcId)
    try {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction SilentlyContinue
        if ($p) { return $p.CommandLine }
    } catch {}
    return $null
}

function Get-ParentPid {
    param([int]$ProcId)
    try {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction SilentlyContinue
        if ($p) { return [int]$p.ParentProcessId }
    } catch {}
    return 0
}

function Read-ProtectConf {
    $extra = @()
    if (Test-Path -LiteralPath $script:ProtectConfPath) {
        Get-Content -LiteralPath $script:ProtectConfPath -ErrorAction SilentlyContinue | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith('#')) {
                $extra += $line
            }
        }
    }
    return $extra
}

function Get-AllProtectedProcessNames {
    $extra = Read-ProtectConf
    $all = @($script:HardcodedProtectedNames) + $extra
    return ($all | Sort-Object -Unique)
}

# Build the full set of protected PIDs:
# - Procs whose name matches the protected list
# - All descendants of those procs
# - Our own ancestor chain
# - Any node.exe whose command line contains 'claude' or 'opencode'
function Get-ProtectedPids {
    $protected = @{}
    $names = Get-AllProtectedProcessNames

    # 1) Match by process name (case-insensitive)
    $allProcs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue
    foreach ($p in $allProcs) {
        $procName = $p.Name -replace '\.exe$', ''
        foreach ($n in $names) {
            if ($procName -ieq $n) {
                $protected[[int]$p.ProcessId] = $true
                break
            }
        }
    }

    # 2) Special-case: any node.exe whose command line references 'claude' or 'opencode'
    foreach ($p in $allProcs) {
        if ($p.Name -ieq 'node.exe' -and $p.CommandLine) {
            if ($p.CommandLine -match '(?i)claude|opencode|@anthropic|@modelcontextprotocol') {
                $protected[[int]$p.ProcessId] = $true
            }
        }
    }

    # 3) Walk descendants of every currently-protected PID
    $queue = New-Object System.Collections.Queue
    foreach ($k in @($protected.Keys)) { $queue.Enqueue($k) }
    while ($queue.Count -gt 0) {
        $parent = $queue.Dequeue()
        foreach ($p in $allProcs) {
            if ([int]$p.ParentProcessId -eq $parent -and -not $protected.ContainsKey([int]$p.ProcessId)) {
                $protected[[int]$p.ProcessId] = $true
                $queue.Enqueue([int]$p.ProcessId)
            }
        }
    }

    # 4) Walk our own ancestry
    $cur = $PID
    for ($i = 0; $i -lt 20; $i++) {
        $protected[$cur] = $true
        $par = Get-ParentPid -ProcId $cur
        if ($par -and $par -ne 0 -and $par -ne $cur) {
            $cur = $par
        } else { break }
    }

    return $protected
}

# Returns @{ Name -> @(PIDs) } of protected procs currently running
function Get-ProtectedRunningSummary {
    $names = Get-AllProtectedProcessNames
    $summary = [ordered]@{}
    foreach ($n in $names) {
        $procs = Get-Process -Name $n -ErrorAction SilentlyContinue
        if ($procs) {
            $summary[$n] = @($procs | ForEach-Object { $_.Id })
        } else {
            $summary[$n] = @()
        }
    }
    return $summary
}
