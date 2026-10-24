import asyncio
import csv
import math
import random
import time
from scaler.net import request


def arrival_schedule(duration, safe_rps, scenario='periodic', seed=101):
    """Exogenous Poisson arrivals. Controller receives observations, not schedule."""
    rng = random.Random(seed)
    schedule = []
    for second in range(math.ceil(duration)):
        if scenario == 'constant':
            rate = safe_rps
        elif scenario == 'ramp':
            phase = (second/duration)
            multiple = .4 if phase < .2 else .4+2.8*min(1,(phase-.2)/.3) if phase < .5 else 3.2-2.8*min(1,(phase-.6)/.4)
            rate = safe_rps*multiple
        else:
            rate = safe_rps*(1.7+1.25*math.sin(2*math.pi*second/120-1.4))
            if scenario == 'flash' and duration*.45 <= second < duration*.6:
                rate += 2*safe_rps
        cursor = float(second)
        while rate > 0:
            cursor += rng.expovariate(rate)
            if cursor >= min(second+1,duration):
                break
            schedule.append(cursor)
    return schedule


class Load:
    def __init__(self, url, schedule, interval=10, limit=300):
        self.url, self.schedule, self.interval, self.limit = url, schedule, interval, limit
        self.records = []
        self.sent = {}
        self.active = set()
        self.start = None
        self.finished = False

    async def one(self, index, scheduled):
        sent = time.perf_counter()-self.start
        self.sent[index] = sent
        status, error = 0, ''
        try:
            status, _ = await request(self.url+'/work',timeout=3)
        except (OSError,TimeoutError,asyncio.IncompleteReadError,ValueError) as exc:
            error = type(exc).__name__
        completed = time.perf_counter()-self.start
        self.records.append(dict(index=index,scheduled_s=scheduled,sent_s=sent,completed_s=completed,
                            send_lag_ms=max(0,(sent-scheduled)*1000),
                            latency_ms=(completed-sent)*1000,status=status,error=error))

    async def run(self, started=None):
        self.start = started if started is not None else time.perf_counter()
        try:
            for i, scheduled in enumerate(self.schedule):
                await asyncio.sleep(max(0,self.start+scheduled-time.perf_counter()))
                if len(self.active) >= self.limit:
                    now=time.perf_counter()-self.start
                    self.sent[i] = now
                    self.records.append(dict(index=i,scheduled_s=scheduled,sent_s=now,completed_s=now,
                                        send_lag_ms=max(0,(now-scheduled)*1000),latency_ms=0,
                                        status=-1,error='generator_capacity_limit'))
                    continue
                task=asyncio.create_task(self.one(i,scheduled))
                self.active.add(task)
                task.add_done_callback(self.active.discard)
            if self.active:
                await asyncio.gather(*list(self.active))
        finally:
            self.finished=True

    def window(self, lower, upper, now):
        # Include all arrivals by their actual send time. In-flight requests
        # count as offered load and become conservative deadline indicators.
        records=[r for r in self.records if lower <= r['sent_s'] < upper]
        completed_ids={r['index'] for r in self.records}
        sent_count=sum(lower <= t < upper for t in self.sent.values())
        latencies=sorted(r['latency_ms'] for r in records if r['status']==200)
        p95=latencies[min(len(latencies)-1,math.ceil(.95*len(latencies))-1)] if latencies else None
        failed=sum(r['status']!=200 for r in records)
        unresolved=sent_count-len(records)
        return dict(offered_rps=sent_count/(upper-lower),completed=len(records),
                    p95_ms=p95,error_fraction=failed/len(records) if records else 0,
                    unresolved=unresolved)

    def save(self,path):
        fields=['index','scheduled_s','sent_s','completed_s','send_lag_ms','latency_ms','status','error']
        with open(path,'w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(sorted(self.records,key=lambda r:r['index']))
