"""Instrumented proxy; each upstream request uses a fresh Service connection."""
import argparse
import asyncio
import os
from scaler.net import read_path, request, respond


class Gateway:
    def __init__(self, targets):
        self.targets = targets
        self.counter = 0

    async def handle(self, reader, writer):
        try:
            path = await read_path(reader)
            if path == '/health':
                await respond(writer, 200, dict(gateway='healthy'))
                return
            if path != '/work':
                await respond(writer, 404, dict(error='unknown_path'))
                return
            targets = self.targets()
            if not targets:
                await respond(writer, 503, dict(error='no_ready_workers'))
                return
            target = targets[self.counter % len(targets)]
            self.counter += 1
            try:
                status, data = await request(target + '/work', timeout=2.5)
                await respond(writer, status, data)
            except (OSError, TimeoutError, asyncio.IncompleteReadError):
                await respond(writer, 502, dict(error='upstream_failed'))
        except (OSError, TimeoutError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, ConnectionError):
                pass


async def main(args):
    gateway = Gateway(lambda: [args.upstream])
    server = await asyncio.start_server(gateway.handle, args.host, args.port)
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--host', default='0.0.0.0')
    p.add_argument('--port', type=int, default=8080)
    p.add_argument('--upstream', default=os.environ.get('UPSTREAM', 'http://worker:8080'))
    asyncio.run(main(p.parse_args()))
