Set-Location -LiteralPath $PSScriptRoot
$ErrorActionPreference='Stop'
New-Item -ItemType Directory -Force runtime | Out-Null
$env:MINIKUBE_HOME=Join-Path $PSScriptRoot 'runtime\minikube'
$env:KUBECONFIG=Join-Path $PSScriptRoot 'runtime\kubeconfig'
minikube start -p acc-lab --driver=docker --cpus=2 --memory=2300mb --kubernetes-version=v1.34.0 --embed-certs
if ($LASTEXITCODE -ne 0) { throw 'Minikube startup failed.' }
docker build -t acc-scaler:lab .
if ($LASTEXITCODE -ne 0) { throw 'Image build failed.' }
minikube image load acc-scaler:lab -p acc-lab
if ($LASTEXITCODE -ne 0) { throw 'Image load failed.' }
kubectl --kubeconfig $env:KUBECONFIG --context acc-lab apply -f k8s/application.yaml
if ($LASTEXITCODE -ne 0) { throw 'Deployment failed.' }
kubectl --kubeconfig $env:KUBECONFIG --context acc-lab -n acc-lab rollout status deployment/worker --timeout=90s
kubectl --kubeconfig $env:KUBECONFIG --context acc-lab -n acc-lab rollout status deployment/gateway --timeout=90s
& (Join-Path $PSScriptRoot 'StartLabConnections.ps1')
