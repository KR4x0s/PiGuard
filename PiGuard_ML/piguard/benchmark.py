"""Measure each model in its own process; power issues invalidate acceptance."""
import argparse
import json
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path


def worker(release,digest,batch_size=100,batches=50):
    import psutil
    process=psutil.Process()
    peak=[0]
    done=threading.Event()
    def sample():
        while not done.is_set():
            peak[0]=max(peak[0],process.memory_info().rss)
            done.wait(.01)
    thread=threading.Thread(target=sample,daemon=True)
    thread.start()
    started=time.perf_counter()
    from piguard.model import Scorer
    scorer=Scorer(release,digest)
    load_seconds=time.perf_counter()-started
    domains=[f'benchmark{i}letters.com' for i in range(batch_size)]
    times=[]
    cpu_start=process.cpu_times()
    wall_start=time.perf_counter()
    for _ in range(batches):
        scorer.cache.clear()
        start=time.perf_counter()
        scorer.score(domains)
        times.append((time.perf_counter()-start)*1000)
    wall=time.perf_counter()-wall_start
    cpu_end=process.cpu_times()
    done.set()
    thread.join()
    ordered=sorted(times)
    p95=ordered[min(len(ordered)-1,int(.95*len(ordered)))]
    return {'platform':platform.machine(),'python':platform.python_version(),
        'manifest_sha256':digest,'reference_vectors':'passed','model_id':scorer.contract['model_id'],
        'peak_rss_mib':peak[0]/1024**2,'batch_size':batch_size,
        'batch_p95_ms':p95,'load_seconds':load_seconds,'uncached_batches':batches,
        'cpu_one_core_percent':100*((cpu_end.user+cpu_end.system)-(cpu_start.user+cpu_start.system))/wall,
        'captured_at':time.time()}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path)
    p.add_argument('--output',type=Path)
    p.add_argument('--release',type=Path)
    p.add_argument('--manifest-sha256')
    p.add_argument('--batch-size',type=int,default=100)
    p.add_argument('--batches',type=int,default=50)
    args=p.parse_args()
    if args.release:
        if not args.manifest_sha256:
            p.error('--manifest-sha256 required with --release')
        if not 1<=args.batch_size<=5000 or not 2<=args.batches<=1000:
            p.error('Invalid benchmark size')
        print(json.dumps(worker(args.release,args.manifest_sha256,args.batch_size,args.batches)))
        return
    if not args.run or not args.output:
        p.error('--run and --output required')
    if args.output.exists():
        p.error('Output already exists; preserve prior evidence')
    choices=json.loads((args.run/'candidates.json').read_text())
    result={}
    for name,record in choices.items():
        if not record['eligible']:
            continue
        completed=subprocess.run([sys.executable,'-m','piguard.benchmark','--release',str(args.run/'candidates'/name),
            '--manifest-sha256',record['manifest_sha256'],'--batch-size',str(args.batch_size),
            '--batches',str(args.batches)],capture_output=True,text=True,check=True)
        result[name]=json.loads(completed.stdout)
        print(name,json.dumps(result[name]),flush=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')

if __name__=='__main__':
    main()
