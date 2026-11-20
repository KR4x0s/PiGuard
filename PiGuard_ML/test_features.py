import math
import pytest
from piguard_dga_features import (FEATURE_NAMES, InputError, candidate_dga_label,
                                 extract_features, feature_frame, normalize_domain, project_domain)

@pytest.mark.parametrize('name,domain,label', [
    ('WWW.Example.COM.', 'example.com', 'example'),
    ('a.example.co.uk', 'example.co.uk', 'example'),
    ('abc123.example.com', 'example.com', 'example'),
    ('bücher.de', 'xn--bcher-kva.de', 'xn--bcher-kva'),
    ('a.www.ck', 'www.ck', 'www'),
    ('a.b.ck', 'a.b.ck', 'a'),
    ('alice.blogspot.com', 'blogspot.com', 'blogspot'),
])
def test_projection(name, domain, label):
    assert project_domain(name) == (domain, label)

@pytest.mark.parametrize('value', [None, float('nan'), '', ' ', '.bad.com', 'bad..com',
    '-bad.com', 'bad-.com', 'a'*64+'.com', 'a_b.com', 'https://example.com/a',
    'example.com:443', 'name@example.com', '127.0.0.1', '::1', 'xn--.com'])
def test_reject_malformed(value):
    with pytest.raises(InputError):
        normalize_domain(value)

@pytest.mark.parametrize('name', ['printer', 'printer.local', 'x.home.arpa',
    '1.0.0.127.in-addr.arpa', 'example.invalid', 'example.test', 'x.unknownsuffixzz', 'co.uk'])
def test_skip_non_public(name):
    with pytest.raises(InputError):
        project_domain(name)


def test_label_mode_is_explicit():
    assert candidate_dga_label('GOOGLE', 'label') == 'google'
    with pytest.raises(InputError):
        candidate_dga_label('google')
    with pytest.raises(InputError):
        candidate_dga_label('google.com', 'label')


def test_known_feature_values_and_order():
    result = extract_features('abc123.com')
    assert list(result) == FEATURE_NAMES
    assert all(math.isfinite(x) for x in result.values())
    assert result['label_length'] == 6
    assert result['digit_ratio'] == .5
    assert result['entropy'] == pytest.approx(math.log2(6))
    assert result['max_digit_run'] == 3
    assert result['vowel_ratio'] == pytest.approx(1/3)
    assert result['hex_char_ratio'] == 1
    matrix = feature_frame(['example.com', 'x9.com'])
    assert matrix.shape == (2, 11)
    assert list(matrix) == FEATURE_NAMES
