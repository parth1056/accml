import asyncio
import unittest
import tempfile
import json
from unittest.mock import patch
from pathlib import Path
from scaler.forecast import Forecaster
from scaler.policy import Policy
from scaler.worker import Worker
from scaler.net import json_request
from scaler.traffic import Load


class PolicyTests(unittest.TestCase):
    def test_invalid_forecast_holds_capacity_but_allows_observed_rescue(self):
        for bad in (float('nan'),float('inf'),-1,'broken'):
            with self.subTest(forecast=bad):
                p=Policy('guarded_predictive',10,stabilization=0)
                state=dict(desired=3,pending=0)
                self.assertEqual(p.decide(0,1,bad,0,state),(3,'MODEL_INVALID_FALLBACK'))
                self.assertEqual(p.decide(60,35,bad,0,state),(4,'MODEL_INVALID_FALLBACK'))
                self.assertEqual(p.decide(70,100,bad,0,state),(4,'CAPACITY_LIMITED'))

    def test_invalid_observations_hold_existing_capacity(self):
        p=Policy('guarded_predictive',10)
        self.assertEqual(p.decide(0,float('nan'),1,0,dict(desired=3,pending=0)),
                         (3,'METRICS_INVALID'))

    def test_zero_forecast_remains_valid_for_fault_ablation(self):
        p=Policy('plain_predictive',10,stabilization=0)
        self.assertEqual(p.decide(0,100,0,0,dict(desired=3,pending=0)),
                         (2,'STABLE_DOWNSCALE'))

    def test_saved_model_predicts_identically(self):
        model=Forecaster(14.4)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'model.json';model.save(path,10)
            restored=Forecaster.load(path)
            self.assertAlmostEqual(model.predict([10,12,14,18,20,25]),restored.predict([10,12,14,18,20,25]))

    def test_budget_cap_is_hard_even_under_sla_failure(self):
        p=Policy('guarded_predictive',10,maximum=6,hourly_rate=.02,hourly_budget=.04)
        n,why=p.decide(10,100,100,2,dict(desired=1,pending=0),p95_ms=1000)
        self.assertEqual((n,why),(2,'CAPACITY_LIMITED'))

    def test_stale_metrics_never_downscale(self):
        p=Policy('guarded_predictive',10)
        self.assertEqual(p.decide(10,0,0,0,dict(desired=3,pending=0),fresh=False),(3,'METRICS_STALE'))

    def test_stabilization_works_with_real_clock_jitter(self):
        p=Policy('reactive',10,stabilization=30)
        state=dict(desired=4,pending=0)
        for t in (0.3,10.7,20.9):
            self.assertEqual(p.decide(t,5,None,0,state)[0],4)
        self.assertEqual(p.decide(31.2,5,None,0,state),(3,'STABLE_DOWNSCALE'))

    def test_pending_capacity_prevents_duplicate_sla_rescue(self):
        p=Policy('guarded_predictive',10)
        n,why=p.decide(10,10,10,0,dict(desired=3,pending=2),p95_ms=900)
        self.assertEqual((n,why),(3,'DOWNSCALE_WAIT'))


class NetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_shadow_never_mutates_fleet_even_with_inference_failure(self):
        from scaler import experiment

        class ReadOnlyFleet:
            backend='kubernetes'
            async def scale(self,*args):
                raise AssertionError('Shadow mode attempted to scale')
            async def close(self):
                raise AssertionError('Shadow cleanup attempted to reset replicas')
            async def status(self):
                return dict(desired=2,ready=2,pending=0,allocated=2,
                            cpu_capacity_cores=.5,cpu_total_seconds=0)

        class BrokenModel:
            buffer=0
            def predict(self,history):
                raise RuntimeError('Injected inference failure')
            def save(self,path,interval):
                path.write_text('{}')

        class ObservedLoad:
            records=[]
            def __init__(self,*args):
                pass
            async def run(self,started):
                pass
            def window(self,*args):
                return dict(offered_rps=35,p95_ms=30,error_fraction=0)
            def save(self,path):
                path.write_text('')

        args=experiment.parser().parse_args(['run','--backend','kubernetes','--mode','shadow',
             '--safe-rps','10','--duration','1.1','--interval','.2','--warmup','0'])
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(experiment,'ROOT',Path(temporary)), \
                 patch.object(experiment,'environment_signature',return_value={}), \
                 patch.object(experiment,'KubernetesFleet',ReadOnlyFleet), \
                 patch.object(experiment,'Forecaster',return_value=BrokenModel()), \
                 patch.object(experiment,'Load',ObservedLoad), \
                 patch('builtins.print'):
                directory,result=await experiment.run_once(args)
            self.assertEqual(result['scaling_actions'],0)
            self.assertGreater(result['shadow_recommendations'],0)
            latest=json.loads((directory.parent/'latest.json').read_text())
            self.assertEqual(latest['desired'],2)
            self.assertEqual(latest['target'],4)
            self.assertEqual(latest['reason'],'MODEL_INVALID_FALLBACK')
            self.assertIn('Injected inference failure',latest['forecast_error'])
            self.assertIsNone(latest['forecast_rps'])

    async def test_kubernetes_proxy_chunked_json(self):
        async def handler(reader,writer):
            await reader.readuntil(b'\r\n\r\n')
            writer.write(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n'
                         b'5\r\n{"ok"\r\n6\r\n:true}\r\n0\r\n\r\n')
            await writer.drain();writer.close();await writer.wait_closed()
        server=await asyncio.start_server(handler,'127.0.0.1',0)
        try:
            value=await json_request(f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/')
            self.assertEqual(value,{'ok':True})
        finally:
            server.close();await server.wait_closed()

    async def test_real_worker_hash_and_cpu_metrics(self):
        worker=Worker(iterations=1000,startup=0)
        server=await asyncio.start_server(worker.handle,'127.0.0.1',0)
        url=f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}'
        try:
            self.assertTrue((await json_request(url+'/ready'))['ready'])
            work=await json_request(url+'/work')
            self.assertEqual(len(work['digest']),16)
            metric=await json_request(url+'/metrics')
            self.assertEqual(metric['completed'],1)
            self.assertGreaterEqual(metric['cpu_seconds'],0)
        finally:
            server.close();await server.wait_closed()

    async def test_offered_demand_comes_from_sends_not_hidden_schedule(self):
        load=Load('http://127.0.0.1:1',[.1,.2,.3,.4])
        load.sent={0:.15,1:.25}
        result=load.window(0,1,1)
        self.assertEqual(result['offered_rps'],2)
        self.assertEqual(result['unresolved'],2)


if __name__=='__main__':
    unittest.main()
