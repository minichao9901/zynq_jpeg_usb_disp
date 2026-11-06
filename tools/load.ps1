param([ValidateSet('rgb','rgb565','jpeg')][string]$Mode = 'jpeg')
$ErrorActionPreference = 'Stop'
& python "$PSScriptRoot/flash.py" $Mode
if ($LASTEXITCODE -ne 0) {throw 'USB display download failed; see the CLI report.'}
