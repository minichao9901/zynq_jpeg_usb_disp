$ErrorActionPreference = 'Stop'
$node = Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB\VID_303A&PID_2986&MI_00\*' }
if (@($node).Count -gt 1) { throw 'Disconnect the other 303A:2986 reference display before loading.' }
$restore = $node -and $node.Status -eq 'OK'
if ($restore) {
    & pnputil /disable-device $node.InstanceId
    if ($LASTEXITCODE -ne 0) { throw 'Unable to suspend USB display before RAM loading.' }
}
& python "$PSScriptRoot/run_xsct.py" "$PSScriptRoot/load.tcl"
if ($LASTEXITCODE -ne 0) { throw 'RAM load failed; IDD remains disabled.' }
if ($restore) {
    & python "$PSScriptRoot/enable_display.py"
    if ($LASTEXITCODE -ne 0) { throw 'Board loaded, but unable to restore extended desktop.' }
}
