import unittest
import numpy as np
from planning_pilot.pilot import (features, supervised, recommend, fit_model,
                                  simulate, scenario, POLICIES, MAX_REPLICAS)


class PilotTests(unittest.TestCase):
    def test_labels_are_future_peak_and_features_are_past(self):
        trace = np.arange(20, dtype=float)
        x, y = supervised(trace)
        self.assertEqual(x[0, 5], 5)
        self.assertEqual(y[0], 8)
        changed = trace.copy()
        changed[6:] += 1000
        x2, _ = supervised(changed)
        np.testing.assert_array_equal(x[0], x2[0])

    def test_unseen_step_triggers_rescue(self):
        target, reason = recommend('guarded_predictive', 350, 50, 5, 1)
        self.assertEqual(target, 5)
        self.assertEqual(reason, 'REACTIVE_RESCUE')
        plain, _ = recommend('plain_predictive', 350, 50, 5, 1)
        self.assertEqual(plain, 1)

    def test_hard_cap_and_stale_metrics(self):
        n, reason = recommend('guarded_predictive', 2000, 2000, 5, 2, cap=4)
        self.assertEqual((n, reason), (4, 'CAPACITY_LIMITED'))
        n, reason = recommend('guarded_predictive', 0, 0, 0, 4, stale=True)
        self.assertEqual((n, reason), (4, 'METRICS_STALE'))

    def test_capacity_readiness_and_allocation_bounds(self):
        model, buffer, _ = fit_model()
        trace = scenario('flash', 999)
        for policy in POLICIES:
            metrics, rows = simulate(trace, policy, model, buffer)
            for row in rows:
                self.assertLessEqual(row['allocated_before_decision'], MAX_REPLICAS)
                self.assertGreaterEqual(row['ready_before_decision'], 1)
            for i, row in enumerate(rows[:-1]):
                if row['action'] == 'UP':
                    self.assertGreater(rows[i + 1]['pending_after_decision'], 0)
            self.assertGreater(metrics['replica_seconds'], 0)

    def test_reproducibility(self):
        np.testing.assert_array_equal(scenario('flash', 101), scenario('flash', 101))
        self.assertFalse(np.array_equal(scenario('flash', 101), scenario('flash', 202)))


if __name__ == '__main__':
    unittest.main()
