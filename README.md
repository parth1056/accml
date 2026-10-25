# Predictive Cloud Resource Manager

An ML-based controller that predicts incoming HTTP demand and scales application workers on a real local Kubernetes cluster. A trained Ridge model works alongside observed-demand and latency safeguards to balance service quality and allocated capacity.

Built for Advanced Cloud Computing Lab-CA by **Parth Dhande (16010123232), Purab Madhan (16010123242) and Pushkar Rai (16010123243)**.

Approved topic: **ML-Based Predictive Cloud Resource Management with SLA-Aware Auto-Scaling, Cost Optimization, and Adaptive Workload Handling.**

## Start here

- [Implementation report (PDF)](output/report/ACC_Lab_CA_Report.pdf): methods, execution screenshots, results and limitations.
- [Editable report (Word)](output/report/ACC_Lab_CA_Report.docx).
- [Presentation](output/presentation/ACC_Lab_CA_Presentation.pptx): 18 slides covering the demonstration. Presenter split: Parth 1–6, Purab 7–12, Pushkar 13–18.
- [Benchmark audit and results](output/evaluation/audit.json): the verified 12-run comparison.

These are the current submission files. `output/ACC_Lab_CA_Implementation_Report.pdf` and `output/presentation/ACC_Lab_CA_Final.pptx` are earlier versions.

To inspect saved experiments without Docker or new traffic, install the Python requirements and run `python -m scaler.viewer`. Open **http://127.0.0.1:8787**. The viewer reads recorded experiment files; Docker is needed only for new Kubernetes runs.

## How it works

```text
HTTP load generator -> Gateway -> Service -> Ready worker pods
        |                                      |
        +---- demand, latency and errors ------+---- CPU and pod state
                                               |
                                       Ridge forecast + policy
                                               |
                                   Deployment replica target
```

Every 10 seconds, Ridge uses six completed demand windows plus their mean, standard deviation, maximum and slope: **10 features covering 60 seconds of history**. It predicts the **peak request rate over the next 30 seconds**. Future arrivals and known burst times are never model inputs.

The guarded policy converts demand into a worker count using calibrated per-worker capacity. It adds an empirical forecast buffer, lets observed demand and latency/errors request capacity, tracks pending pods, and stabilizes downscaling for 30 seconds. Normal runs allow **1–4 workers**, with a **250 ms p95 latency target** and **at least 99% successful requests**. Invalid forecasts fall back to observed demand without triggering model-failure downscale; stale or invalid demand holds current capacity. A hard cap can make the service targets infeasible.

Each worker performs 60,000 PBKDF2-HMAC-SHA256 iterations per request, with a 250m CPU limit and a five-second readiness delay. The gateway routes traffic to ready endpoints. These are real HTTP requests and pod changes on **Docker Desktop + Minikube**, all on one laptop. The system scales application replicas, not cloud VMs or physical nodes. No AWS or Azure account is required.

## Run a new Kubernetes demo

### Prerequisites

Use Windows PowerShell with Git, Python 3.11+, Minikube and kubectl available on `PATH`. Start Docker Desktop with **Linux containers**. The Minikube profile requires 2 CPUs and 2300 MB memory, plus host/Docker overhead. First-time setup downloads Kubernetes components and builds the image. The supplied PowerShell helpers target Windows.

The repository default branch is `parth/predictive-scaler`.

### Install and start

```powershell
git clone --branch parth/predictive-scaler https://github.com/parth1056/accml.git
cd accml
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
.\SetupLab.ps1
```

Setup creates the dedicated `acc-lab` Minikube profile and namespace, builds and loads the image, deploys the gateway and worker, and starts local connection helpers. Kubeconfig and helper logs stay in ignored `runtime/`. If PowerShell blocks scripts, use a shell configuration that permits your local project scripts. Python commands can use `.\.venv\Scripts\python.exe` directly instead of environment activation.

### Calibrate, train and run

Measure the current machine instead of assuming another laptop has the same capacity:

```powershell
python -m scaler.experiment calibrate --backend kubernetes --rates 6 12 18 24 30 --seconds 40
$labSafeRps = (Get-Content output/live/calibration-kubernetes.json -Raw | ConvertFrom-Json).recommended_safe_rps
if ($null -eq $labSafeRps -or $labSafeRps -le 0) { throw 'No passing calibration rate. Inspect the results.' }
python -m scaler.forecast --safe-rps $labSafeRps
.\RunDemo.ps1
```

