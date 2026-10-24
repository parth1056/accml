"""Deterministic planning experiment, NOT a live system or latency benchmark.

Demand is synthetic. Capacity is a fluid model with delayed readiness. Allocated
replica time and energy are model outputs; HTTP latency/CPU are not simulated.
"""
from pathlib import Path
import csv
import json
import math
import numpy as np

DT = 10
HORIZON = 3
HISTORY = 6
MAX_REPLICAS = 6
SAFE_RPS = 70.0  # assumed, not calibrated
PHYSICAL_RPS = 100.0  # assumed fluid service capacity
WARMUP = 2  # simulated 20-second startup
POLICIES = ('fixed', 'reactive', 'plain_predictive', 'guarded_predictive')
SCENARIOS = ('ramp', 'periodic', 'flash', 'underprediction', 'overprediction')
OUT = Path(__file__).resolve().parents[1] / 'output'


def features(history):
    """Only consumes history supplied by the caller, ending at completed t."""
    a = np.asarray(history[-HISTORY:], dtype=float)
    if len(a) != HISTORY:
        raise ValueError('Six completed windows are required')
    return np.r_[a, a.mean(), a.std(), a.max(), (a[-1] - a[0]) / 5]


def supervised(trace):
    x, y = [], []
    for t in range(HISTORY - 1, len(trace) - HORIZON):
        x.append(features(trace[:t + 1]))
        y.append(max(trace[t + 1:t + 1 + HORIZON]))
    return np.asarray(x), np.asarray(y)


def training_trace(seed, size=720):
    rng = np.random.default_rng(seed)
    t = np.arange(size)
    period = rng.uniform(35, 90)
    a = rng.uniform(35, 110)
    trace = 140 + a * np.sin(2 * np.pi * t / period + rng.uniform(0, 6))
    trace += 25 * np.sin(2 * np.pi * t / (period * 2.2))
    trace += rng.normal(0, 5, size)
    return np.maximum(2, trace)


def scenario(name, seed, size=180):
    rng = np.random.default_rng(seed)
    t = np.arange(size)
    if name == 'ramp':
        y = np.interp(t, [0, 30, 80, 120, size - 1], [40, 40, 300, 300, 40])
    else:
        y = 130 + 85 * np.sin(2 * np.pi * t / 55)
        if name == 'flash':
            y[65:85] += 270  # unexpected event, no feature reveals its schedule
    return np.maximum(2, y + rng.normal(0, 5, size))


class Ridge:
    def fit(self, x, y, alpha=10):
        self.mean = x.mean(axis=0)
        self.scale = np.maximum(x.std(axis=0), 1e-8)
        z = np.c_[np.ones(len(x)), (x - self.mean) / self.scale]
        penalty = np.eye(z.shape[1]) * alpha
        penalty[0, 0] = 0
        self.coef = np.linalg.solve(z.T @ z + penalty, z.T @ y)
        return self

    def predict(self, x):
        x = np.atleast_2d(x)
        return np.maximum(0, np.c_[np.ones(len(x)), (x - self.mean) / self.scale] @ self.coef)


def fit_model():
    # Entire training traces precede separate validation/test traces in this
    # experimental protocol. No window/label spans any trace boundary.
    xy = [supervised(training_trace(s)) for s in range(12)]
    x = np.concatenate([a for a, b in xy])
    y = np.concatenate([b for a, b in xy])
    vx, vy = supervised(training_trace(50))
    candidates = []
    for alpha in (1, 10, 100):
        model = Ridge().fit(x, y, alpha)
        p = model.predict(vx)
        candidates.append((float(np.mean(abs(p - vy))), alpha, model))
    mae, alpha, model = min(candidates, key=lambda z: z[0])
    pred = model.predict(vx)
    buffer = float(np.quantile(np.maximum(vy - pred, 0), .9))
    persistence = vx[:, HISTORY - 1]
    info = dict(algorithm='standardized Ridge', alpha=alpha,
                train_seeds=list(range(12)), validation_seed=50,
                test_seeds=[101, 202, 303], horizon_seconds=30,
                validation_mae=mae,
                validation_rmse=float(np.sqrt(np.mean((pred - vy) ** 2))),
                persistence_validation_mae=float(np.mean(abs(persistence - vy))),
                validation_positive_residual_q90=buffer,
                mean=model.mean.tolist(), scale=model.scale.tolist(),
                coefficients=model.coef.tolist(),
                limitations='Synthetic traces; no HTTP latency, cloud bill or measured CPU.')
    return model, buffer, info


def recommend(policy, observed, forecast, buffer, allocated, stale=False, cap=MAX_REPLICAS):
    """Pure recommendation, before common readiness/stabilization rules."""
    if stale:
        return allocated, 'METRICS_STALE'
    if policy == 'fixed':
        return cap, 'FIXED'
    if policy == 'reactive':
        requested, reason = math.ceil(observed / SAFE_RPS), 'REACTIVE'
    elif policy == 'plain_predictive':
        requested, reason = math.ceil(forecast / SAFE_RPS), 'FORECAST_ONLY'
    elif policy == 'guarded_predictive':
        prediction = math.ceil((forecast + buffer) / SAFE_RPS)
        rescue = math.ceil(observed / SAFE_RPS)
        requested = max(prediction, rescue)
        reason = 'REACTIVE_RESCUE' if rescue > prediction else 'PREDICTIVE'
    else:
        raise ValueError(policy)
    return min(cap, max(1, requested)), 'CAPACITY_LIMITED' if requested > cap else reason


