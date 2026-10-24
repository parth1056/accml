"""Run real HTTP experiments, never a capacity simulator.

Examples:
 python -m scaler.experiment calibrate --rates 5 10 20 30 --seconds 30
 python -m scaler.experiment run --safe-rps 15 --duration 240 --warmup 60
"""
import argparse
import asyncio
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import platform
import os
from pathlib import Path
import time
from uuid import uuid4
import numpy as np
from scaler.fleet import LocalFleet, KubernetesFleet
from scaler.forecast import Forecaster
from scaler.gateway import Gateway
from scaler.policy import Policy, nonnegative_finite
from scaler.traffic import Load, arrival_schedule

ROOT=Path(__file__).resolve().parents[1]


def environment_signature():
    host=hashlib.sha256((platform.node()+'|'+platform.machine()+'|'+str(os.cpu_count())).encode()).hexdigest()
    workload=hashlib.sha256()
    for name in ('scaler/worker.py','scaler/net.py','Dockerfile','k8s/application.yaml'):
        workload.update((ROOT/name).read_bytes())
    return dict(host_fingerprint=host,workload_fingerprint=workload.hexdigest())


def save_csv(path, rows):
    if not rows:
        return
    with Path(path).open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def percentile(values, q):
    return float(np.percentile(values,q)) if values else None


def summarize(load, snapshots, decisions, args):
    records=[r for r in load.records if args.warmup <= r['sent_s'] < args.duration]
    successes=[r for r in records if r['status']==200]
    latency=[r['latency_ms'] for r in successes]
    allocation=cpu_core_s=cpu_s=energy=0.
    for before,after in zip(snapshots,snapshots[1:]):
        start=max(args.warmup,before['elapsed_s']);end=min(args.duration,after['elapsed_s'])
        dt=max(0,end-start)
        if not dt:
            continue
        allocation += before['allocated']*dt
        cpu_core_s += before['cpu_capacity_cores']*dt
        if before['cpu_total_seconds'] is not None and after['cpu_total_seconds'] is not None:
            whole=after['elapsed_s']-before['elapsed_s']
            used=max(0,after['cpu_total_seconds']-before['cpu_total_seconds'])*dt/whole
            cpu_s += used
            energy += (before['allocated']*10*dt+20*used)/3600
    errors=sum(r['status']!=200 for r in records)
    windows=[]
    for left in np.arange(args.warmup,args.duration,args.interval):
        subset=[r for r in records if left<=r['sent_s']<left+args.interval]
        successful=[r['latency_ms'] for r in subset if r['status']==200]
        if subset:
            p95=percentile(successful,95)
            failed=sum(r['status']!=200 for r in subset)/len(subset)
            windows.append((p95 is None or p95>args.sla_ms) or failed>.01)
    forecasts=[]
    for d in decisions:
        if d['forecast_rps'] is None or d['elapsed_s']<args.warmup or d['elapsed_s']+3*args.interval>args.duration:
            continue
        rates=[]
        for k in range(3):
            lo=d['elapsed_s']+k*args.interval
            rates.append(sum(lo<=r['sent_s']<lo+args.interval for r in load.records)/args.interval)
        forecasts.append((d['forecast_rps'],max(rates),d['observed_rps']))
    total_y=sum(y for _,y,_ in forecasts)
    cpu_available=all(s['cpu_total_seconds'] is not None for s in snapshots)
    return dict(backend=args.backend,policy=args.policy,scenario=args.scenario,seed=args.seed,
        controller_mode=getattr(args,'mode','active'),
        duration_s=args.duration,warmup_s=args.warmup,scored_requests=len(records),
        success_fraction=len(successes)/len(records) if records else None,
        failure_fraction=errors/len(records) if records else None,
        p50_ms=percentile(latency,50),p95_ms=percentile(latency,95),p99_ms=percentile(latency,99),
        sla_violating_window_fraction=float(np.mean(windows)) if windows else None,
        replica_seconds=allocation,estimated_cost=allocation/3600*args.hourly_rate,
        cost_unit='illustrative currency units; not an AWS bill',
        measured_worker_cpu_seconds=cpu_s if cpu_available else None,
        mean_worker_cpu_utilization=cpu_s/cpu_core_s if cpu_available and cpu_core_s else None,
        energy_proxy_wh=energy if cpu_available else allocation*10/3600,
        energy_method='assumed 10W allocated + 20W per measured CPU core' if cpu_available else 'allocation-only assumed 10W per replica',
        scaling_actions=sum(d['action']=='SCALE' for d in decisions if d['elapsed_s']>=args.warmup),
        shadow_recommendations=sum(d['action']=='SHADOW' for d in decisions if d['elapsed_s']>=args.warmup),
        generator_capacity_drops=sum(r['status']==-1 for r in records),
        send_lag_p99_ms=percentile([r['send_lag_ms'] for r in records],99),
        forecast_mae_rps=float(np.mean([abs(p-y) for p,y,_ in forecasts])) if forecasts else None,
        forecast_rmse_rps=float(np.sqrt(np.mean([(p-y)**2 for p,y,_ in forecasts]))) if forecasts else None,
        forecast_wape=float(sum(abs(p-y) for p,y,_ in forecasts)/total_y) if total_y else None,
        persistence_mae_rps=float(np.mean([abs(b-y) for _,y,b in forecasts])) if forecasts else None,
        forecast_targets=len(forecasts),safe_rps=args.safe_rps,
        validity_warning='Generator overloaded' if any(r['status']==-1 for r in records) or
                         (percentile([r['send_lag_ms'] for r in records],99) or 0)>100 else None)


