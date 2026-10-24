"""Verify the matched live experiment manifest and summarize measured results."""
from pathlib import Path
from collections import defaultdict
import csv
import hashlib
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
LIVE=ROOT/'output'/'live'
OUT=ROOT/'output'/'evaluation'


def main():
    matrix=json.loads((LIVE/'matrix.json').read_text())
    completed=matrix['completed']
    expected={tuple(x) for x in matrix['run_order']}
    received={(r['summary']['scenario'],r['summary']['seed'],r['summary']['policy']) for r in completed}
    if received!=expected or len(completed)!=len(expected):
        raise SystemExit(f'Comparison suite incomplete: {len(received)}/{len(expected)} runs.')
    OUT.mkdir(parents=True,exist_ok=True)
    groups=defaultdict(list);schedules=defaultdict(set);code=set();models=set();readiness=[]
    verified=[]
    for run in completed:
        directory=LIVE/str(run['directory']).replace('\\','/').rsplit('/',1)[-1]
        config=json.loads((directory/'config.json').read_text())
        result=json.loads((directory/'summary.json').read_text())
        assert result['validity_warning'] is None, f'Invalid generator: {directory.name}'
        assert result['generator_capacity_drops']==0
        code.add(config['code_sha256'])
        models.add(hashlib.sha256((directory/'model.json').read_bytes()).hexdigest())
        actual_hash=hashlib.sha256((directory/'arrivals.csv').read_bytes()).hexdigest()
        assert actual_hash==config['arrival_schedule_sha256']
        schedules[(result['scenario'],result['seed'])].add(actual_hash)
        groups[(result['scenario'],result['policy'])].append(result)
        verified.append(dict(run=directory.name,**result))
        with (directory/'decisions.csv').open() as f:
            decisions=list(csv.DictReader(f))
        with (directory/'resources.csv').open() as f:
            resources=list(csv.DictReader(f))
        for decision in decisions:
            if decision['action']!='SCALE' or int(decision['target'])<=int(decision['desired']):
                continue
            first=next((s for s in resources if float(s['elapsed_s'])>=float(decision['elapsed_s']) and int(s['ready'])>=int(decision['target'])),None)
            if first:
                readiness.append(float(first['elapsed_s'])-float(decision['elapsed_s']))
    assert len(code)==1, 'Source changed between compared runs'
    assert len(models)==1, 'Model changed between compared runs'
    assert all(len(values)==1 for values in schedules.values()), 'Arrival schedule mismatch'
    rows=[]
    for (scenario,policy),results in sorted(groups.items()):
        rows.append(dict(scenario=scenario,policy=policy,repeats=len(results),
            p95_mean_of_runs_ms=float(np.mean([r['p95_ms'] for r in results])),
            p95_min_ms=min(r['p95_ms'] for r in results),p95_max_ms=max(r['p95_ms'] for r in results),
            mean_failure_fraction=float(np.mean([r['failure_fraction'] for r in results])),
            mean_sla_violating_window_fraction=float(np.mean([r['sla_violating_window_fraction'] for r in results])),
            mean_replica_seconds=float(np.mean([r['replica_seconds'] for r in results])),
            mean_worker_cpu_utilization=float(np.mean([r['mean_worker_cpu_utilization'] for r in results])),
            mean_estimated_cost=float(np.mean([r['estimated_cost'] for r in results])),
            mean_energy_proxy_wh=float(np.mean([r['energy_proxy_wh'] for r in results])),
            mean_forecast_mae_rps=float(np.mean([r['forecast_mae_rps'] for r in results])),
            mean_persistence_mae_rps=float(np.mean([r['persistence_mae_rps'] for r in results]))))
    for name,data in [('matched_runs.csv',verified),('comparison.csv',rows)]:
        with (OUT/name).open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    audit=dict(complete_runs=len(completed),matched_schedules=len(schedules),
        identical_source=True,identical_model=True,source_sha256=next(iter(code)),model_sha256=next(iter(models)),
        generator_capacity_drops=0,
        sampled_window_end_to_ready_median_s=float(np.median(readiness)) if readiness else None,
        sampled_window_end_to_ready_p95_s=float(np.percentile(readiness,95)) if readiness else None,
        readiness_note='Window end to sampled Ready state; includes decision/proxy latency; not exact container boot time.',
        units='p95 is summarized across runs with min/max; cost/energy are proxies, not cloud bills/physical measurements',
        results=rows)
    (OUT/'audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    fig,axes=plt.subplots(1,2,figsize=(8.5,5.8))
    colors={'fixed':'#6a7c90','reactive':'#bd7033','guarded_predictive':'#008d83'}
    labels=[]
    for i,row in enumerate(rows):
        label=row['scenario'].title()+'\n'+{'fixed':'Fixed','reactive':'Reactive','guarded_predictive':'Predictive'}[row['policy']]
        labels.append(label)
        axes[0].bar(i,row['mean_replica_seconds'],color=colors[row['policy']])
        axes[1].bar(i,row['p95_mean_of_runs_ms'],color=colors[row['policy']])
        axes[1].errorbar(i,row['p95_mean_of_runs_ms'],
            yerr=[[row['p95_mean_of_runs_ms']-row['p95_min_ms']],[row['p95_max_ms']-row['p95_mean_of_runs_ms']]],
            fmt='none',ecolor='#243348',capsize=4)
    axes[0].set_ylabel('Mean allocated replica-seconds (lower is less resource)')
    axes[1].set_ylabel('Mean run p95 latency, ms (whiskers = min/max)')
    axes[1].axhline(250,color='#a63333',ls='--',label='250 ms target');axes[1].legend(fontsize=8)
    for ax in axes:
        ax.set_xticks(range(len(rows)),labels,rotation=40,ha='right',fontsize=10)
        ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    fig.suptitle('MEASURED KUBERNETES COMPARISON | two repeats per scenario/policy\nIdentical arrivals, model, source, limits and scoring intervals',fontsize=12)
    fig.tight_layout();fig.savefig(OUT/'comparison.png',dpi=160);fig.savefig(OUT/'comparison.svg');plt.close(fig)
    print(json.dumps(audit,indent=2))


if __name__=='__main__':
    main()
