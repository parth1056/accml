from collections import deque
import math


def nonnegative_finite(value):
    try:
        return math.isfinite(value) and value >= 0
    except (TypeError, ValueError):
        return False


class Policy:
    def __init__(self, name, safe_rps, maximum=4, minimum=1, sla_ms=250,
                 stabilization=30, hourly_rate=.02, hourly_budget=None):
        if name not in ('fixed','reactive','plain_predictive','guarded_predictive'):
            raise ValueError('Unknown policy')
        if not nonnegative_finite(safe_rps) or not safe_rps > 0 or not nonnegative_finite(hourly_rate) or not hourly_rate > 0:
            raise ValueError('Capacity and rate must be positive')
        if hourly_budget is not None and not nonnegative_finite(hourly_budget):
            raise ValueError('Budget must be finite and nonnegative')
        self.cap = min(maximum, math.floor(hourly_budget/hourly_rate)) if hourly_budget is not None else maximum
        if not 1 <= minimum <= self.cap <= 6:
            raise ValueError('Budget/replica bounds are infeasible')
        self.name, self.safe_rps, self.minimum = name, safe_rps, minimum
        self.sla_ms, self.stabilization = sla_ms, stabilization
        self.recommendations = deque()
        self.started = None

    def decide(self, now, observed, forecast, buffer, state, p95_ms=None,
               error_fraction=0, fresh=True, forecast_failed=False):
        current = state['desired']
        if self.started is None:
            self.started = now
        if not fresh:
            return current, 'METRICS_STALE'
        if not nonnegative_finite(observed):
            return current, 'METRICS_INVALID'
        invalid_forecast = forecast_failed or (forecast is not None and not nonnegative_finite(forecast))
        if not nonnegative_finite(buffer):
            invalid_forecast = True
            buffer = 0
        if invalid_forecast:
            forecast = None
        pred = max(0, forecast if forecast is not None else observed)
        observed_n = math.ceil(observed/self.safe_rps)
        predicted_n = math.ceil((pred + buffer)/self.safe_rps)
        if self.name == 'fixed':
            return self.cap, 'FIXED'
        if self.name == 'reactive':
            raw, reason = observed_n, 'REACTIVE'
        elif self.name == 'plain_predictive':
            raw, reason = math.ceil(pred/self.safe_rps), 'FORECAST_ONLY'
        else:
            raw = max(observed_n, predicted_n)
            reason = 'REACTIVE_RESCUE' if observed_n > predicted_n else 'PREDICTIVE'
            # Let a pending scale-out become Ready before latency requests more.
            if state['pending'] == 0 and ((p95_ms is not None and p95_ms > self.sla_ms) or error_fraction > .01):
                raw = max(raw, current+1)
                reason = 'SLA_RESCUE'
        target = max(self.minimum, min(self.cap, raw))
        if raw > self.cap:
            reason = 'CAPACITY_LIMITED'
        elif invalid_forecast:
            # A broken model can request observed-demand rescue, but must not
            # remove capacity merely because it stopped returning a forecast.
            target = max(current, target)
            reason = 'MODEL_INVALID_FALLBACK'
        elif forecast is None and self.name in ('plain_predictive', 'guarded_predictive') and reason in ('PREDICTIVE', 'FORECAST_ONLY'):
            reason = 'MODEL_WARMUP'
        self.recommendations.append((now, target))
        while self.recommendations and self.recommendations[0][0] < now-self.stabilization:
            self.recommendations.popleft()
        if target < current:
            if state['pending'] or now-self.started < self.stabilization:
                return current, 'DOWNSCALE_WAIT'
            stable = max(n for _, n in self.recommendations)
            target = max(current-1, stable)
            if target >= current:
                return current, 'DOWNSCALE_WAIT'
            reason = 'STABLE_DOWNSCALE'
        return target, reason
