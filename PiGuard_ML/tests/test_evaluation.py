"""Exercise final evaluation only on tiny disposable synthetic training runs."""
import json
import string
import pandas as pd
import pytest
from piguard.training import train,evaluate


def test_final_evaluation_gate_and_one_time_holdout(tmp_path,monkeypatch):
    monkeypatch.setenv('MPLCONFIGDIR',str(tmp_path/'mpl'))
    words=['garden'+a+b for a in string.ascii_lowercase[:8] for b in string.ascii_lowercase[:8]]
    noise=['x9z'+str(i)+'v8q7' for i in range(64)]
    dataset=tmp_path/'fixture.csv'
    pd.DataFrame({'domain':words+noise,'class':[0]*64+[1]*64}).to_csv(dataset,index=False)
    run=tmp_path/'run'
    train(dataset,run)
    choices=json.loads((run/'candidates.json').read_text())
    passing={k:v for k,v in choices.items() if v['eligible']}
    assert passing
    selected=max(passing,key=lambda n:(passing[n]['validation']['recall'],passing[n]['validation']['precision']))
    benchmark=tmp_path/'fixture-benchmark.json'
    (run/'evaluation_policy.json').write_text(json.dumps({'status':'locked_before_test_evaluation',
        'benchmark_evidence':benchmark.name,'requirements':{'platform':'aarch64',
        'reference_vectors':'passed','batch_size':500,'max_scorer_peak_rss_mib':256,
        'max_batch_p95_ms':2000}}))
    evidence={name:{'stable_power':False,'platform':'aarch64','reference_vectors':'passed',
        'manifest_sha256':record['manifest_sha256'],'peak_rss_mib':1,'batch_size':500,
        'batch_p95_ms':3000,
        'synthetic_test_fixture':True} for name,record in passing.items()}
    benchmark.write_text(json.dumps(evidence))
    with pytest.raises(ValueError,match='resource policy'):
        evaluate(run,selected,tmp_path/'release',benchmark)
    assert not (run/'FINAL_EVALUATED.json').exists()
    for item in evidence.values(): item['batch_p95_ms']=1000
    benchmark.write_text(json.dumps(evidence))
    evaluate(run,selected,tmp_path/'release',benchmark)
    assert (tmp_path/'release/evaluation.png').is_file()
    assert (tmp_path/'release/metrics.json').is_file()
    assert (run/'FINAL_EVALUATED.json').is_file()
    with pytest.raises(ValueError,match='consumed'):
        evaluate(run,selected,tmp_path/'another',benchmark)
