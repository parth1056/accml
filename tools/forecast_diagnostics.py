"""Score frozen predictions and past-only baselines on the completed matrix.

This does not train, tune, or replace a model or alter benchmark inputs.
"""
import csv
import json
from pathlib import Path
from statistics import mean

ROOT=Path(__file__).resolve().parents[1]


def main():
    live=ROOT/'output'/'live'
    matrix=json.loads((live/'matrix.json').read_text())
    rows=[]
    for entry in matrix['completed']:
        if entry['summary']['policy']!='guarded_predictive':
            continue
        directory=live/entry['directory'].replace('\\','/').rsplit('/',1)[-1]
        config=json.loads((directory/'config.json').read_text())
        with (directory/'decisions.csv').open(newline='',encoding='utf-8') as handle:
            decisions=list(csv.DictReader(handle))
        with (directory/'requests.csv').open(newline='',encoding='utf-8') as handle:
            sends=[float(row['sent_s']) for row in csv.DictReader(handle)]
        history=[]
        local=[]
        interval=config['interval']
        for decision in decisions:
            issued=float(decision['elapsed_s'])
            observed=float(decision['observed_rps'])
            history.append(observed)
            if issued<config['warmup'] or issued+3*interval>config['duration'] or not decision['forecast_rps']:
                continue
            actual=max(sum(issued+k*interval<=sent<issued+(k+1)*interval for sent in sends)/interval
                       for k in range(3))
            # Future demand labels this evaluation slice only; it is never a feature.
            threshold=max(2,.2*observed)
            phase='rising' if actual>observed+threshold else 'falling' if actual<observed-threshold else 'stable'
            local.append(dict(run=directory.name,scenario=config['scenario'],seed=config['seed'],
                              issued_s=issued,phase=phase,actual_peak_rps=actual,
                              ridge_rps=float(decision['forecast_rps']),persistence_rps=observed,
                              moving_mean_5_rps=mean(history[-5:])))
        assert local, f'No forecast targets in {directory.name}'
        for key,summary_key in [('ridge_rps','forecast_mae_rps'),('persistence_rps','persistence_mae_rps')]:
            actual_mae=mean(abs(row[key]-row['actual_peak_rps']) for row in local)
            assert abs(actual_mae-entry['summary'][summary_key])<1e-9, 'Target alignment differs from benchmark'
        rows.extend(local)
    assert len({row['run'] for row in rows})==4, 'Expected four guarded runs in the frozen matrix'
    groups={'all':rows}
    groups.update({phase:[row for row in rows if row['phase']==phase] for phase in ('rising','falling','stable')})
    scores={name:dict(targets=len(group),mae_rps={key:mean(abs(row[key]-row['actual_peak_rps']) for row in group)
                  if group else None for key in ('ridge_rps','persistence_rps','moving_mean_5_rps')})
            for name,group in groups.items()}
    report=dict(source='Frozen main matrix: four guarded runs; two scenarios x two seeds',
                horizon='Peak actual offered RPS over the next three 10-second windows',
                moving_mean='Mean of the last five completed observed windows; no future inputs',
                phase_rule='Rising/falling if future peak differs from current observed RPS by more than max(2 RPS, 20%); otherwise stable. Evaluation labels only.',
                limitation='Small synthetic replay suite; exploratory diagnostics, not model selection or production validation.',
                scores=scores)
    out=ROOT/'output'/'evaluation'
    out.mkdir(parents=True,exist_ok=True)
    (out/'forecast_diagnostics.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    with (out/'forecast_diagnostics.csv').open('w',newline='',encoding='utf-8') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    print(json.dumps(scores,indent=2))


if __name__=='__main__':
    main()
