Set-Location -LiteralPath $PSScriptRoot
$ErrorActionPreference='Stop'
New-Item -ItemType Directory -Force runtime | Out-Null
$labKubeconfig=Join-Path $PSScriptRoot 'runtime\kubeconfig'
$labKubectl=(Get-Command kubectl).Source
$labArguments=@('--kubeconfig',('"'+$labKubeconfig+'"'),'--context','acc-lab')
try { $labProxy=Invoke-RestMethod 'http://127.0.0.1:18001/api/v1/namespaces/acc-lab' -TimeoutSec 2 } catch { $labProxy=$null }
if ($null -eq $labProxy) {
    $labProcess=Start-Process -FilePath $labKubectl -ArgumentList ($labArguments+@('proxy','--port=18001','--address=127.0.0.1')) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $PSScriptRoot 'runtime\proxy.log') -RedirectStandardError (Join-Path $PSScriptRoot 'runtime\proxy-error.log')
    $labProcess.Id | Set-Content runtime/proxy.pid
}
try { $labGateway=Invoke-RestMethod 'http://127.0.0.1:18080/health' -TimeoutSec 2 } catch { $labGateway=$null }
if ($null -eq $labGateway) {
    $labProcess=Start-Process -FilePath $labKubectl -ArgumentList ($labArguments+@('-n','acc-lab','port-forward','service/gateway','18080:8080','--address=127.0.0.1')) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $PSScriptRoot 'runtime\gateway-forward.log') -RedirectStandardError (Join-Path $PSScriptRoot 'runtime\gateway-forward-error.log')
    $labProcess.Id | Set-Content runtime/gateway-forward.pid
}
Write-Output 'Local API proxy: 127.0.0.1:18001; application gateway: 127.0.0.1:18080'
