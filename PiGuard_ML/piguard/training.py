"""Reproducible preparation, candidate export, and a separately gated final test."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import shutil
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score,
                             precision_score, recall_score, roc_auc_score)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import piguard_dga_features as features
from piguard.model import sha256

ROOT = Path(__file__).resolve().parents[1]
DATASET_REVISION = "b9c75bc92d16736875f094b05180befb163d756a"
DATASET_URL = f"https://raw.githubusercontent.com/tisage/DGA-dataset/{DATASET_REVISION}/domains_features.gz"


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def binary_label(value):
    text = str(value).strip().lower()
    if text in {"0", "0.0", "benign", "legit", "legitimate", "negative", "good"}:
        return 0
    if text in {"1", "1.0", "dga", "malicious", "positive", "bad"}:
        return 1
    raise ValueError("Unknown dataset class")


def clean_data(raw: pd.DataFrame):
    columns = {c.lower(): c for c in raw.columns}
    domain_col = next((columns[c] for c in ["domain", "hostname", "fqdn"] if c in columns), None)
    label_col = next((columns[c] for c in ["class", "label", "target"] if c in columns), None)
    if not domain_col or not label_col:
        raise ValueError("Dataset needs domain and class/label columns")
    rows, invalid = [], 0
    for domain, target in zip(raw[domain_col], raw[label_col]):
        label = binary_label(target)
        try:
            normalized = features.normalize_domain(domain)
            mode = "dns" if "." in normalized else "label"
            effective = features.candidate_dga_label(normalized, mode)
        except features.InputError:
            invalid += 1
            continue
        rows.append({"domain": normalized, "effective_label": effective, "label": label})
    data = pd.DataFrame(rows)
    if data.empty:
        raise ValueError("No valid data")
    conflicts = data.groupby("effective_label").label.nunique()
    conflict_keys = set(conflicts[conflicts > 1].index)
    unconflicted = data[~data.effective_label.isin(conflict_keys)]
    clean = unconflicted.drop_duplicates("effective_label").sort_values("effective_label").reset_index(drop=True)
    return clean, {"raw_rows": len(raw), "invalid_rows": invalid,
                   "conflicting_groups": len(conflict_keys), "conflicting_rows": len(data) - len(unconflicted),
                   "duplicates_removed": len(unconflicted) - len(clean), "clean_rows": len(clean),
                   "class_counts": {str(k): int(v) for k, v in clean.label.value_counts().items()}}


def split_data(data, seed=42):
    train, rest = train_test_split(data, test_size=.30, stratify=data.label, random_state=seed)
    val, test = train_test_split(rest, test_size=.5, stratify=rest.label, random_state=seed)
    groups = [set(x.effective_label) for x in (train, val, test)]
    assert not (groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])
    return {"train": train.copy(), "validation": val.copy(), "test": test.copy()}


def wilson(successes, total):
    if not total:
        return [None, None]
    z = 1.959963984540054
    p = successes / total
    center = (p + z*z/(2*total)) / (1 + z*z/total)
    radius = z * ((p*(1-p)/total + z*z/(4*total*total))**.5) / (1 + z*z/total)
    return [max(0., center-radius), min(1., center+radius)]


def metrics(y, scores, threshold):
    pred = np.asarray(scores) >= threshold
    tn, fp, fn, tp = map(int, confusion_matrix(y, pred, labels=[0, 1]).ravel())
    both = len(set(y)) == 2
    return {"threshold": float(threshold), "n": len(y), "confusion_matrix": [[tn, fp], [fn, tp]],
            "precision": float(precision_score(y, pred, zero_division=0)),
            "recall": float(recall_score(y, pred, zero_division=0)),
            "f1": float(f1_score(y, pred, zero_division=0)),
            "false_positive_rate": fp / (fp+tn) if fp+tn else None,
            "recall_95ci": wilson(tp, tp+fn), "false_positive_rate_95ci": wilson(fp, fp+tn),
            "roc_auc": float(roc_auc_score(y, scores)) if both else None,
            "average_precision": float(average_precision_score(y, scores)) if both else None}


def select_threshold(y, scores, max_fpr=.01):
    """Linear sweep after sorting; include tied scores atomically and a no-alert state."""
    y, scores = np.asarray(y), np.asarray(scores)
    order = np.argsort(-scores, kind="stable")
    sorted_y, sorted_scores = y[order], scores[order]
    tp = np.cumsum(sorted_y == 1)
    fp = np.cumsum(sorted_y == 0)
    ends = np.r_[sorted_scores[:-1] != sorted_scores[1:], True]
    valid = np.flatnonzero(ends & (fp / max(1, np.sum(y == 0)) <= max_fpr) & (tp > 0))
    if not len(valid):
        return None  # A no-alert operating point is not a deployable detector.
    best = max(valid, key=lambda i: (int(tp[i]), float(tp[i]/(tp[i]+fp[i])), float(sorted_scores[i])))
    return float(sorted_scores[best])


def candidates():
    return {
        "logistic_regression": make_pipeline(StandardScaler(), LogisticRegression(
            class_weight="balanced", solver="liblinear", max_iter=2000, random_state=42)),
        "compact_random_forest": RandomForestClassifier(n_estimators=100, max_depth=12,
            min_samples_leaf=5, class_weight="balanced_subsample", n_jobs=-1, random_state=42),
        "random_forest": RandomForestClassifier(n_estimators=250, max_depth=20,
            min_samples_leaf=2, class_weight="balanced_subsample", n_jobs=-1, random_state=42),
    }


def seal_release(path):
    files = {str(p.relative_to(path)): sha256(p) for p in sorted(path.rglob("*"))
             if p.is_file() and p.name not in {"manifest.json", "MANIFEST.sha256"}}
    write_json(path / "manifest.json", {"format": 1, "files": files})
    digest = sha256(path / "manifest.json")
    (path / "MANIFEST.sha256").write_text(digest + "\n")
    return digest


def export_candidate(path, model, name, threshold, validation, data_info, val, elapsed):
    path.mkdir(parents=True)
    (path / "data").mkdir()
    if hasattr(model, "n_jobs"):
        model.n_jobs = 1
    joblib.dump(model, path / "piguard_dga_model.joblib", compress=3)
    shutil.copy2(features.__file__, path / "piguard_dga_features.py")
    shutil.copy2(features.PSL_PATH, path / "data/public_suffix_list.dat")
    deps = {dist.metadata["Name"].lower(): dist.version for dist in importlib.metadata.distributions()
            if dist.metadata["Name"].lower() not in {"pip", "setuptools", "wheel"}}
    contract = {"model_id": f"{name}-{sha256(path / 'piguard_dga_model.joblib')[:12]}",
                "model_name": name, "positive_class": 1, "positive_class_name": "dga_like",
                "decision_threshold": threshold, "feature_version": features.FEATURE_VERSION,
                "feature_names": features.FEATURE_NAMES, "extraction_policy": features.EXTRACTION_POLICY,
                "feature_sha256": sha256(Path(features.__file__)), "psl_sha256": sha256(features.PSL_PATH),
                "model_sha256": sha256(path / "piguard_dga_model.joblib"),
                "python_version": platform.python_version(), "dependencies": deps,
                "seed": 42, "deployment_mode": "alert_only", "dataset": data_info,
                "limitations": ["No family-held-out evidence", "Not a probability of infection",
                                "Registrable label only; no subdomain/tunnelling analysis",
                                "Local traffic is unlabeled until reviewed"]}
    write_json(path / "feature_contract.json", contract)
    write_json(path / "validation.json", {**validation, "training_seconds": elapsed,
                                           "artifact_bytes": (path / "piguard_dga_model.joblib").stat().st_size})
    (path / "requirements-pi.txt").write_text("".join(f"{p}=={v}\n" for p, v in sorted(deps.items())))
    samples = [(x, "label") for _, group in val.groupby("label")
               for x in group.sample(n=min(10, len(group)), random_state=42).effective_label]
    samples += [("WWW.Example.CO.UK.", "dns"), ("bücher.de", "dns"), ("a.www.ck", "dns"),
                ("random-subdomain.example.com", "dns")]
    vectors = []
    for value, mode in samples:
        matrix = features.feature_frame([value], mode)
        score = float(model.predict_proba(matrix)[0, list(model.classes_).index(1)])
        vectors.append({"input": value, "mode": mode, "features": matrix.iloc[0].tolist(),
                        "score": score, "suspicious": score >= threshold})
    write_json(path / "test_vectors.json", vectors)
    return seal_release(path)


def train(dataset, output):
    if output.exists():
        raise ValueError("Choose a new run directory; existing runs are immutable")
    output.mkdir(parents=True)
    shutil.copy2(__file__, output / "training_recipe.py")
    (output / "training_recipe.sha256").write_text(sha256(Path(__file__)) + "\n")
    raw = pd.read_csv(dataset, compression="infer")
    clean, audit = clean_data(raw)
    splits = split_data(clean)
    data_info = {"source_url": DATASET_URL, "source_revision": DATASET_REVISION,
                 "sha256": sha256(dataset), "audit": audit,
                 "input_file": dataset.name}
    write_json(output / "data_audit.json", data_info)
    for name, data in splits.items():
        data.to_csv(output / f"{name}.csv.gz", index=False, compression="gzip")
    write_json(output / "split_manifest.json", {name: {"rows": len(data),
               "sha256": sha256(output / f"{name}.csv.gz")} for name, data in splits.items()})
    x = features.feature_frame(splits["train"].effective_label, "label")
    xv = features.feature_frame(splits["validation"].effective_label, "label")
    summary = {}
    for name, model in candidates().items():
        start = time.perf_counter()
        model.fit(x, splits["train"].label)
        elapsed = time.perf_counter() - start
        scores = model.predict_proba(xv)[:, list(model.classes_).index(1)]
        threshold = select_threshold(splits["validation"].label, scores)
        if threshold is None:
            summary[name] = {"eligible": False, "reason": "no_nonzero_recall_under_fpr_limit"}
            continue
        result = metrics(splits["validation"].label, scores, threshold)
        digest = export_candidate(output / "candidates" / name, model, name, threshold,
                                  result, data_info, splits["validation"], elapsed)
        summary[name] = {"eligible": True, "validation": result, "manifest_sha256": digest}
        print(name, json.dumps(summary[name]), flush=True)
    write_json(output / "candidates.json", summary)
    print("Test set remains untouched. Benchmark candidates before final evaluation.", flush=True)


def evaluate(run, candidate, output, benchmark):
    from piguard.model import Scorer
    if (run / "FINAL_EVALUATED.json").exists():
        raise ValueError("This run has already consumed its test set")
    if output.exists():
        raise ValueError("Choose a new release directory")
    policy_path = run / "evaluation_policy.json"
    if not policy_path.exists():
        raise ValueError("Lock an evaluation policy before opening the final test set")
    policy = json.loads(policy_path.read_text())
    if policy.get("status") != "locked_before_test_evaluation" or benchmark.name != policy.get("benchmark_evidence"):
        raise ValueError("Benchmark does not match the locked evaluation policy")
    limits = policy["requirements"]
    choices = json.loads((run / "candidates.json").read_text())
    eligible = [name for name, record in choices.items() if record["eligible"]]
    if candidate not in eligible:
        raise ValueError("Candidate is not validation-eligible")
    bench = json.loads(benchmark.read_text())
    passing = []
    for name in eligible:
        evidence = bench.get(name, {})
        if (evidence.get("platform") == limits["platform"]
                and evidence.get("reference_vectors") == limits["reference_vectors"]
                and evidence.get("manifest_sha256") == choices[name]["manifest_sha256"]
                and evidence.get("batch_size") == limits["batch_size"]
                and evidence.get("peak_rss_mib", float("inf")) <= limits["max_scorer_peak_rss_mib"]
                and evidence.get("batch_p95_ms", float("inf")) <= limits["max_batch_p95_ms"]):
            passing.append(name)
    if not passing:
        raise ValueError("No candidate meets the locked Pi resource policy; final test remains untouched")
    selected = max(passing, key=lambda name: (choices[name]["validation"]["recall"],
                   choices[name]["validation"]["precision"], -bench[name]["peak_rss_mib"]))
    if candidate != selected:
        raise ValueError(f"Predeclared selection policy chose {selected}")
    release = run / "candidates" / candidate
    scorer = Scorer(release, choices[candidate]["manifest_sha256"])
    manifest = json.loads((run / "split_manifest.json").read_text())
    for name, metadata in manifest.items():
        if sha256(run / f"{name}.csv.gz") != metadata["sha256"]:
            raise ValueError("Split changed after training")
    # Record consumption before looking at scores. A crash must not silently unlock retuning.
    write_json(run / "FINAL_EVALUATED.json", {"candidate": candidate, "started_at": time.time(),
                "policy_sha256": sha256(policy_path), "benchmark_sha256": sha256(benchmark),
                "evaluation_source_sha256": sha256(Path(__file__))})
    test = pd.read_csv(run / "test.csv.gz")
    scores = np.array([r["dga_score"] for r in scorer.score(test.effective_label.tolist(), "label")])
    result = metrics(test.label, scores, scorer.contract["decision_threshold"])
    test["score"] = scores
    test["prediction"] = scores >= scorer.contract["decision_threshold"]
    test["length_bucket"] = pd.cut(test.effective_label.str.len(), [0, 8, 16, 32, 63], include_lowest=True).astype(str)
    test["punycode"] = test.effective_label.str.startswith("xn--")
    slices = {}
    for column in ["length_bucket", "punycode"]:
        slices[column] = {str(key): metrics(frame.label, frame.score, scorer.contract["decision_threshold"])
                          for key, frame in test.groupby(column)}
    shutil.copytree(release, output)
    write_json(output / "metrics.json", {"test": result, "slices": slices, "benchmark": bench[candidate]})
    test[test.prediction != test.label].to_csv(output / "test_errors.csv", index=False)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.metrics import ConfusionMatrixDisplay, RocCurveDisplay, PrecisionRecallDisplay
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    ConfusionMatrixDisplay.from_predictions(test.label, test.prediction, ax=axes[0])
    RocCurveDisplay.from_predictions(test.label, test.score, ax=axes[1])
    PrecisionRecallDisplay.from_predictions(test.label, test.score, ax=axes[2])
    fig.tight_layout()
    fig.savefig(output / "evaluation.png", dpi=160)
    shutil.copy2(run / "split_manifest.json", output / "split_manifest.json")
    shutil.copy2(run / "data_audit.json", output / "data_audit.json")
    shutil.copy2(run / "training_recipe.py", output / "training_recipe.py")
    shutil.copy2(run / "training_recipe.sha256", output / "training_recipe.sha256")
    shutil.copy2(policy_path, output / "evaluation_policy.json")
    shutil.copy2(benchmark, output / "benchmark-pi-batch500.json")
    shutil.copy2(Path(__file__), output / "evaluation_recipe.py")
    digest = seal_release(output)
    print(json.dumps({"release": str(output), "manifest_sha256": digest, "test": result}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("train")
    t.add_argument("--dataset", type=Path, default=ROOT / "data/domains_features.gz")
    t.add_argument("--output", type=Path, required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--run", type=Path, required=True)
    e.add_argument("--candidate", required=True)
    e.add_argument("--output", type=Path, required=True)
    e.add_argument("--benchmark", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "train":
        train(args.dataset, args.output)
    else:
        evaluate(args.run, args.candidate, args.output, args.benchmark)


if __name__ == "__main__":
    main()
