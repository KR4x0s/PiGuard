#!/usr/bin/env python3
"""Benchmark the two memory-eligible candidates before the held-out test."""
import json
import subprocess
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
run=root/'runs/2026-10-25-baseline'
output=run/'benchmark-pi-batch500.json'
if output.exists():
    raise SystemExit('Benchmark evidence already exists; preserve it')
choices=json.loads((run/'candidates.json').read_text())
results={}
for name in ('logistic_regression','compact_random_forest'):
    release=run/'candidates'/name
    command=[sys.executable,'-m','piguard.benchmark','--release',str(release),
             '--manifest-sha256',choices[name]['manifest_sha256'],
             '--batch-size','500','--batches','20']
    completed=subprocess.run(command,capture_output=True,text=True,check=True)
    results[name]=json.loads(completed.stdout)
    print(name,json.dumps(results[name]),flush=True)
output.write_text(json.dumps(results,indent=2)+'\n')
print('Saved',output)
