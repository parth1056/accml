"""Real bounded CPU service. Runs unchanged on Windows or in a container."""
import argparse
import asyncio
import hashlib
import os
import signal
import time
from scaler.net import read_path, respond


class Worker:
    def __init__(self, iterations=60000, startup=5):
        self.iterations = iterations
        self.started = time.monotonic()
        self.startup = startup
        self.gate = asyncio.Semaphore(1)
        self.inflight = self.completed = self.rejected = 0

    async def handle(self, reader, writer):
        admitted = False
        try:
            path = await read_path(reader)
            if path == '/metrics':
                cpu = os.times()
                await respond(writer, 200, dict(pid=os.getpid(), cpu_seconds=cpu.user + cpu.system,
                              uptime=time.monotonic() - self.started, completed=self.completed,
                              inflight=self.inflight, rejected=self.rejected))
            elif path in ('/health', '/ready'):
                ready = time.monotonic() - self.started >= self.startup
                await respond(writer, 200 if ready else 503, dict(ready=ready, pid=os.getpid()))
            elif path == '/work':
                if time.monotonic() - self.started < self.startup or self.inflight >= 100:
                    self.rejected += 1
                    await respond(writer, 503, dict(error='starting_or_queue_full'))
                    return
                self.inflight += 1
                admitted = True
                queued = time.perf_counter()
                try:
                    await asyncio.wait_for(self.gate.acquire(), 1.5)
                except TimeoutError:
                    self.rejected += 1
                    await respond(writer, 503, dict(error='queue_deadline'))
                    return
                try:
                    began = time.perf_counter()
                    result = await asyncio.to_thread(hashlib.pbkdf2_hmac, 'sha256', b'acc-lab-workload',
                                                     b'fixed-reproducible-salt', self.iterations)
                    self.completed += 1
                    await respond(writer, 200, dict(worker=os.getpid(), digest=result.hex()[:16],
                                  queue_ms=(began - queued) * 1000,
                                  service_ms=(time.perf_counter() - began) * 1000))
                finally:
                    self.gate.release()
            else:
                await respond(writer, 404, dict(error='unknown_path'))
        except (OSError, ConnectionError, asyncio.IncompleteReadError, TimeoutError):
            pass
        finally:
            if admitted:
                self.inflight -= 1
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, ConnectionError):
                pass


async def main(args):
    worker = Worker(args.iterations, args.startup)
    server = await asyncio.start_server(worker.handle, args.host, args.port, limit=16384)
    print(f'worker pid={os.getpid()} port={args.port} iterations={args.iterations}', flush=True)
    stopping=asyncio.Event()
    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM,stopping.set)
    except NotImplementedError:
        pass  # Windows local fleet removes routing and drains before termination.
    async with server:
        await stopping.wait()
    deadline=time.monotonic()+3
    while worker.inflight and time.monotonic()<deadline:
        await asyncio.sleep(.05)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=19001)
    p.add_argument('--iterations', type=int, default=int(os.environ.get('WORK_ITERATIONS', '60000')))
    p.add_argument('--startup', type=float, default=float(os.environ.get('STARTUP_SECONDS', '5')))
    asyncio.run(main(p.parse_args()))