Calibration selects 80% of the highest passing rate; repeat boundary rates to check stability. The recorded machine selected **14.4 RPS per worker**, based on a repeatably passing 18 RPS. Training saves `output/trained_model.json` and its holdout evaluation. The runner reuses the saved model when its capacity and horizon match; otherwise it trains a compatible model.

The default demo is a **four-minute flash workload** with guarded predictive scaling. The first 60 seconds collect history and are excluded from scored results. Terminal output shows decision reasons, ready/pending workers and target counts. Active runs return the deployment to one worker on completion.

In a second terminal, from this repository and the same Python environment:

```powershell
python -m scaler.viewer
```

Open **http://127.0.0.1:8787**. During warm-up the forecast is blank, but observed demand still drives allocation. Cards show the observed state before the latest decision is applied, so a newly requested target can differ from the displayed ready/desired count.

### Other modes

```powershell
.\RunDemo.ps1 -Scenario periodic -Policy reactive
.\RunDemo.ps1 -Scenario ramp -Policy guarded_predictive
.\RunDemo.ps1 -Mode shadow
```

Policies: `fixed`, `reactive`, `plain_predictive`, `guarded_predictive`. Shadow mode requires an existing running deployment. It sends real test traffic and records recommendations, but never changes replicas, including at startup or cleanup. A dedicated check recorded seven recommendations and zero scaling actions.

If connection helpers have stopped, run `.\StartLabConnections.ps1`. The gateway uses `127.0.0.1:18080`, the local Kubernetes API proxy `127.0.0.1:18001`, and the viewer port `8787`. Check `runtime/*-error.log` if the gateway or proxy is unavailable. If the viewer port is occupied, use the existing viewer or stop that viewer before starting another.

Stop the viewer with Ctrl+C. To stop the project's cluster from the repository root:

```powershell
$env:MINIKUBE_HOME = Join-Path $PWD 'runtime\minikube'
minikube stop -p acc-lab
```

### Without Docker

The local backend starts real host worker processes instead of Kubernetes pods. It is useful for development; the submitted benchmark uses Kubernetes. Calibrate this backend separately:

```powershell
python -m scaler.experiment calibrate --backend local --rates 6 12 18 24 30 --seconds 40
$labLocalSafeRps = (Get-Content output/live/calibration-local.json -Raw | ConvertFrom-Json).recommended_safe_rps
if ($null -eq $labLocalSafeRps -or $labLocalSafeRps -le 0) { throw 'No passing local calibration rate.' }
python -m scaler.experiment run --backend local --safe-rps $labLocalSafeRps --scenario flash --duration 240 --warmup 60
```

## Tests and evaluation

The existing tests run without Docker:

```powershell
python -m unittest discover -s tests -v
```

All 17 tests pass. They cover model persistence, past-only features, limits, invalid forecasts, stale metrics, pending capacity, shadow behavior and actual localhost HTTP/CPU work.

To verify and analyze the **saved benchmark**, without generating traffic:

```powershell
python tools/evaluate_matrix.py
python tools/forecast_diagnostics.py
```

The evaluator verifies matching planned arrival schedules, model weights and source fingerprints, then regenerates the audit, comparison tables and plots. Forecast diagnostics align each prediction with its actual future peak and compare past-only baselines.

To generate a **new suite**, first finish Kubernetes setup and calibration. In the same PowerShell session where `$labSafeRps` was set:

```powershell
python -m scaler.matrix --backend kubernetes --safe-rps $labSafeRps
python tools/evaluate_matrix.py
python tools/forecast_diagnostics.py
```

The default matrix takes approximately **48 minutes plus overhead**: three policies, two workloads, two seeds, four minutes per run. It replaces `output/live/matrix.json`; each new run gets a timestamped folder. Keep the committed results separately when comparing a new suite with the submission. `python -m scaler.analyze` produces per-run plots for completed experiments.

`python tools/run_fault_checks.py` separately reproduces the zero-forecast pair and the one-worker budget test on Kubernetes. It takes about ten minutes, uses the recorded 14.4 RPS setting and replaces the fault-check summary. Adapt that script's capacity settings after calibrating a different machine.

## Recorded results

