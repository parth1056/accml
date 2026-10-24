# Predictive Cloud Resource Manager

Real HTTP workload, ML demand forecasting and SLA-aware replica scaling on a local Kubernetes cluster. Approved topic: **ML-Based Predictive Cloud Resource Management with SLA-Aware Auto-Scaling, Cost Optimization, and Adaptive Workload Handling.**

## Run

Requires Python 3.11+, NumPy/Matplotlib, Docker Desktop (Linux containers), Minikube and kubectl.

```powershell
python -m pip install -r requirements.txt
.\SetupLab.ps1
python -m scaler.experiment calibrate --backend kubernetes --rates 6 12 18 24 30 --seconds 40
python -m scaler.forecast --safe-rps 14.4
.\RunDemo.ps1
```

Use the safe rate reported by calibration when training on another machine. RunDemo.ps1 reads the saved calibration. The calibrated rate on this machine is 14.4 RPS per replica. Container CPU limit: 250m. Workload: 60,000-iteration PBKDF2; one active CPU task per worker. Each pod has an explicitly configured five-second readiness delay, and comparisons use preloaded images.

The read-only viewer runs with `python -m scaler.viewer` at **http://127.0.0.1:8787**. Run it in another terminal while the demo runs.

For real worker processes without Kubernetes:

```powershell
python -m scaler.experiment run --backend local --safe-rps 24 --duration 240 --warmup 60
```

## Comparisons and checks

```powershell
python -m unittest discover -s tests -v
python -m scaler.matrix --backend kubernetes --safe-rps 14.4
python -m scaler.analyze
```

Each run saves arrivals, actual sends/completions, raw latency/errors, model coefficients, decisions, resource snapshots and summary metrics under output/live/. Identical scenario/seed/settings produce identical planned arrival schedules. Matrix order is randomized with a fixed seed. Warm-up is excluded from scored outcomes and preserved in raw data. Failed/aborted runs have no summary and are excluded from comparisons.

## Model and controller

- Ridge regression predicts peak offered RPS over the next three 10-second windows from six completed windows and their rolling statistics. Separate synthetic traces supply training, validation and test data; no scenario schedule is a feature.
- Validation chooses regularization and an empirical underprediction buffer. The saved model is reused for matching calibration/horizon settings. This is offline training followed by online inference, not continuous retraining on production traffic.
- Guarded prediction combines forecast capacity with observed-demand rescue, p95/error rescue, a hard budget/replica cap, pending-pod handling and conservative downscale. Reactive/fixed/plain-predictive baselines use the same service.
- Only the dedicated acc-lab context and namespace are controlled. Kubeconfig/certificates and helper PIDs stay in ignored runtime/; no cloud credentials are needed.

## Interpretation

Application latency, errors, CPU and replica changes are measured. Traffic is synthetic replay, not production data. Cost uses an illustrative per-replica rate; energy uses assumed power and sampled process CPU. These are not actual cloud bills or measured physical energy. All pods share one laptop; the controller scales application replicas, not physical nodes. The reactive baseline is custom, not Kubernetes HPA. The separate planning_pilot/ outputs are simulations and must not be presented as live results.

The earlier documents in docs/ are historical planning material. The working application is in scaler/ and k8s/.
