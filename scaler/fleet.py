import asyncio
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import time
from scaler.net import json_request

ROOT = Path(__file__).resolve().parents[1]


class LocalFleet:
    """Starts/stops only worker subprocesses owned by this experiment."""
    backend = 'local-processes'
    def __init__(self, directory, iterations=60000, startup=5):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.workers = []
        self.ready_urls = []
        self.next_port = 19000
        self.iterations, self.startup = iterations, startup
        self.previous_cpu = {}
        self.cpu_delta = 0
        self.cpu_total = 0
        self.retiring = []

    async def scale(self, desired):
        if not 1 <= desired <= 6:
            raise ValueError('Local replica count must be 1..6')
        while len(self.workers) < desired:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            log = (self.directory / f'worker-{port}.log').open('w')
            kwargs = dict(cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
            if os.name == 'nt':
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            process = subprocess.Popen([sys.executable, '-m', 'scaler.worker', '--port', str(port),
                                        '--iterations', str(self.iterations), '--startup', str(self.startup)], **kwargs)
            self.workers.append(dict(process=process, log=log, url=f'http://127.0.0.1:{port}', started=time.monotonic()))
        while len(self.workers) > desired:
            worker = self.workers.pop()
            # Remove from routing immediately, then allow existing requests to drain.
            self.ready_urls = [u for u in self.ready_urls if u != worker['url']]
            worker['retire_at'] = time.monotonic() + 3
            self.retiring.append(worker)

    async def status(self):
        now = time.monotonic()
        for w in list(self.retiring):
            if now >= w['retire_at']:
                w['process'].terminate()
                await asyncio.to_thread(w['process'].wait, timeout=5)
                w['log'].close()
                self.retiring.remove(w)
        ready = []
        cpu_delta = 0
        for worker in self.workers + self.retiring:
            if worker['process'].poll() is not None:
                raise RuntimeError(f"Owned worker exited: {worker['url']}")
            try:
                health = await json_request(worker['url'] + '/ready', timeout=.3)
                if health['ready'] and worker in self.workers:
                    ready.append(worker['url'])
                metric = await json_request(worker['url'] + '/metrics', timeout=.5)
                total = metric['cpu_seconds']
                old = self.previous_cpu.get(worker['url'], 0)
                cpu_delta += max(0, total - old)
                self.previous_cpu[worker['url']] = total
            except (OSError, TimeoutError, RuntimeError, asyncio.IncompleteReadError):
                # Startup is expected; a live process that cannot become ready
                # for 30 seconds is an experiment failure, not imaginary capacity.
                if now - worker['started'] > max(30, self.startup + 15):
                    raise RuntimeError(f"Worker health unavailable: {worker['url']}")
        self.ready_urls = ready
        self.cpu_total += cpu_delta
        self.cpu_delta += cpu_delta
        return dict(desired=len(self.workers), ready=len(ready), pending=len(self.workers)-len(ready),
                    allocated=len(self.workers)+len(self.retiring), cpu_total_seconds=self.cpu_total,
                    cpu_capacity_cores=float(len(self.workers)+len(self.retiring)))

    async def close(self):
        for w in self.workers + self.retiring:
            if w['process'].poll() is None:
                w['process'].terminate()
                try:
                    await asyncio.to_thread(w['process'].wait, timeout=5)
                except subprocess.TimeoutExpired:
                    w['process'].kill()
            w['log'].close()
        self.workers.clear()
        self.retiring.clear()


class KubernetesFleet:
    backend = 'kubernetes'
    def __init__(self, context='acc-lab', namespace='acc-lab'):
        if context != 'acc-lab' or namespace != 'acc-lab':
            raise ValueError('Only dedicated acc-lab context/namespace is permitted')
        self.context, self.namespace = context, namespace
        self.proxy='http://127.0.0.1:18001'
        self.previous_cpu={}
        self.cpu_total=0.
        self.cpu_samples=0

    async def command(self, *args):
        command = ['kubectl', '--kubeconfig', str(ROOT/'runtime'/'kubeconfig'),
                   '--context', self.context, '-n', self.namespace, *args]
        def run():
            result = subprocess.run(command, text=True, capture_output=True, timeout=15)
            if result.returncode:
                raise RuntimeError(result.stderr[:1200])
            return result.stdout
        return await asyncio.to_thread(run)

    async def scale(self, desired):
        if not 1 <= desired <= 6:
            raise ValueError('Replica count must be 1..6')
        await self.command('scale', 'deployment/worker', f'--replicas={desired}')

    async def status(self):
        # Pod list gives actual running/initializing/terminating allocation.
        deployment,pod_list = await asyncio.gather(
            json_request(self.proxy+'/apis/apps/v1/namespaces/acc-lab/deployments/worker',timeout=5),
            json_request(self.proxy+'/api/v1/namespaces/acc-lab/pods?labelSelector=app%3Dworker',timeout=5))
        pods=pod_list['items']
        ready = sum(any(c['type']=='Ready' and c['status']=='True' for c in p.get('status',{}).get('conditions',[]))
                    and not p['metadata'].get('deletionTimestamp') for p in pods)
        desired = deployment['spec']['replicas']
        async def cpu(pod):
            if pod.get('status',{}).get('phase')!='Running':
                return
            name=pod['metadata']['name'];uid=pod['metadata']['uid']
            try:
                metric=await json_request(self.proxy+f'/api/v1/namespaces/acc-lab/pods/{name}:8080/proxy/metrics',timeout=2)
                total=metric['cpu_seconds']
                self.cpu_total+=max(0,total-self.previous_cpu.get(uid,0))
                self.previous_cpu[uid]=total
                self.cpu_samples+=1
            except (OSError,TimeoutError,RuntimeError,asyncio.IncompleteReadError):
                pass
        await asyncio.gather(*(cpu(p) for p in pods))
        return dict(desired=desired, ready=ready, pending=max(0,desired-ready), allocated=len(pods),
                    cpu_total_seconds=self.cpu_total if self.cpu_samples else None,
                    cpu_capacity_cores=len(pods)*.25)

    async def close(self):
        # Leave reproducible namespace intact but return compute to one worker.
        await self.scale(1)
