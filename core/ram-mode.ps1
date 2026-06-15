# core/ram-mode.ps1 - --ram dedicated mode (no disk cleanup)

function Invoke-RamMode {
    param(
        [hashtable]$ProtectedPids,
        [switch]$DryRun
    )

    Write-Section 'SUPERCLEAN -- RAM MODE'

    $memBefore = Get-MemorySnapshot
    Write-Log ("Before: {0} / {1} GB used ({2} GB free)" -f $memBefore.UsedGB, $memBefore.TotalGB, $memBefore.FreeGB)

    # 1. Smart-orphan kill
    Write-Log ''
    Write-Log '== Smart orphan kill ==' 'HEAD'
    $orphans = @(Find-OrphanProcs -ProtectedPids $ProtectedPids)
    $killResult = Remove-OrphanProcs -Orphans $orphans -DryRun:$DryRun

    # 2. Standby list flush (with GPU/IO guard)
    Write-Log ''
    Write-Log '== Standby list flush ==' 'HEAD'
    $sb = Invoke-StandbyFlush -DryRun:$DryRun

    # 3. Working-set trim
    Write-Log ''
    Write-Log '== Working-set trim (idle >30 min, >200 MB) ==' 'HEAD'
    $ws = Invoke-WorkingSetTrim -ProtectedPids $ProtectedPids -DryRun:$DryRun

    # 4. Idle Ollama unload
    Write-Log ''
    Write-Log '== Idle Ollama unload ==' 'HEAD'
    $oll = Invoke-OllamaIdleUnload -DryRun:$DryRun

    # 5. DNS / ARP flush
    Write-Log ''
    Write-Log '== DNS / ARP flush ==' 'HEAD'
    Invoke-DnsArpFlush -DryRun:$DryRun

    # Summary
    Start-Sleep -Milliseconds 500
    $memAfter = Get-MemorySnapshot
    $delta = [math]::Round($memAfter.FreeGB - $memBefore.FreeGB, 2)
    Write-Log ''
    Write-Section 'RAM MODE SUMMARY'
    Write-Log ("After:  {0} / {1} GB used ({2} GB free)" -f $memAfter.UsedGB, $memAfter.TotalGB, $memAfter.FreeGB)
    if ($delta -gt 0) {
        Write-Log ("Net free RAM gained: +{0} GB" -f $delta) 'OK'
    } elseif ($delta -lt 0) {
        Write-Log ("Net free RAM delta:  {0} GB (load increased during run)" -f $delta) 'INFO'
    } else {
        Write-Log "No net RAM change measured." 'INFO'
    }
    Write-Log ("Orphans killed:      {0}" -f $killResult.Killed)
    Write-Log ("Working sets trimmed: {0}" -f $ws.Trimmed)
    Write-Log ("Ollama unloaded:     {0}" -f $oll.Unloaded)
}

function Invoke-GpuReset {
    Write-Section 'GPU DEVICE TREE RESET'
    if (-not (Test-IsAdmin)) {
        Write-Log 'GPU reset requires Administrator. Re-run elevated.' 'ERROR'
        return
    }

    $code = @'
using System;
using System.Runtime.InteropServices;
public class CfgMgr32 {
    [DllImport("cfgmgr32.dll", SetLastError = true)]
    public static extern int CM_Locate_DevNode(out IntPtr pdnDevInst, string pDeviceID, int ulFlags);
    [DllImport("cfgmgr32.dll", SetLastError = true)]
    public static extern int CM_Reenumerate_DevNode(IntPtr dnDevInst, int ulFlags);
}
'@
    if (-not ('CfgMgr32' -as [type])) {
        Add-Type -TypeDefinition $code -Language CSharp
    }

    $devInst = [IntPtr]::Zero
    $r1 = [CfgMgr32]::CM_Locate_DevNode([ref]$devInst, $null, 0)
    Write-Log ("CM_Locate_DevNode: result={0} (0=success)" -f $r1)

    $r2 = [CfgMgr32]::CM_Reenumerate_DevNode($devInst, 2)
    Write-Log ("CM_Reenumerate_DevNode (RETRY_INSTALLATION): result={0} (0=success)" -f $r2)

    Start-Sleep -Seconds 3

    $vc = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue
    foreach ($v in $vc) {
        Write-Log ("  GPU: {0,-40} Status={1} DriverVer={2}" -f $v.Name, $v.Status, $v.DriverVersion)
    }
}
