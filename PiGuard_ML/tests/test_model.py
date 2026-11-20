import json
import shutil
import pandas as pd
import pytest
from sklearn.ensemble import RandomForestClassifier
import piguard_dga_features as features
from piguard.model import Scorer, verify_release
from piguard.training import export_candidate, seal_release

@pytest.fixture(scope='module')
def release(tmp_path_factory):
    path=tmp_path_factory.mktemp('model')/'release'
    values=['garden'+chr(97+i) for i in range(12)]+['x8z'+str(i)+'q9v' for i in range(12)]
    frame=pd.DataFrame({'effective_label':values,'label':[0]*12+[1]*12})
    model=RandomForestClassifier(n_estimators=8,max_depth=3,random_state=42).fit(features.feature_frame(values,'label'),frame.label)
    digest=export_candidate(path,model,'fixture',.5,{}, {'fixture':True},frame,.01)
    return path,digest


def test_verified_reference_predictions_cache_and_skip(release):
    path,digest=release
    scorer=Scorer(path,digest,cache_size=1)
    names=['gardena.com','x8z1q9v.com','printer.local','gardena.net']
    first=scorer.score(names)
    assert first[0]['dga_score']==first[-1]['dga_score']
    assert first[1]['suspicious']
    assert first[2]=={'status':'skipped','reason':'special_use_name'}
    assert first==scorer.score(names)
    assert len(scorer.cache)==1


def test_corruption_rejected_before_load(release,tmp_path,monkeypatch):
    import piguard.model as module
    path,digest=release
    def forbidden(*args,**kwargs):
        raise AssertionError('joblib must not run')
    monkeypatch.setattr(module.joblib,'load',forbidden)
    with pytest.raises(ValueError,match='manifest'):
        Scorer(path,'0'*64)
    dest=tmp_path/'copy'
    shutil.copytree(path,dest)
    (dest/'piguard_dga_model.joblib').write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='hash'):
        Scorer(dest,digest)

@pytest.mark.parametrize('field,value', [('feature_version','wrong'), ('feature_names',[]),
    ('extraction_policy','other'),('feature_sha256','wrong'),('python_version','0.0.0'),('decision_threshold',2)])
def test_contract_mismatch(release,tmp_path,field,value):
    path,_=release
    dest=tmp_path/'copy'
    shutil.copytree(path,dest)
    contract=json.loads((dest/'feature_contract.json').read_text())
    contract[field]=value
    (dest/'feature_contract.json').write_text(json.dumps(contract))
    with pytest.raises(ValueError):
        verify_release(dest,seal_release(dest))


def test_dependency_and_reference_mismatch(release,tmp_path):
    path,_=release
    dest=tmp_path/'copy'
    shutil.copytree(path,dest)
    vectors=json.loads((dest/'test_vectors.json').read_text())
    vectors[0]['score']+=.5
    (dest/'test_vectors.json').write_text(json.dumps(vectors))
    with pytest.raises(ValueError,match='prediction'):
        Scorer(dest,seal_release(dest))
    contract=json.loads((dest/'feature_contract.json').read_text())
    contract['dependencies']['numpy']='0.0.0'
    (dest/'feature_contract.json').write_text(json.dumps(contract))
    with pytest.raises(ValueError,match='Dependency'):
        verify_release(dest,seal_release(dest))
