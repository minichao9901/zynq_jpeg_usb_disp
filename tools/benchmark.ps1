param([int]$Repeat = 3, [int]$Frames = 128, [string]$Out = 'build/throughput-final.json')
$ErrorActionPreference = 'Stop'
$node=Get-PnpDevice -PresentOnly | Where-Object {$_.InstanceId -like 'USB\VID_303A&PID_2986&MI_00\*'}
if (@($node).Count -ne 1) {throw 'Connect exactly one Zynq USB Display.'}
$restore=$node.Status -eq 'OK'
try {
    if ($restore) {
        & pnputil /disable-device $node.InstanceId
        if ($LASTEXITCODE -ne 0) {throw 'Unable to pause IDD.'}
    }
    & python "$PSScriptRoot/throughput_suite.py" --repeat $Repeat --frames $Frames --out $Out
    if ($LASTEXITCODE -ne 0) {throw 'Throughput benchmark failed.'}
} finally {
    if ($restore) {& python "$PSScriptRoot/enable_display.py"}
}
