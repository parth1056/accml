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

For a first look, open that viewer: it also shows the completed experiments without rerunning them. The implementation report is `output/ACC_Lab_CA_Implementation_Report.pdf`. The 18-slide presentation in `output/presentation/ACC_Lab_CA_Presentation.pptx` covers the demonstration with captured screenshots, ML methodology, results and speaker notes: Parth presents slides 1–6, Purab 7–12 and Pushkar 13–18. The time-lapse is optional supporting footage.

To test recommendations without changing an existing lab deployment:

```powershell
.\StartLabConnections.ps1
.\RunDemo.ps1 -Mode shadow
```

Shadow mode sends real test traffic and records proposed targets, but never changes replicas, including at startup or cleanup. It requires an already running Kubernetes lab. Active mode remains the default for reproducing the recorded benchmarks. The viewer labels shadow results separately.

For real worker processes without Kubernetes:

```powershell
python -m scaler.experiment run --backend local --safe-rps 24 --duration 240 --warmup 60
```

## Comparisons and checks

```powershell
python -m unittest discover -s tests -v
python -m scaler.matrix --backend kubernetes --safe-rps 14.4
python -m scaler.analyze
python tools/evaluate_matrix.py
python tools/run_fault_checks.py
python tools/train_recorded_candidate.py
python tools/forecast_diagnostics.py
python tools/build_submission_report.py
```

Each run saves arrivals, actual sends/completions, raw latency/errors, model coefficients, decisions, resource snapshots and summary metrics under output/live/. Identical scenario/seed/settings produce identical planned arrival schedules. Matrix order is randomized with a fixed seed. Warm-up is excluded from scored outcomes and preserved in raw data. Failed/aborted runs have no summary and are excluded from comparisons.

The matrix evaluator verifies identical arrival schedules, model weights and source fingerprints before producing the comparison. Fault checks separately replay a deliberately zeroed forecast and a one-replica budget cap. Their summary scenario labels describe the injection; configs retain the underlying periodic workload. The report builder requires completed comparisons, fault checks and execution screenshots; it does not invent missing results. ReportLab is used only for this optional report export, not by the running service.

An additional recorded-traffic model is saved as output/recorded_model_candidate.json. It uses distinct training/validation/test seeds, and remains an exploratory candidate: the published 12-run benchmark and default demo keep their original frozen model. Calibration retains only results from the same host and workload fingerprint; repeat boundary rates to confirm stability. Raw result files preserve their original bytes in Git so schedule/model hashes remain verifiable after download.

The added forecast diagnostics use 64 aligned targets from the four frozen guarded runs: Ridge MAE is 11.24 RPS, persistence 9.39, and a trailing five-window mean 12.06. Ridge improves on persistence during falling-demand slices, but does not win overall. These replay results support the complete guarded controller's measured trade-off, not a claim that ML universally beats simple forecasting. The separate recorded-data candidate needs fresh matched controller runs before promotion.

## Model and controller

- Ridge regression predicts peak offered RPS over the next three 10-second windows from six completed windows and their rolling statistics. Separate synthetic traces supply training, validation and test data; no scenario schedule is a feature.
- Validation chooses regularization and an empirical underprediction buffer. The saved model is reused for matching calibration/horizon settings. This is offline training followed by online inference, not continuous retraining on production traffic.
- Guarded prediction combines forecast capacity with observed-demand rescue, p95/error rescue, a hard budget/replica cap, pending-pod handling and conservative downscale. Reactive/fixed/plain-predictive baselines use the same service.
- Inference exceptions and invalid forecasts fall back to observed demand while preventing model-failure downscale; stale/invalid demand holds current capacity. A zero forecast remains a valid deliberate stress case.
- Only the dedicated acc-lab context and namespace are controlled. Kubeconfig/certificates and helper PIDs stay in ignored runtime/; no cloud credentials are needed.

## Interpretation

Application latency, errors, CPU and replica changes are measured. Traffic is synthetic replay, not production data. Cost uses an illustrative per-replica rate; energy uses assumed power and sampled process CPU. These are not actual cloud bills or measured physical energy. All pods share one laptop; the controller scales application replicas, not physical nodes. The reactive baseline is custom, not Kubernetes HPA. The separate planning_pilot/ outputs are simulations and must not be presented as live results.

The working application is in scaler/ and k8s/. Completed results, the implementation PDF and captured demo footage are in output/.

Shadow mode and the additional past-only moving-average/phase diagnostics were informed by reviewing [Pushkar's CloudShop plan](https://github.com/git-push-kar/cloudshop). Its API is a possible future workload; adopting it requires fresh calibration and comparisons. Our completed measurements use the CPU service described above. The original matrix, model and report measurements remain frozen; the shadow check and extra diagnostics are separate evidence.