The main suite contains 12 matched Kubernetes runs, with a 240-second duration and 60-second excluded warm-up. All scored requests succeeded. Each range is the minimum/maximum **run p95** over two repeats, not a confidence interval or pooled percentile.

| Workload | Policy | Run p95 range ms | Mean replica-seconds | Mean violating windows |
| --- | --- | ---: | ---: | ---: |
| Flash | Fixed | 42.8–43.2 | 720.0 | 0.00% |
| Flash | Guarded predictive | 44.0–46.9 | 705.3 | 0.00% |
| Flash | Reactive | 64.1–65.8 | 561.3 | 0.00% |
| Periodic | Fixed | 34.6–55.3 | 720.0 | 0.00% |
| Periodic | Guarded predictive | 49.0–56.6 | 643.1 | 0.00% |
| Periodic | Reactive | 71.5–503.9 | 498.8 | 5.56% |

Guarded control used **10.7% fewer replica-seconds than fixed capacity on periodic demand**, and 2.0% fewer on flash demand. Reactive control used less capacity, with a latency excursion in the periodic suite. This is a capacity/service-quality trade-off.

Ridge was trained on 8,544 synthetic rows, validated on 4,272 rows and tested on an independent seed. Synthetic holdout MAE was **1.67 RPS**, versus persistence at **2.61 RPS**. Across 64 aligned targets in the recorded guarded runs, Ridge MAE was **11.24 RPS**, persistence **9.39 RPS**, and a trailing five-window mean **12.06 RPS**. Ridge does not beat persistence overall on these replays; service results evaluate the complete guarded controller.

With deliberately zeroed forecasts, forecast-only control failed **13.35%** of requests. Guarded control had **0%** failures and run p95 **215.1 ms**, although one scored window still violated the target. A separate one-worker budget test failed **17.73%** of requests. Safeguards cannot remove provisioning delay or create capacity forbidden by a cap.

## Repository map

| Location | Purpose |
| --- | --- |
| `scaler/` | HTTP worker/gateway, traffic, model, policy, fleet adapters, runner and viewer. |
| `k8s/application.yaml` | Namespace, Deployments, Services, resource and readiness settings. |
| `SetupLab.ps1`, `StartLabConnections.ps1`, `RunDemo.ps1` | Windows setup, connections and demo helpers. |
| `tests/` | Model, policy, network and planning tests. |
| `tools/` | Audit, forecast diagnostics and additional evaluation scripts. |
| `output/live/` | Raw experiments, calibration, latest run and matrix manifest. |
| `output/evaluation/` | Matched results, audit, forecast diagnostics and separate fault/shadow checks. |
| `output/evidence/` | Execution screenshots and supporting logs. |
| `output/report/`, `output/presentation/` | Current submission report and presentation. |
| `planning_pilot/` | Earlier simulation and reusable regression/features; simulated outcomes stay separate from live measurements. |

Each completed run stores `config.json`, `arrivals.csv`, `requests.csv`, `decisions.csv`, `resources.csv`, `model.json` and `summary.json`. Warm-up remains in raw records but is excluded from scored metrics. Aborted runs lack a completed summary and are excluded from comparisons. Saved absolute paths are resolved by folder name within local `output/live/`, allowing inspection from another checkout. Git preserves raw result bytes for hash verification.

## Interpretation and additional work

Latency, errors, worker CPU and replica changes are measured. Traffic is synthetic. Cost assumes **0.02 illustrative units per replica-hour**. Energy integrates assumed power of **10 W per allocated worker + 20 W per measured CPU core**. These are estimates, not provider bills or physical energy measurements. All pods share one host; the reactive baseline is custom code, not Kubernetes HPA.

Training is offline. `output/recorded_model_candidate.json`, generated by `tools/train_recorded_candidate.py`, is an exploratory model and is not used by the published benchmark. It needs broader validation and fresh matched runs before promotion.

`tools/build_submission_report.py` generates the **earlier ReportLab PDF**, not the current template-based Word/PDF report linked above. It is optional, requires the retained results and screenshots, and is not part of application startup.

Shadow mode and additional moving-average/phase diagnostics were informed by reviewing [Pushkar's CloudShop plan](https://github.com/git-push-kar/cloudshop). The completed measurements here use the CPU service described above; adopting another workload requires fresh calibration and evaluation.
