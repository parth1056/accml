"""Real HTTP fault-injection checks, kept separate from the matched main suite."""
import asyncio
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scaler.experiment import parser,run_once


async def main():
    results=[]
    order=['plain_predictive','guarded_predictive']
    random.Random(918).shuffle(order)
    for policy in order:
        args=parser().parse_args(['run','--backend','kubernetes','--safe-rps','14.4',
            '--scenario','periodic','--policy',policy,'--bias','0','--seed','404',
            '--duration','240','--warmup','60'])
        directory,result=await run_once(args)
        # Label the injected condition without altering measured metric values.
        result['scenario']='zero-forecast stress'
        (directory/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        results.append(dict(condition='forecast multiplier = 0; base workload = periodic',
                            directory=str(directory),summary=result))
    hashes=[hashlib.sha256((Path(r['directory'])/'arrivals.csv').read_bytes()).hexdigest() for r in results]
    assert len(set(hashes))==1,'Fault-check arrival schedules differ'
    args=parser().parse_args(['run','--backend','kubernetes','--safe-rps','14.4',
        '--scenario','periodic','--policy','guarded_predictive','--hourly-budget','.02',
        '--seed','505','--duration','120','--warmup','30'])
    directory,result=await run_once(args)
    result['scenario']='one-replica budget stress'
    (directory/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    results.append(dict(condition='hourly rate budget .02 / per-replica .02 = one desired replica',
                        directory=str(directory),summary=result))
    output=ROOT/'output'/'evaluation';output.mkdir(parents=True,exist_ok=True)
    (output/'fault_checks.json').write_text(json.dumps(dict(results=results,
        notes='Zero-forecast checks share an identical periodic arrival schedule and seed; one repeat each. Budget check is a separate stress case. Summary scenario labels describe the injection; configs retain the underlying periodic workload.'),indent=2),encoding='utf-8')
    print('Real fault-injection checks saved.',flush=True)


if __name__=='__main__':asyncio.run(main())
