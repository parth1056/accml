"""Read-only local demo viewer for actual experiment outputs."""
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LIVE=ROOT/'output'/'live'


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass

    def do_GET(self):
        if self.path=='/':
            body=(Path(__file__).with_name('viewer.html')).read_bytes()
            content_type='text/html; charset=utf-8'
        elif self.path=='/api':
            latest={};decisions=[];resources=[];summaries=[]
            try:
                latest=json.loads((LIVE/'latest.json').read_text(encoding='utf-8'))
                directory=(LIVE/str(latest['directory']).replace('\\','/').rsplit('/',1)[-1]).resolve()
                if directory.parent!=LIVE.resolve():
                    raise ValueError('Invalid experiment directory')
                for filename,target in [('decisions.csv',decisions),('resources.csv',resources)]:
                    if (directory/filename).exists():
                        with (directory/filename).open(encoding='utf-8') as f:
                            target.extend(csv.DictReader(f))
            except (FileNotFoundError,ValueError,KeyError,json.JSONDecodeError):
                pass
            for path in sorted(LIVE.glob('*/summary.json'),reverse=True):
                try:
                    s=json.loads(path.read_text(encoding='utf-8'))
                    summaries.append(dict(run=path.parent.name,**s))
                except (OSError,ValueError):
                    continue
            body=json.dumps(dict(latest=latest,decisions=decisions,resources=resources,summaries=summaries)).encode()
            content_type='application/json'
        else:
            self.send_error(404);return
        self.send_response(200)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.end_headers();self.wfile.write(body)


if __name__=='__main__':
    print('Measured experiment viewer: http://127.0.0.1:8787',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8787),Handler).serve_forever()
