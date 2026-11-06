param([int]$Frames = 300, [string]$Out = 'build/acceptance')
$ErrorActionPreference = 'Stop'
$node = Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB\VID_303A&PID_2986&MI_00\*' }
if (-not $node) { throw 'Zynq IDD display MI_00 not found. Load tools/load.tcl first.' }
if (@($node).Count -ne 1) { throw 'Multiple 303A:2986 displays are connected; disconnect the other reference board before testing.' }
$reenable = $false
try {
    if ($node.Status -eq 'OK') {
        & pnputil /disable-device $node.InstanceId
        if ($LASTEXITCODE -ne 0) { throw 'Unable to suspend IDD for deterministic tests' }
        $reenable = $true
    }
    & python "$PSScriptRoot/acceptance.py" --frames $Frames --out $Out
    if ($LASTEXITCODE -ne 0) { throw 'USB display acceptance failed; see report.json' }
} finally {
    if ($reenable) {
        & python "$PSScriptRoot/enable_display.py"
        if ($LASTEXITCODE -ne 0) { Write-Error 'Unable to restore extended desktop; MI_00 has been disabled for recovery.' }
    }
}
