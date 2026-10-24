"""Sequential matched comparisons, with frozen settings and saved run order."""
import argparse
import asyncio
import json
from pathlib import Path
import random
from scaler.experiment import parser, run_once


async def main(args):
    config=parser().parse_args(['run'])
    for name in ('backend','safe_rps','duration','warmup','iterations','startup','maximum'):
        setattr(config,name,getattr(args,name))
    combinations=[(scenario,seed,policy) for scenario in args.scenarios
                  for seed in args.seeds for policy in args.policies]
    random.Random(818).shuffle(combinations)
    root=Path(__file__).resolve().parents[1]/'output'/'live'
    root.mkdir(parents=True,exist_ok=True)
    manifest=dict(config=vars(config),run_order=combinations,completed=[])
    path=root/'matrix.json'
    path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    for scenario,seed,policy in combinations:
        config.scenario,config.seed,config.policy=scenario,seed,policy
        directory,result=await run_once(config)
        manifest['completed'].append(dict(directory=str(directory),summary=result))
        path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--backend',choices=['local','kubernetes'],default='local')
    p.add_argument('--safe-rps',type=float,required=True)
    p.add_argument('--duration',type=float,default=240)
    p.add_argument('--warmup',type=float,default=60)
    p.add_argument('--iterations',type=int,default=60000)
    p.add_argument('--startup',type=float,default=5)
    p.add_argument('--maximum',type=int,default=4)
    p.add_argument('--scenarios',nargs='+',default=['periodic','flash'])
    p.add_argument('--seeds',nargs='+',type=int,default=[101,202])
    p.add_argument('--policies',nargs='+',default=['fixed','reactive','guarded_predictive'])
    asyncio.run(main(p.parse_args()))
