"""Verify a trusted release before deserializing its model."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import platform
from collections import OrderedDict
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

import piguard_dga_features as features


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_release(path: Path, expected_digest: str) -> dict:
    path = path.resolve()
    manifest_path = path / "manifest.json"
    if sha256(manifest_path) != expected_digest:
        raise ValueError("Untrusted or changed release manifest")
    manifest = json.loads(manifest_path.read_text())
    required = {"piguard_dga_model.joblib", "feature_contract.json", "test_vectors.json",
                "piguard_dga_features.py", "data/public_suffix_list.dat"}
    if not required.issubset(manifest["files"]):
        raise ValueError("Incomplete release manifest")
    for name, digest in manifest["files"].items():
        file = (path / name).resolve()
        if not file.is_relative_to(path) or sha256(file) != digest:
            raise ValueError("Release file hash mismatch")
    contract = json.loads((path / "feature_contract.json").read_text())
    if contract.get("deployment_mode") != "alert_only":
        raise ValueError("Only alert-only releases are supported")
    if contract["feature_version"] != features.FEATURE_VERSION or contract["feature_names"] != features.FEATURE_NAMES:
        raise ValueError("Feature contract mismatch")
    if contract["extraction_policy"] != features.EXTRACTION_POLICY:
        raise ValueError("Extraction policy mismatch")
    if sha256(Path(features.__file__)) != contract["feature_sha256"]:
        raise ValueError("Running feature source does not match release")
    if sha256(path / "data/public_suffix_list.dat") != contract["psl_sha256"]:
        raise ValueError("Suffix snapshot mismatch")
    if sha256(path / "piguard_dga_model.joblib") != contract["model_sha256"]:
        raise ValueError("Model hash mismatch")
    if contract["python_version"] != platform.python_version():
        raise ValueError("Python version differs from training; recreate the matching environment")
    for package, version in contract["dependencies"].items():
        if importlib.metadata.version(package) != version:
            raise ValueError(f"Dependency mismatch: {package}")
    threshold = contract["decision_threshold"]
    if not isinstance(threshold, (float, int)) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Invalid threshold")
    return contract


class Scorer:
    def __init__(self, release: Path, expected_digest: str, cache_size: int = 10000):
        self.release = release.resolve()
        self.contract = verify_release(self.release, expected_digest)
        self.stage = "evaluated" if (self.release / "metrics.json").exists() else "candidate"
        self.psl = self.release / "data/public_suffix_list.dat"
        self.model = joblib.load(self.release / "piguard_dga_model.joblib")
        if hasattr(self.model, "n_jobs"):
            self.model.n_jobs = 1
        classes = list(self.model.classes_)
        if sorted(classes) != [0, 1] or self.contract["positive_class"] != 1:
            raise ValueError("Invalid class mapping")
        self.positive_index = classes.index(1)
        self.cache_size = cache_size
        self.cache = OrderedDict()
        self.verify_vectors()

    def verify_vectors(self):
        vectors = json.loads((self.release / "test_vectors.json").read_text())
        if not vectors:
            raise ValueError("Missing reference vectors")
        for vector in vectors:
            matrix = features.feature_frame([vector["input"]], vector["mode"], self.psl)
            if not np.allclose(matrix.to_numpy()[0], vector["features"], rtol=0, atol=1e-12):
                raise ValueError("Reference feature mismatch")
            score = float(self.model.predict_proba(matrix)[0, self.positive_index])
            if abs(score - vector["score"]) > 1e-6:
                raise ValueError("Reference prediction mismatch")
            if (score >= self.contract["decision_threshold"]) != vector["suspicious"]:
                raise ValueError("Reference decision mismatch")

    def score(self, values: list[str], mode: str = "dns") -> list[dict]:
        projected = []
        missing = {}
        for value in values:
            try:
                domain, label = features.project_domain(value, mode, self.psl)
                projected.append((domain, label, None))
                if label not in self.cache:
                    missing[label] = features.label_features(label)
            except features.InputError as exc:
                projected.append((None, None, str(exc)))
        scores = {}
        if missing:
            matrix = pd.DataFrame(missing.values(), columns=features.FEATURE_NAMES, dtype=float)
            predictions = self.model.predict_proba(matrix)[:, self.positive_index]
            if not np.isfinite(predictions).all():
                raise ValueError("Non-finite model score")
            scores = dict(zip(missing, map(float, predictions)))
        results = []
        threshold = self.contract["decision_threshold"]
        for domain, label, reason in projected:
            if reason:
                results.append({"status": "skipped", "reason": reason})
                continue
            score = scores[label] if label in scores else self.cache[label]
            results.append({"status": "scored", "domain": domain, "label": label,
                            "feature_version": features.FEATURE_VERSION,
                            "features": features.label_features(label),
                            "model_id": self.contract["model_id"], "dga_score": score,
                            "dga_probability": score, "threshold": threshold,
                            "suspicious": score >= threshold})
        # Update only after every result is assembled: eviction cannot break the current batch.
        for _, label, reason in projected:
            if not reason:
                self.cache[label] = scores[label] if label in scores else self.cache[label]
                self.cache.move_to_end(label)
        while len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)
        return results
