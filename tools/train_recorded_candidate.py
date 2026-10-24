"""Train a separate candidate on recorded HTTP demand, without altering benchmarks.

Train seeds 101, validate 202, test 404. Only offered arrivals are used;
allocation/response success cannot become an oracle feature. The published
12-run suite keeps its original model. This candidate is not auto-promoted.
"""
from pathlib import Path
import csv
import hashlib
import json
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from planning_pilot.pilot import Ridge,supervised


def trace(directory):
    with (directory/'requests.csv').open() as f:
        records=list(csv.DictReader(f))
    config=json.loads((directory/'config.json').read_text())
    values=[sum(left<=float(r['sent_s'])<left+10 for r in records)/10
            for left in range(0,int(config['duration']),10)]
    return np.asarray(values)


def main():
    matrix=json.loads((ROOT/'output/live/matrix.json').read_text())
    faults=json.loads((ROOT/'output/evaluation/fault_checks.json').read_text())
    def directory(item):
        return ROOT/'output/live'/str(item['directory']).replace('\\','/').rsplit('/',1)[-1]
    train=[directory(r) for r in matrix['completed'] if r['summary']['policy']=='fixed' and r['summary']['seed']==101]
    validation=next(directory(r) for r in matrix['completed'] if r['summary']['policy']=='fixed' and r['summary']['seed']==202 and r['summary']['scenario']=='periodic')
    test=next(directory(r) for r in faults['results'] if r['summary']['policy']=='guarded_predictive' and r['summary']['seed']==404)
    normalizer=70/14.4
    xy=[supervised(trace(p)*normalizer) for p in train]
    x=np.concatenate([a for a,_ in xy]);y=np.concatenate([b for _,b in xy])
    vx,vy=supervised(trace(validation)*normalizer)
    tx,ty=supervised(trace(test)*normalizer)
    candidates=[]
    for alpha in (1,10,100):
        model=Ridge().fit(x,y,alpha)
        candidates.append((float(abs(model.predict(vx)-vy).mean()),alpha,model))
    mae,alpha,model=min(candidates,key=lambda row:row[0])
    primary=json.loads((ROOT/'output/trained_model.json').read_text())
    stock=Ridge();stock.mean=np.asarray(primary['mean']);stock.scale=np.asarray(primary['scale']);stock.coef=np.asarray(primary['coefficients'])
    predicted=model.predict(tx);original=stock.predict(tx)
    metrics=dict(training_rows=len(y),validation_rows=len(vy),test_rows=len(ty),alpha=alpha,
        candidate_test_mae_rps=float(abs(predicted-ty).mean()/normalizer),
        candidate_test_rmse_rps=float(np.sqrt(np.mean((predicted-ty)**2))/normalizer),
        primary_test_mae_rps=float(abs(original-ty).mean()/normalizer),
        persistence_test_mae_rps=float(abs(tx[:,5]-ty).mean()/normalizer),
        promoted=False,
        notes='Exploratory recorded-replay candidate with a small holdout. The 12-run benchmark still uses the original frozen synthetic-trained model. Traffic is synthetic replay measured through actual HTTP sends, not production traffic.')
    sources=dict(training=[p.name for p in train],validation=validation.name,test=test.name)
    candidate={**primary,'alpha':alpha,'training_source':'recorded HTTP offered-demand traces, seed 101',
        'validation_source':validation.name,'test_source':test.name,'training_rows':len(y),
        'validation_mae_rps':mae/normalizer,
        'persistence_validation_mae_rps':float(abs(vx[:,5]-vy).mean()/normalizer),
        'buffer_rps':float(np.quantile(np.maximum(vy-model.predict(vx),0),.9)/normalizer),
        'mean':model.mean.tolist(),'scale':model.scale.tolist(),'coefficients':model.coef.tolist(),
        'forecast_bias':1,'data_provenance':sources,'promoted':False}
    candidate.pop('validation_seeds',None)
    (ROOT/'output/recorded_model_candidate.json').write_text(json.dumps(candidate,indent=2),encoding='utf-8')
    (ROOT/'output/evaluation/recorded_training.json').write_text(json.dumps(dict(**metrics,sources=sources),indent=2),encoding='utf-8')
    print(json.dumps(metrics,indent=2))


if __name__=='__main__':main()
