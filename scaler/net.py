import asyncio
import json
from urllib.parse import urlsplit


async def request(url, timeout=3, method='GET', body=None):
    """Small HTTP/1.1 client; one connection/request avoids backend stickiness."""
    writer = None
    async def exchange():
        nonlocal writer
        u = urlsplit(url)
        reader, writer = await asyncio.open_connection(u.hostname, u.port or 80)
        payload = b'' if body is None else json.dumps(body).encode()
        headers = (f'{method} {u.path or "/"}{"?" + u.query if u.query else ""} HTTP/1.1\r\n'
                   f'Host: {u.hostname}\r\nConnection: close\r\nContent-Length: {len(payload)}\r\n\r\n').encode()
        writer.write(headers + payload)
        await writer.drain()
        header = await reader.readuntil(b'\r\n\r\n')
        status = int(header.split(b' ', 2)[1])
        length = next((int(x.split(b':', 1)[1]) for x in header.split(b'\r\n')
                       if x.lower().startswith(b'content-length:')), None)
        if b'transfer-encoding: chunked' in header.lower():
            chunks=[]
            while True:
                size=int((await reader.readline()).strip().split(b';',1)[0],16)
                if size==0:
                    while (await reader.readline()) not in (b'\r\n',b''):
                        pass
                    break
                chunks.append(await reader.readexactly(size))
                if await reader.readexactly(2)!=b'\r\n':
                    raise ValueError('Invalid HTTP chunk terminator')
            data=b''.join(chunks)
        else:
            data = await reader.readexactly(length) if length is not None else await reader.read()
        return status, data
    try:
        return await asyncio.wait_for(exchange(), timeout)
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, ConnectionError):
                pass


async def json_request(url, **kwargs):
    status, data = await request(url, **kwargs)
    if status != 200:
        raise RuntimeError(f'HTTP {status} at {url}: {data[:100]!r}')
    return json.loads(data)


async def respond(writer, status, body):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    writer.write(f'HTTP/1.1 {status} Result\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\nConnection: close\r\n\r\n'.encode() + data)
    await writer.drain()


async def read_path(reader):
    header = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
    return header.split(b' ', 2)[1].decode().split('?', 1)[0]