def simulate(trace, policy, model, buffer, bias=1.0):
    # Same initial capacity and six-window model-history warm-up for all policies.
    # Fixed policy provisions its cap at first scored decision and pays startup.
    ready = 1
    pending = []
    recommendations = []
    rows = []
    for t in range(HISTORY - 1, len(trace)):
        ready += sum(due <= t for due in pending)
        pending = [due for due in pending if due > t]
        allocated = ready + len(pending)
        demand = float(trace[t])
        # This slot's outcome occurs before the decision at its completed end.
        capacity = ready * PHYSICAL_RPS
        unmet = max(0, demand - capacity) * DT
        utilization = min(1.0, demand / capacity)
        energy = ((10 + 20 * utilization) * ready + 10 * len(pending)) * DT / 3600
        forecast = float(model.predict(features(trace[:t + 1]))[0]) * bias
        target, reason = recommend(policy, demand, forecast, buffer, allocated)
        recommendations.append(target)
        action = 'HOLD'
        if target > allocated:
            pending.extend([t + WARMUP + 1] * (target - allocated))
            action = 'UP'
        elif not pending and len(recommendations) >= 3:
            stable = max(recommendations[-3:])
            if stable < ready:
                ready -= 1
                action = 'DOWN'
        rows.append(dict(step=t, seconds=t * DT, demand_rps=demand,
                         forecast_peak_rps=forecast, ready_before_decision=round(capacity / PHYSICAL_RPS),
                         allocated_before_decision=allocated,
                         target=target, pending_after_decision=len(pending),
                         action=action, reason=reason, unmet_requests_model=unmet,
                         energy_proxy_wh=energy,
                         model_capacity_exceeded=int(demand > capacity),
                         scored=int(t >= HISTORY - 1 + 6)))
    # A common 60-second controller warm-up is excluded from scored outcomes.
    scored = [r for r in rows if r['scored']]
    demand_total = sum(r['demand_rps'] * DT for r in scored)
    summary = dict(policy=policy,
                   replica_seconds=sum(r['allocated_before_decision'] * DT for r in scored),
                   warmup_replica_seconds=sum(r['allocated_before_decision'] * DT for r in rows if not r['scored']),
                   model_capacity_exceeded_pct=100 * np.mean([r['model_capacity_exceeded'] for r in scored]),
                   unmet_demand_pct_model=100 * sum(r['unmet_requests_model'] for r in scored) / demand_total,
                   energy_proxy_wh=sum(r['energy_proxy_wh'] for r in scored),
                   scaling_actions=sum(r['action'] != 'HOLD' for r in scored))
    return summary, rows


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    OUT.mkdir(exist_ok=True)
    model, buffer, info = fit_model()
    runs, examples, accuracy = [], {}, []
    for name in SCENARIOS:
        for seed in (101, 202, 303):
            trace = scenario(name, seed)
            x, y = supervised(trace)
            p = model.predict(x)
            accuracy.append(dict(scenario=name, seed=seed,
                                 mae=float(abs(p - y).mean()),
                                 rmse=float(np.sqrt(np.mean((p - y) ** 2))),
                                 wape_pct=float(100 * abs(p - y).sum() / y.sum()),
                                 persistence_mae=float(abs(x[:, HISTORY - 1] - y).mean())))
            bias = .65 if name == 'underprediction' else 1.5 if name == 'overprediction' else 1.
            for policy in POLICIES:
                metrics, rows = simulate(trace, policy, model, buffer, bias)
                runs.append(dict(scenario=name, seed=seed, **metrics))
                if name == 'flash' and seed == 101:
                    examples[policy] = rows
    summary = []
    for name in SCENARIOS:
        for policy in POLICIES:
            selected = [r for r in runs if r['scenario'] == name and r['policy'] == policy]
            summary.append(dict(scenario=name, policy=policy,
                                **{k: float(np.mean([r[k] for r in selected]))
                                   for k in selected[0] if k not in ('scenario', 'seed', 'policy')}))
    write_csv(OUT / 'pilot_runs.csv', runs)
    write_csv(OUT / 'pilot_summary.csv', summary)
    write_csv(OUT / 'pilot_accuracy.csv', accuracy)
    write_csv(OUT / 'pilot_flash_decisions.csv', examples['guarded_predictive'])
    (OUT / 'pilot_forecast.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for policy, rows in examples.items():
        tm = [r['seconds'] / 60 for r in rows]
        axes[0].step(tm, [r['ready_before_decision'] * PHYSICAL_RPS for r in rows],
                     label=policy, where='post', alpha=.8)
    axes[0].plot(tm, [r['demand_rps'] for r in rows], color='black', label='Synthetic demand', lw=2)
    axes[0].set_ylabel('Requests/s or model capacity')
    axes[0].legend(ncol=2, fontsize=8)
    rows = examples['guarded_predictive']
    axes[1].plot(tm, [r['demand_rps'] for r in rows], color='black', label='Current demand')
    # Forecast target is peak over NEXT 30s, so keep forecast at issue time and
    # label it explicitly; this is not a point-by-point prediction alignment plot.
    axes[1].plot(tm, [r['forecast_peak_rps'] for r in rows], label='Forecast of next 30s peak (at issue time)')
    axes[1].set(xlabel='Simulated minutes', ylabel='Requests/s')
    axes[1].legend(fontsize=8)
    for ax in axes:
        ax.grid(alpha=.15)
    fig.suptitle('OFFLINE FEASIBILITY PILOT - synthetic traffic, assumed capacities\nNot measured HTTP latency or cloud performance', fontsize=13)
    fig.tight_layout()
    fig.savefig(OUT / 'pilot_flash.png', dpi=140)
    fig.savefig(OUT / 'pilot_flash.svg')
    plt.close(fig)
    print(json.dumps(dict(runs=len(runs), validation=info,
                          result_files=str(OUT)), indent=2))


if __name__ == '__main__':
    main()
