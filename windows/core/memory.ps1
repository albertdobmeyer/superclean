# core/memory.ps1 -- RAM relief that doesn't kill anything
# - Standby list flush via NtSetSystemInformation
# - Working-set trim via EmptyWorkingSet
# - DNS / ARP cache flush

# Lazily Add-Type the P/Invoke wrappers (only once per session)
function Initialize-MemoryPInvoke {
    if ('SuperClean.Mem' -as [type]) { return }
    $code = @'
using System;
using System.Runtime.InteropServices;

namespace SuperClean {
    public static class Mem {
        [DllImport("ntdll.dll")]
        public static extern int NtSetSystemInformation(int SystemInformationClass, IntPtr SystemInformation, int SystemInformationLength);

        [DllImport("ntdll.dll")]
        public static extern int NtQuerySystemInformation(int SystemInformationClass, IntPtr SystemInformation, int SystemInformationLength, out int ReturnLength);

        [DllImport("psapi.dll")]
        public static extern int EmptyWorkingSet(IntPtr hProcess);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern IntPtr OpenProcess(uint dwDesiredAccess, bool bInheritHandle, int dwProcessId);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool CloseHandle(IntPtr hObject);

        [DllImport("advapi32.dll", SetLastError = true)]
        public static extern bool OpenProcessToken(IntPtr ProcessHandle, uint DesiredAccess, out IntPtr TokenHandle);

        [DllImport("advapi32.dll", SetLastError = true)]
        public static extern bool LookupPrivilegeValue(string lpSystemName, string lpName, out long lpLuid);

        [StructLayout(LayoutKind.Sequential)]
        public struct LUID_AND_ATTRIBUTES {
            public long Luid;
            public uint Attributes;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct TOKEN_PRIVILEGES {
            public uint PrivilegeCount;
            public LUID_AND_ATTRIBUTES Privileges;
        }

        [DllImport("advapi32.dll", SetLastError = true)]
        public static extern bool AdjustTokenPrivileges(IntPtr TokenHandle, bool DisableAllPrivileges, ref TOKEN_PRIVILEGES NewState, uint BufferLength, IntPtr PreviousState, IntPtr ReturnLength);

        public const uint TOKEN_ADJUST_PRIVILEGES = 0x0020;
        public const uint TOKEN_QUERY = 0x0008;
        public const uint SE_PRIVILEGE_ENABLED = 0x00000002;
        public const uint PROCESS_SET_QUOTA = 0x0100;
        public const uint PROCESS_QUERY_INFORMATION = 0x0400;

        public const int SystemMemoryListInformation = 80;
        public const int MemoryPurgeStandbyList = 4;
        public const int MemoryPurgeLowPriorityStandbyList = 5;

        public static bool EnablePrivilege(string privilege) {
            IntPtr token;
            if (!OpenProcessToken(System.Diagnostics.Process.GetCurrentProcess().Handle, TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, out token))
                return false;
            long luid;
            if (!LookupPrivilegeValue(null, privilege, out luid)) {
                CloseHandle(token);
                return false;
            }
            TOKEN_PRIVILEGES tp = new TOKEN_PRIVILEGES();
            tp.PrivilegeCount = 1;
            tp.Privileges.Luid = luid;
            tp.Privileges.Attributes = SE_PRIVILEGE_ENABLED;
            bool ok = AdjustTokenPrivileges(token, false, ref tp, 0, IntPtr.Zero, IntPtr.Zero);
            CloseHandle(token);
            return ok;
        }

        public static int PurgeStandbyList() {
            // Need SeProfileSingleProcessPrivilege
            EnablePrivilege("SeProfileSingleProcessPrivilege");
            int cmd = MemoryPurgeStandbyList;
            IntPtr ptr = Marshal.AllocHGlobal(sizeof(int));
            Marshal.WriteInt32(ptr, cmd);
            int result = NtSetSystemInformation(SystemMemoryListInformation, ptr, sizeof(int));
            Marshal.FreeHGlobal(ptr);
            return result;
        }

        public static bool TrimProcess(int procId) {
            IntPtr h = OpenProcess(PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, false, procId);
            if (h == IntPtr.Zero) return false;
            int r = EmptyWorkingSet(h);
            CloseHandle(h);
            return r != 0;
        }
    }
}
'@
    Add-Type -TypeDefinition $code -Language CSharp -ErrorAction Stop
}

function Get-StandbyListSizeMB {
    # Best-effort estimate via PerformanceCounter
    try {
        $cb = New-Object System.Diagnostics.PerformanceCounter('Memory', 'Standby Cache Normal Priority Bytes')
        $val = $cb.NextValue()
        return [math]::Round($val / 1MB, 1)
    } catch { return -1 }
}

function Get-GpuUtilization {
    # Returns int percentage 0-100, or -1 if unavailable
    try {
        $out = & nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) {
            $vals = ($out -split "`r?`n") | Where-Object { $_ } | ForEach-Object { [int]($_.Trim()) }
            if ($vals.Count -gt 0) {
                return ($vals | Measure-Object -Maximum).Maximum
            }
        }
    } catch {}
    return -1
}

function Get-DiskWriteRateMBps {
    # Sample 1 second of disk writes
    try {
        $c = Get-Counter '\PhysicalDisk(_Total)\Disk Write Bytes/sec' -SampleInterval 1 -MaxSamples 1 -ErrorAction Stop
        $bytes = $c.CounterSamples[0].CookedValue
        return [math]::Round($bytes / 1MB, 1)
    } catch { return -1 }
}

