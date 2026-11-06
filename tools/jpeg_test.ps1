param([string]$Out = 'build/jpeg-acceptance')
$ErrorActionPreference = 'Stop'
$node=Get-PnpDevice -PresentOnly | Where-Object {$_.InstanceId -like 'USB\VID_303A&PID_2986&MI_00\*'}
if (@($node).Count -ne 1) {throw 'Connect exactly one Zynq USB Display.'}
$restore=$node.Status -eq 'OK'
try {
    if ($restore) {
        & pnputil /disable-device $node.InstanceId
        if ($LASTEXITCODE -ne 0) {throw 'Unable to pause IDD.'}
    }
    & python "$PSScriptRoot/jpeg_acceptance.py" --out $Out
    if ($LASTEXITCODE -ne 0) {throw 'JPEG acceptance failed.'}
} finally {
    if ($restore) {& python "$PSScriptRoot/enable_display.py"}
}
