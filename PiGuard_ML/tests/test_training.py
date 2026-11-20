import numpy as np
import pandas as pd
import pytest
from piguard.training import clean_data, split_data, select_threshold, metrics, binary_label


def test_conflict_and_effective_label_dedup():
    raw = pd.DataFrame({'domain': ['www.foo.com','foo.net','foo','bar.com','bar.net','baz','bad..com'],
                        'class': [0,0,0,0,1,1,0]})
    clean, audit = clean_data(raw)
    assert set(clean.effective_label) == {'foo','baz'}
    assert audit['conflicting_groups'] == 1
    assert audit['conflicting_rows'] == 2
    assert audit['duplicates_removed'] == 2
    assert audit['invalid_rows'] == 1


def test_split_has_no_label_overlap_and_is_reproducible():
    data = pd.DataFrame({'effective_label': [f'd{i}' for i in range(200)], 'label': [0,1]*100})
    first, second = split_data(data), split_data(data)
    assert [len(first[k]) for k in first] == [140,30,30]
    for key in first:
        assert first[key].equals(second[key])
    assert not set(first['train'].effective_label) & set(first['test'].effective_label)
    assert not set(first['validation'].effective_label) & set(first['test'].effective_label)


def test_threshold_handles_ties_and_rejects_no_recall():
    assert select_threshold([0,0,1,1], [.1,.3,.7,.9], 0) == .7
    assert select_threshold([0,1], [.9,.9], 0) is None
    assert select_threshold([0,0,1], [0,0,1], 0) == 1
    assert select_threshold([0,1], [1,0], 0) is None


def test_threshold_matches_brute_force():
    rng = np.random.default_rng(5)
    y = rng.integers(0,2,300)
    scores = np.round(rng.random(300),2)
    threshold = select_threshold(y,scores,.15)
    accepted = [metrics(y,scores,t) for t in np.unique(scores)]
    accepted = [m for m in accepted if m['false_positive_rate'] <= .15 and m['recall'] > 0]
    best = max(accepted,key=lambda m:(m['recall'],m['precision'],m['threshold']))
    assert threshold == best['threshold']


def test_metrics_zero_positive_and_ci():
    result = metrics([0,0,1,1], np.array([.1,.1,.9,.1]), .5)
    assert result['confusion_matrix'] == [[2,0],[1,1]]
    assert result['recall'] == .5
    assert 0 < result['recall_95ci'][0] < .5 < result['recall_95ci'][1] < 1
    with pytest.raises(ValueError):
        binary_label('unknown')