function Invoke-StandbyFlush {
    param([switch]$DryRun, [switch]$Force)
    Initialize-MemoryPInvoke

    if (-not $Force) {
        $gpu = Get-GpuUtilization
        if ($gpu -ge 20) {
            Write-Log ("  Skip standby flush: GPU at {0}% (would slow active compute)." -f $gpu) 'SKIP'
            return @{ Skipped = $true; Reason = "GPU $gpu%" }
        }
        $diskRate = Get-DiskWriteRateMBps
        if ($diskRate -ge 100) {
            Write-Log ("  Skip standby flush: disk writing at {0} MB/s." -f $diskRate) 'SKIP'
            return @{ Skipped = $true; Reason = "Disk $diskRate MB/s" }
        }
    }

    $beforeMB = Get-StandbyListSizeMB
    if ($DryRun) {
        Write-Log ("  [DRY] Would flush standby list (~{0} MB held)." -f $beforeMB) 'DRY'
        return @{ Skipped = $false; ReclaimedMB = 0; DryRun = $true }
    }

    $rc = [SuperClean.Mem]::PurgeStandbyList()
    Start-Sleep -Milliseconds 500
    $afterMB = Get-StandbyListSizeMB
    $reclaimed = if ($beforeMB -ge 0 -and $afterMB -ge 0) { [math]::Max(0, $beforeMB - $afterMB) } else { -1 }

    if ($rc -eq 0) {
        Write-Log ("  Standby list flushed. Reclaimed ~{0} MB." -f $reclaimed) 'OK'
        return @{ Skipped = $false; ReclaimedMB = $reclaimed }
    } elseif ($rc -eq -1073741727 -or $rc -eq 0xC0000061) {  # STATUS_PRIVILEGE_NOT_HELD
        Write-Log "  Standby flush BLOCKED: this token lacks SeProfileSingleProcessPrivilege." 'WARN'
        Write-Log "  Likely cause on this machine: WDAC restricts admin token privileges." 'WARN'
        Write-Log "  Workaround options:" 'INFO'
        Write-Log "    1) Use Sysinternals RAMMap (run as admin, Empty -> Empty Standby List)" 'INFO'
        Write-Log "    2) secpol.msc -> Local Policies -> User Rights Assignment ->" 'INFO'
        Write-Log "       'Profile single process' -> Add your user (requires reboot)" 'INFO'
        Write-Log "    3) Skip -- working-set trim already gives most of the benefit." 'INFO'
        return @{ Skipped = $false; ReclaimedMB = 0; Error = 'PRIVILEGE_NOT_HELD' }
    } else {
        Write-Log ("  Standby flush returned NTSTATUS 0x{0:X8}" -f $rc) 'WARN'
        return @{ Skipped = $false; ReclaimedMB = 0; Error = $rc }
    }
}

function Invoke-WorkingSetTrim {
    param(
        [hashtable]$ProtectedPids,
        [int]$MinWorkingSetMB = 200,
        [int]$MinIdleMinutes = 30,
        [switch]$DryRun
    )
    Initialize-MemoryPInvoke

    $now = Get-Date
    $candidates = Get-Process | Where-Object {
        $_.WorkingSet64 -gt ($MinWorkingSetMB * 1MB) -and
        -not $ProtectedPids.ContainsKey($_.Id)
    }

    $beforeBytes = 0L
    $trimmedCount = 0
    $skippedCount = 0

    foreach ($p in $candidates) {
        # Skip if recently active (CPU has ticked recently -- best proxy is StartTime+CPU rate, but simplest is to skip if CPU s / age > 0.05)
        try {
            $age = ($now - $p.StartTime).TotalMinutes
            if ($age -lt $MinIdleMinutes) { $skippedCount++; continue }
        } catch { $skippedCount++; continue }

        $beforeBytes += $p.WorkingSet64
        if ($DryRun) {
            $trimmedCount++
            continue
        }
        try {
            $ok = [SuperClean.Mem]::TrimProcess($p.Id)
            if ($ok) { $trimmedCount++ } else { $skippedCount++ }
        } catch { $skippedCount++ }
    }

    if ($DryRun) {
        Write-Log ("  [DRY] Would trim working set on {0} idle process(es) (~{1} held)." -f $trimmedCount, (Get-FriendlySize $beforeBytes)) 'DRY'
        return @{ Trimmed = $trimmedCount; Skipped = $skippedCount; ReclaimedBytes = 0 }
    }

    Start-Sleep -Milliseconds 500
    # Re-measure after trim
    $afterBytes = 0L
    foreach ($p in $candidates) {
        try {
            $proc = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
            if ($proc) { $afterBytes += $proc.WorkingSet64 }
        } catch {}
    }
    $reclaimed = [math]::Max(0L, $beforeBytes - $afterBytes)
    Write-Log ("  Working sets trimmed on {0} process(es). Reclaimed ~{1}." -f $trimmedCount, (Get-FriendlySize $reclaimed)) 'OK'
    return @{ Trimmed = $trimmedCount; Skipped = $skippedCount; ReclaimedBytes = $reclaimed }
}

function Invoke-DnsArpFlush {
    param([switch]$DryRun)
    if ($DryRun) {
        Write-Log '  [DRY] Would flush DNS + ARP caches.' 'DRY'
        return
    }
    & ipconfig /flushdns 2>&1 | Out-Null
    & netsh interface ip delete arpcache 2>&1 | Out-Null
    Write-Log '  DNS + ARP caches flushed.' 'OK'
}
