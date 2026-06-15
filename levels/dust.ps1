# levels/dust.ps1 - Gentlest level: Recycle Bin >7d, tiny sub-caches, temp prune

function Clear-RecycleBinOlderThan {
    param([int]$Days = 7, [switch]$DryRun)
    $shell = New-Object -ComObject Shell.Application
    $bin = $shell.Namespace(10)
    if (-not $bin) { return 0L }
    $cutoff = (Get-Date).AddDays(-$Days)
    $reclaimed = 0L
    $count = 0

    # Iterate items (need to do this carefully - collection changes as we delete)
    $itemsToDelete = @()
    foreach ($item in $bin.Items()) {
        try {
            # ExtendedProperty 'System.Recycle.DateDeleted' = property index 'ItemDate' (often)
            $deletedDate = $item.ModifyDate  # Best-effort
            if ($deletedDate -is [DateTime] -and $deletedDate -lt $cutoff) {
                $itemsToDelete += @{ Path = $item.Path; Size = $item.Size }
            }
        } catch {}
    }

    foreach ($i in $itemsToDelete) {
        if ($DryRun) {
            $reclaimed += $i.Size
            $count++
        } else {
            try {
                Remove-Item -LiteralPath $i.Path -Recurse -Force -ErrorAction Stop
                $reclaimed += $i.Size
                $count++
            } catch {}
        }
    }

    return @{ Items = $count; Bytes = $reclaimed }
}

function Invoke-LevelDust {
    param([switch]$DryRun)

    Write-Section "LEVEL: --dust"
    $startSnap = Get-FreeSpaceSnapshot

    Write-Log ''
    Write-Log '== Recycle Bin items older than 7 days ==' 'HEAD'
    $rb = Clear-RecycleBinOlderThan -Days 7 -DryRun:$DryRun
    $verb = if ($DryRun) { 'Would reclaim' } else { 'Reclaimed' }
    Write-Log ("  Items: {0}  {1}: {2}" -f $rb.Items, $verb, (Get-FriendlySize $rb.Bytes)) 'OK'

    Write-Log ''
    Write-Log '== $env:TEMP older than 3 days ==' 'HEAD'
    $cutoff = (Get-Date).AddDays(-3)
    $tempBytes = 0L
    $tempCount = 0
    $tempSkipped = 0
    Get-ChildItem -Path $env:TEMP -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoff } | ForEach-Object {
            $sz = $_.Length
            if ($DryRun) {
                $tempBytes += $sz; $tempCount++
            } else {
                try { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop; $tempBytes += $sz; $tempCount++ }
                catch { $tempSkipped++ }
            }
        }
    Write-Log ("  Files: {0}  Reclaimed: {1}  Skipped(locked): {2}" -f $tempCount, (Get-FriendlySize $tempBytes), $tempSkipped) 'OK'

    Write-Log ''
    Write-Log '== Cursor / Claude tiny sub-caches (always safe) ==' 'HEAD'
    $tinyTargets = @(
        (Join-Path $env:APPDATA 'Cursor\GPUCache'),
        (Join-Path $env:APPDATA 'Cursor\Crashpad'),
        (Join-Path $env:APPDATA 'Claude\Crashpad'),
        (Join-Path $env:APPDATA 'Claude\GPUCache')
    )
    $tinyBytes = 0L
    foreach ($t in $tinyTargets) {
        if (Test-Path -LiteralPath $t) {
            $r = Remove-DirContents -Path $t -DryRun:$DryRun
            $tinyBytes += $r.DeletedBytes
            $tag = if ($DryRun) { '[DRY] ' } else { '' }
            Write-Log ("  {0}{1}  {2}" -f $tag, $t, (Get-FriendlySize $r.DeletedBytes))
        }
    }
    Write-Log ("  Total tiny caches: {0}" -f (Get-FriendlySize $tinyBytes)) 'OK'

    $endSnap = Get-FreeSpaceSnapshot
    Write-Log ''
    Write-Log '== Dust delta ==' 'HEAD'
    foreach ($drv in $startSnap.Keys) {
        $delta = $endSnap[$drv] - $startSnap[$drv]
        if ($delta -ne 0) {
            Write-Log ("  {0} freed: {1}" -f $drv, (Get-FriendlySize $delta))
        }
    }
}
