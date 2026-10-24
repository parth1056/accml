"""Causal model with portable JSON coefficients; NumPy needed only by host."""
import json
import argparse
from pathlib import Path
import numpy as np
from planning_pilot.pilot import Ridge, features, supervised


def demand_history(seed, size=720):
    """Training family spans both short demo cycles and slower demand changes."""
    rng=np.random.default_rng(seed)
    t=np.arange(size)
    period=rng.uniform(9,90)
    amplitude=rng.uniform(35,100)
    trace=135+amplitude*np.sin(2*np.pi*t/period+rng.uniform(0,6))
    trace+=15*np.sin(2*np.pi*t/(period*2.2))
    return np.maximum(2,trace+rng.normal(0,5,size))


class Forecaster:
    def __init__(self, safe_rps, bias=1):
        self.safe_rps, self.bias = safe_rps, bias
        self.normalizer = 70 / safe_rps
        xy = [supervised(demand_history(seed)) for seed in range(12)]
        x = np.concatenate([a for a, _ in xy])
        y = np.concatenate([b for _, b in xy])
        validation=[supervised(demand_history(seed)) for seed in range(50,56)]
        vx=np.concatenate([a for a,_ in validation]);vy=np.concatenate([b for _,b in validation])
        selected = []
        for alpha in (1, 10, 100):
            m = Ridge().fit(x, y, alpha)
            selected.append((float(abs(m.predict(vx)-vy).mean()), alpha, m))
        self.mae, self.alpha, self.model = min(selected, key=lambda a:a[0])
        self.persistence_mae=float(abs(vx[:,5]-vy).mean())/self.normalizer
        self.buffer = float(np.quantile(np.maximum(vy-self.model.predict(vx),0),.9))/self.normalizer

    @classmethod
    def load(cls,path,bias=1):
        record=json.loads(Path(path).read_text())
        obj=cls.__new__(cls)
        obj.safe_rps=record['safe_rps'];obj.normalizer=70/obj.safe_rps;obj.bias=bias
        obj.alpha=record['alpha'];obj.mae=record['validation_mae_rps']*obj.normalizer
        obj.persistence_mae=record['persistence_validation_mae_rps']
        obj.buffer=record['buffer_rps'];obj.model=Ridge()
        obj.model.mean=np.asarray(record['mean']);obj.model.scale=np.asarray(record['scale'])
        obj.model.coef=np.asarray(record['coefficients'])
        return obj

    def predict(self, history):
        if len(history) < 6:
            return None
        return float(self.model.predict(features(np.asarray(history)*self.normalizer))[0])/self.normalizer*self.bias

    def save(self, path, interval):
        Path(path).write_text(json.dumps(dict(algorithm='standardized_ridge', alpha=self.alpha,
            training_source='synthetic demand traces, seeds 0..11; periods 9..90 windows', validation_seeds=list(range(50,56)),
            safe_rps=self.safe_rps, feature_windows=6, target_peak_windows=3,
            horizon_seconds=interval*3, forecast_bias=self.bias, buffer_rps=self.buffer,
            mean=self.model.mean.tolist(), scale=self.model.scale.tolist(),
            coefficients=self.model.coef.tolist(),
            persistence_validation_mae_rps=self.persistence_mae,
            validation_mae_rps=self.mae/self.normalizer),indent=2),encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--safe-rps',type=float,required=True)
    p.add_argument('--interval',type=float,default=10)
    p.add_argument('--output',default='output/trained_model.json')
    args=p.parse_args()
    model=Forecaster(args.safe_rps)
    model.save(args.output,args.interval)
    x,y=supervised(demand_history(99))
    predicted=model.model.predict(x)/model.normalizer
    actual=y/model.normalizer
    persistence=x[:,5]/model.normalizer
    metrics=dict(training_rows=12*len(y),validation_rows=6*len(y),test_seed=99,
                 test_mae_rps=float(abs(predicted-actual).mean()),
                 test_rmse_rps=float(np.sqrt(np.mean((predicted-actual)**2))),
                 persistence_test_mae_rps=float(abs(persistence-actual).mean()),
                 data_source='synthetic traces; model-only holdout, not HTTP performance')
    destination=Path(args.output).with_name('training_evaluation.json')
    destination.write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(10,4))
    t=np.arange(len(y))*args.interval
    ax.plot(t[:150],actual[:150],label='Actual next-30s peak target',color='#20374c')
    ax.plot(t[:150],predicted[:150],label='Ridge prediction',color='#008d83')
    ax.plot(t[:150],persistence[:150],label='Persistence baseline',alpha=.45)
    ax.set(xlabel='Forecast issue time in synthetic test trace (seconds)',ylabel='Requests / second',
           title='Trained workload predictor | independent synthetic holdout seed 99')
    ax.legend();ax.grid(alpha=.15);fig.tight_layout()
    fig.savefig(Path(args.output).with_name('trained_forecast.png'),dpi=150);plt.close(fig)
    print(json.dumps(dict(model=str(args.output),alpha=model.alpha,**metrics),indent=2))
