#!/usr/bin/env python3
"""Compare public-domain DNS probes without changing the client's resolver."""
import concurrent.futures
import datetime
import json
import re
import subprocess
from pathlib import Path

SERVERS=['192.168.31.235','192.168.31.1','1.1.1.1']
NAMES=['example.com','www.google.com','www.wikipedia.org','www.apple.com','mask.icloud.com','mask-h2.icloud.com']

def probe(item):
    server,name,kind=item
    command=['dig','@'+server,name,kind,'+time=2','+tries=1','+noall','+comments','+answer','+stats']
    try:
        result=subprocess.run(command,capture_output=True,text=True,timeout=4)
        match=re.search(r'status: ([A-Z]+)',result.stdout)
        ms=re.search(r'Query time: (\d+) msec',result.stdout)
        return {'server':server,'name':name,'type':kind,'exit_code':result.returncode,
                'status':match.group(1) if match else None,'latency_ms':int(ms.group(1)) if ms else None,
                'output':result.stdout}
    except subprocess.TimeoutExpired:
        return {'server':server,'name':name,'type':kind,'status':'timeout'}

if __name__=='__main__':
    work=[(s,n,k) for s in SERVERS for n in NAMES for k in ['A','AAAA']]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        records=list(pool.map(probe,work))
    timestamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path=Path(__file__).resolve().parents[2]/'PiGuard/evidence'/f'dns-comparison-{timestamp}.json'
    path.write_text(json.dumps(records,indent=2))
    for r in records:
        print(r['server'],r['name'],r['type'],r['status'],r.get('latency_ms'))
    print('Saved',path)
