param(
    [ValidateSet('local','kubernetes')][string]$Backend='kubernetes',
    [ValidateSet('periodic','flash','ramp')][string]$Scenario='flash',
    [ValidateSet('fixed','reactive','guarded_predictive','plain_predictive')][string]$Policy='guarded_predictive',
    [ValidateSet('active','shadow')][string]$Mode='active',
    [double]$SafeRps=0,
    [int]$Seconds=240
)
Set-Location -LiteralPath $PSScriptRoot
if ($SafeRps -le 0) {
    $labCalibration=Get-Content -LiteralPath "output/live/calibration-$Backend.json" -Raw | ConvertFrom-Json
    $SafeRps=$labCalibration.recommended_safe_rps
    if ($SafeRps -le 0) { throw 'Run capacity calibration first.' }
}
if ($Backend -eq 'kubernetes') { & (Join-Path $PSScriptRoot 'StartLabConnections.ps1') }
python -u -m scaler.experiment run --backend $Backend --mode $Mode --scenario $Scenario --policy $Policy --safe-rps $SafeRps --duration $Seconds --warmup 60
if ($LASTEXITCODE -ne 0) { throw 'Experiment failed. Inspect the saved run logs.' }
python -m scaler.analyze