async def run_once(args):
    mode=getattr(args,'mode','active')
    if mode=='shadow' and (args.backend!='kubernetes' or args.command!='run'):
        raise ValueError('Shadow mode attaches read-only to an existing Kubernetes deployment; use run --backend kubernetes.')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory=ROOT/'output'/'live'/f'{stamp}-{args.backend}-{args.scenario}-{args.policy}-{uuid4().hex[:4]}'
    directory.mkdir(parents=True)
    config=vars(args).copy()
    config.update(environment_signature())
    code=hashlib.sha256()
    for source in sorted((ROOT/'scaler').glob('*.py')):
        code.update(source.name.encode());code.update(source.read_bytes())
    config['code_sha256']=code.hexdigest()
    config['python_version']=platform.python_version()
    config['numpy_version']=np.__version__
    config['started_utc']=stamp
    config['workload']='real HTTP PBKDF2 CPU service; synthetic exogenous arrival schedule'
    config['controller_mode']=mode
    (directory/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    fleet=LocalFleet(directory/'workers',args.iterations,args.startup) if args.backend=='local' else KubernetesFleet()
    server=None
    snapshots=[];decisions=[]
    stored=ROOT/'output'/'trained_model.json'
    stored_data=json.loads(stored.read_text()) if stored.exists() else {}
    if stored_data.get('safe_rps')==args.safe_rps and stored_data.get('horizon_seconds')==args.interval*3:
        model=Forecaster.load(stored,args.bias)
    else:
        model=Forecaster(args.safe_rps,args.bias)
    model.save(directory/'model.json',args.interval)
    policy=Policy(args.policy,args.safe_rps,args.maximum,sla_ms=args.sla_ms,
                  stabilization=args.stabilization,hourly_rate=args.hourly_rate,hourly_budget=args.hourly_budget)
    schedule=arrival_schedule(args.duration,args.safe_rps,args.scenario,args.seed)
    save_csv(directory/'arrivals.csv',[dict(index=i,scheduled_s=t) for i,t in enumerate(schedule)])
    config['arrival_schedule_sha256']=hashlib.sha256((directory/'arrivals.csv').read_bytes()).hexdigest()
    (directory/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    load=None;task=None
    try:
        if mode=='active':
            await fleet.scale(1)
        deadline=time.monotonic()+60
        while True:
            state=await fleet.status()
            if mode=='shadow' and state['ready']>0:
                break
            if state['desired']==1 and state['ready']==1 and state['pending']==0 and state['allocated']==1:
                break
            if time.monotonic()>deadline:
                raise RuntimeError('Initial worker readiness timed out')
            await asyncio.sleep(.5)
        if args.backend=='local':
            gateway=Gateway(lambda:fleet.ready_urls)
            server=await asyncio.start_server(gateway.handle,'127.0.0.1',0)
            url=f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        else:
            url=args.url
        load=Load(url,schedule,args.interval)
        started=time.perf_counter()
        task=asyncio.create_task(load.run(started))
        history=[];next_window=1;last_action=None
        state=await fleet.status()
        if mode=='active' and args.policy=='fixed' and policy.cap>1:
            await fleet.scale(policy.cap)
        while time.perf_counter()-started<args.duration:
            now=time.perf_counter()-started
            state=await fleet.status()
            snapshots.append(dict(elapsed_s=time.perf_counter()-started,**state))
            while next_window*args.interval<=now:
                end=next_window*args.interval
                telemetry=load.window(end-args.interval,end,now)
                history.append(telemetry['offered_rps'])
                forecast_error=''
                try:
                    forecast=model.predict(history)
                    if forecast is not None and not nonnegative_finite(forecast):
                        raise ValueError('Predictor returned a negative or non-finite demand')
                except Exception as exc:
                    # Inference failures must not stop the observed-demand path.
                    forecast=None
                    forecast_error=f'{type(exc).__name__}: {exc}'[:300]
                desired,reason=policy.decide(end,telemetry['offered_rps'],forecast,model.buffer,state,
                    p95_ms=telemetry['p95_ms'],error_fraction=telemetry['error_fraction'],
                    fresh=now-end<2*args.interval,forecast_failed=bool(forecast_error))
                action='HOLD';error=''
                if desired!=state['desired']:
                    if mode=='shadow':
                        action='SHADOW'
                    else:
                        try:
                            await fleet.scale(desired)
                            action='SCALE'
                        except (RuntimeError,OSError) as exc:
                            action='FAILED';error=str(exc)
                decision=dict(elapsed_s=end,decision_lag_s=now-end,observed_rps=telemetry['offered_rps'],
                    forecast_rps=forecast,buffer_rps=model.buffer,target=desired,reason=reason,action=action,
                    ready=state['ready'],pending=state['pending'],desired=state['desired'],
                    p95_ms=telemetry['p95_ms'],error_fraction=telemetry['error_fraction'],actuator_error=error,
                    controller_mode=mode,forecast_error=forecast_error)
                decisions.append(decision)
                print(f"{args.policy:20} t={end:4.0f}s rps={telemetry['offered_rps']:5.1f} "
                      f"ready={state['ready']} pending={state['pending']} target={desired} {reason} {action}",flush=True)
                # Persist progress for recovery and the demo viewer.
                save_csv(directory/'decisions.csv',decisions)
                latest=ROOT/'output'/'live'/'latest.json'
                temporary=latest.with_suffix('.tmp')
                temporary.write_text(json.dumps(dict(directory=str(directory),
                    backend=fleet.backend,**decision),indent=2),encoding='utf-8')
                temporary.replace(latest)
                state=await fleet.status()
                next_window+=1
            await asyncio.sleep(min(1,max(.01,args.duration-(time.perf_counter()-started))))
        snapshots.append(dict(elapsed_s=time.perf_counter()-started,**(await fleet.status())))
        await task
        result=summarize(load,snapshots,decisions,args)
        (directory/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print('RESULT',json.dumps(result),flush=True)
        print('SAVED',directory,flush=True)
        return directory,result
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        if load is not None:
            load.save(directory/'requests.csv')
        save_csv(directory/'resources.csv',snapshots)
        save_csv(directory/'decisions.csv',decisions)
        if server is not None:
            server.close();await server.wait_closed()
        if mode=='active':
            await fleet.close()


async def main(args):
    if args.command=='calibrate':
        all_results=[]
        for rate in args.rates:
            clone=argparse.Namespace(**vars(args))
            clone.safe_rps=rate;clone.duration=args.seconds;clone.warmup=min(5,args.seconds/4)
            clone.policy='fixed';clone.maximum=1;clone.scenario='constant'
            path,result=await run_once(clone)
            passed=(result['p95_ms'] is not None and result['p95_ms']<=args.sla_ms and
                    result['success_fraction']>=.99 and result['sla_violating_window_fraction']==0 and
                    not result['validity_warning'])
            all_results.append(dict(rate_rps=rate,passed=passed,path=str(path),**result))
        # Retain earlier calibration passes and boundary repeats; comparison
        # runs and different CPU workloads must never contaminate calibration.
        all_results=[]
        environment=environment_signature()
        for path in (ROOT/'output'/'live').glob('*/summary.json'):
            cfg=json.loads((path.parent/'config.json').read_text())
            if cfg.get('command')!='calibrate' or cfg.get('backend')!=args.backend or cfg.get('iterations')!=args.iterations:
                continue
            if any(cfg.get(key)!=value for key,value in environment.items()):
                continue
            measured=json.loads(path.read_text())
            passed=(measured['p95_ms'] is not None and measured['p95_ms']<=args.sla_ms and
                    measured['success_fraction']>=.99 and measured['sla_violating_window_fraction']==0 and
                    not measured['validity_warning'])
            all_results.append(dict(rate_rps=cfg['safe_rps'],passed=passed,path=str(path.parent),**measured))
        rates={r['rate_rps'] for r in all_results}
        passing=[rate for rate in rates if all(r['passed'] for r in all_results if r['rate_rps']==rate)]
        result=dict(backend=args.backend,iterations=args.iterations,sla_ms=args.sla_ms,
                    **environment,
                    passing_rule='every repeated run: global p95 and all nonempty-window p95 <= SLA; success >=99%; valid generator',
                    highest_passing_rps=max(passing) if passing else None,
                    recommended_safe_rps=max(passing)*.8 if passing else None,points=all_results)
        target=ROOT/'output'/'live'/f'calibration-{args.backend}.json'
        target.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print('CALIBRATION',json.dumps({k:v for k,v in result.items() if k!='points'}),flush=True)
    else:
        await run_once(args)


def parser():
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['run','calibrate'])
    p.add_argument('--backend',choices=['local','kubernetes'],default='local')
    p.add_argument('--mode',choices=['active','shadow'],default='active',help='shadow observes an existing Kubernetes service without changing replicas, including startup/cleanup')
    p.add_argument('--url',default='http://127.0.0.1:18080')
    p.add_argument('--policy',default='guarded_predictive',choices=['fixed','reactive','plain_predictive','guarded_predictive'])
    p.add_argument('--scenario',default='periodic',choices=['periodic','ramp','flash','constant'])
    p.add_argument('--safe-rps',type=float,default=15)
    p.add_argument('--duration',type=float,default=240)
    p.add_argument('--warmup',type=float,default=60)
    p.add_argument('--interval',type=float,default=10)
    p.add_argument('--maximum',type=int,default=4)
    p.add_argument('--startup',type=float,default=5)
    p.add_argument('--iterations',type=int,default=60000)
    p.add_argument('--sla-ms',type=float,default=250)
    p.add_argument('--stabilization',type=float,default=30)
    p.add_argument('--hourly-rate',type=float,default=.02)
    p.add_argument('--hourly-budget',type=float)
    p.add_argument('--bias',type=float,default=1)
    p.add_argument('--seed',type=int,default=101)
    p.add_argument('--rates',type=float,nargs='+',default=[5,10,20,30])
    p.add_argument('--seconds',type=float,default=30)
    return p


if __name__=='__main__':
    args=parser().parse_args()
    if args.command=='run' and not 0<=args.warmup<args.duration:
        raise SystemExit('warmup must be less than duration')
    asyncio.run(main(args))
