"""Plot measured live outputs; never merges simulated results into live charts."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]


def analyze(directory):
    directory=Path(directory)
    summary=json.loads((directory/'summary.json').read_text())
    with (directory/'requests.csv').open() as f:
        requests=list(csv.DictReader(f))
    with (directory/'decisions.csv').open() as f:
        decisions=list(csv.DictReader(f))
    with (directory/'resources.csv').open() as f:
        resources=list(csv.DictReader(f))
    fig,axes=plt.subplots(3,1,figsize=(11,8),sharex=True)
    if decisions:
        t=[float(d['elapsed_s']) for d in decisions]
        axes[0].plot(t,[float(d['observed_rps']) for d in decisions],label='Measured offered RPS',color='#20374c')
        axes[0].plot(t,[float(d['forecast_rps']) if d['forecast_rps'] else np.nan for d in decisions],label='Forecast next-30s peak (issue time)',color='#008d83')
        for d in decisions:
            if d['action']=='SCALE':
                axes[1].annotate(d['reason'],(float(d['elapsed_s']),float(d['target'])),rotation=55,fontsize=6)
    axes[1].step([float(d['elapsed_s']) for d in resources],[int(d['ready']) for d in resources],where='post',label='Ready')
    axes[1].step([float(d['elapsed_s']) for d in resources],[int(d['allocated']) for d in resources],where='post',label='Allocated',alpha=.65)
    duration=summary['duration_s']
    window=[];p95=[];failure=[]
    for start in np.arange(0,duration,10):
        subset=[r for r in requests if start<=float(r['sent_s'])<start+10]
        values=[float(r['latency_ms']) for r in subset if int(r['status'])==200]
        window.append(start+10)
        p95.append(float(np.percentile(values,95)) if values else np.nan)
        failure.append(sum(int(r['status'])!=200 for r in subset)/len(subset) if subset else 0)
    axes[2].plot(window,p95,label='Measured successful-request p95',color='#b45426')
    axes[2].axhline(250,color='#af3030',ls='--',label='250 ms target')
    twin=axes[2].twinx();twin.plot(window,np.asarray(failure)*100,color='#666',alpha=.5,label='Errors %');twin.set_ylabel('Errors / timeouts (%)')
    for ax in axes:
        ax.axvspan(0,summary['warmup_s'],color='#dce4ed',alpha=.4)
        ax.grid(alpha=.15);ax.legend(loc='upper left',fontsize=8)
    axes[0].set_ylabel('Requests/s');axes[1].set_ylabel('Real replicas');axes[2].set_ylabel('Latency (ms)')
    axes[2].set_xlabel('Wall-clock elapsed seconds (shaded = unscored warm-up)')
    fig.suptitle(f"MEASURED HTTP RUN | {summary['backend']} | {summary['scenario']} | {summary['policy']} | {summary.get('controller_mode','active')}\nSynthetic arrivals; real service/latency/replica observations",fontsize=12)
    fig.tight_layout();fig.savefig(directory/'measured_run.png',dpi=150);plt.close(fig)
    return summary


def main(args):
    paths=[Path(args.run)] if args.run else [p.parent for p in (ROOT/'output'/'live').glob('*/summary.json')]
    results=[]
    for path in paths:
        result=analyze(path)
        if result['scenario']!='constant':
            results.append(dict({'run':path.name,'controller_mode':'active',
                                 'shadow_recommendations':0},**result))
    if results:
        with (ROOT/'output'/'live'/'comparison.csv').open('w',newline='',encoding='utf-8') as f:
            fields=list(dict.fromkeys(key for result in results for key in result))
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(results)
    print(f'Plotted {len(paths)} measured runs; {len(results)} comparison rows.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run');main(p.parse_args())
