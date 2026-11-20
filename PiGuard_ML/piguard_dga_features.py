"""Versioned, offline lexical feature contract shared by training and inference."""
from __future__ import annotations

import ipaddress
import math
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import idna
import pandas as pd
import tldextract

FEATURE_VERSION = "3.0.0"
FEATURE_NAMES = ["label_length", "entropy", "digit_ratio", "alpha_ratio", "hyphen_ratio",
                 "vowel_ratio", "unique_char_ratio", "max_consonant_run", "max_digit_run",
                 "hex_char_ratio", "has_punycode"]
PSL_PATH = Path(__file__).resolve().parent / "data/public_suffix_list.dat"
EXTRACTION_POLICY = "icann-registrable-label-idna-uts46-std3-v1"
SPECIAL_SUFFIXES = ("local", "localhost", "internal", "test", "invalid", "example",
                    "onion", "alt", "home.arpa", "in-addr.arpa", "ip6.arpa")


class InputError(ValueError):
    """A rejected input; its message is a stable, non-identifying reason code."""


def normalize_domain(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError("empty_or_non_string")
    text = value.strip().lower()
    if text.endswith("."):
        text = text[:-1]
    try:
        ipaddress.ip_address(text)
    except ValueError:
        pass
    else:
        raise InputError("ip_literal")
    if any(c in text for c in "/:?#@\\"):
        raise InputError("not_a_hostname")
    try:
        text = idna.encode(text, uts46=True, std3_rules=True).decode("ascii")
    except idna.IDNAError as exc:
        raise InputError("invalid_idna_or_hostname") from exc
    if len(text) > 253:
        raise InputError("hostname_too_long")
    return text


@lru_cache(maxsize=4)
def suffix_extractor(psl_path: str):
    path = Path(psl_path).resolve(strict=True)
    return tldextract.TLDExtract(suffix_list_urls=(path.as_uri(),), cache_dir=None,
                                fallback_to_snapshot=False, include_psl_private_domains=False)


def project_domain(value: object, mode: str = "dns", psl_path: Path = PSL_PATH) -> tuple[str, str]:
    text = normalize_domain(value)
    if mode == "label":
        if "." in text:
            raise InputError("expected_single_label")
        return text, text
    if mode != "dns":
        raise ValueError("mode must be dns or label")
    if "." not in text:
        raise InputError("local_single_label")
    if any(text == suffix or text.endswith("." + suffix) for suffix in SPECIAL_SUFFIXES):
        raise InputError("special_use_name")
    parts = suffix_extractor(str(psl_path.resolve()))(text)
    if not parts.suffix:
        raise InputError("unknown_suffix")
    if not parts.domain:
        raise InputError("public_suffix_only")
    return f"{parts.domain}.{parts.suffix}", parts.domain


def candidate_dga_label(value: object, mode: str = "dns", psl_path: Path = PSL_PATH) -> str:
    return project_domain(value, mode, psl_path)[1]


def _max_run(text: str, chars: str) -> int:
    best = run = 0
    for char in text:
        run = run + 1 if char in chars else 0
        best = max(best, run)
    return best


def label_features(label: str) -> dict[str, float]:
    length = len(label)
    if not length:
        raise InputError("empty_label")
    alpha = sum(c in "abcdefghijklmnopqrstuvwxyz" for c in label)
    counts = Counter(label)
    return dict(zip(FEATURE_NAMES, map(float, [
        length, -sum((n / length) * math.log2(n / length) for n in counts.values()),
        sum(c in "0123456789" for c in label) / length, alpha / length,
        label.count("-") / length, sum(c in "aeiou" for c in label) / alpha if alpha else 0,
        len(counts) / length, _max_run(label, "bcdfghjklmnpqrstvwxyz"),
        _max_run(label, "0123456789"), sum(c in "0123456789abcdef" for c in label) / length,
        label.startswith("xn--"),
    ])))


def extract_features(domain: object, mode: str = "dns", psl_path: Path = PSL_PATH) -> dict[str, float]:
    return label_features(candidate_dga_label(domain, mode, psl_path))


def feature_frame(domains: Iterable[object], mode: str = "dns", psl_path: Path = PSL_PATH) -> pd.DataFrame:
    return pd.DataFrame([extract_features(d, mode, psl_path) for d in domains],
                        columns=FEATURE_NAMES, dtype=float)
