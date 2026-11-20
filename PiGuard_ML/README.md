# PiGuard ML: alert-only DNS observer and client dashboard

The combined PiGuard dashboard source now includes a Pi-hole/ML overview, review
queue, Tor gateway controls, account roles, and a guided network setup page. It
uses the root-owned fixed-command broker in `../PiGuard/`, with no general sudo
access for the web process. Local and Pi-side route tests pass, but the upgraded
dashboard is staged rather than active on the live Pi. Deployment steps and
remaining hardware checks are in `../PiGuard/DEPLOY_DASHBOARD.md`.

PiGuard scores **registrable domain labels** for DGA-like patterns, then stores alerts for human review. It never writes Pi-hole policy or delays a DNS response. A high score is not proof of malware infection. Subdomain tunnelling, arbitrary malware URLs, payload inspection, and automatic blocking are outside this implementation.

See `IMPLEMENTATION_STATUS.md` for measured results and deployment limitations. The previous notebook is preserved as `PiGuard_DGA_Training_Colab_legacy.ipynb`; its feature-v2 artifacts are incompatible with this feature-v3 runtime.

## Environment and tests

Use Python **3.13.5**, matching the observed Pi. Create an isolated environment, then install the complete package lock:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pytest test_features.py tests -q
```

The test suite includes malformed inputs, PSL wildcard/exception handling, leakage prevention, score thresholds, artifact tampering, reference parity, transactional recovery, source reset, concurrent observers, retention, CSRF, stored text escaping, filters, and one-time final evaluation on disposable synthetic data. The dashboard browser test uses synthetic traffic only.

For Colab, run `python scripts/package_source.py`, upload `output/PiGuard_ML_Source.zip`, and use the updated notebook. It installs an isolated Python 3.13.5 runtime. The source package contains no household logs or local credentials.

## Train and freeze candidates

Download the pinned dataset URL documented in `data/README.md`, saving it as `data/domains_features.gz`. The notebook additionally verifies the known hash. Training always records the bytes actually used.

```bash
.venv/bin/python -m piguard.training train \
  --dataset data/domains_features.gz --output runs/new-run
```

The immutable run directory contains:

- Data audit and 70/15/15 split files with no effective-label overlap.
- Exact training recipe and source hash.
- Validation results for logistic regression, compact forest, and the original forest.
- Candidate bundles containing model, preprocessing code, offline PSL, environment lock, threshold, and reference vectors.

Thresholds maximize validation recall under a measured FPR of 1%; zero-recall operating points are rejected. Candidate choice uses validation recall, precision, then measured Pi memory among candidates passing the locked resource policy. The baseline policy was saved before its held-out test was opened. Its one-time final evaluation is complete; do not run it again.

```bash
.venv/bin/python -m piguard.benchmark --run runs/new-run \
  --batch-size 500 --batches 20 --output runs/new-run/benchmark-pi-batch500.json
.venv/bin/python -m piguard.training evaluate \
  --run runs/new-run --candidate SELECTED_NAME \
  --benchmark runs/new-run/benchmark-pi-batch500.json --output releases/new-final
```

Run the benchmark **on the Pi**, with `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`. Before evaluating a new run, save `evaluation_policy.json` in its run directory with the selection order, `status: locked_before_test_evaluation`, benchmark filename, and resource requirements. The baseline policy requires ARM64, reference parity, scorer peak RSS ≤256 MiB, and p95 ≤2 seconds for a warm uncached batch of 500 names. The batch limit follows the observer's two-second drain budget. The evaluation command refuses an ineligible candidate or a second test-set evaluation. If evaluation crashes after marking the test consumed, investigate and preserve the run; do not delete the marker to retune.

The final release includes confusion counts, precision/recall/F1/FPR, ROC-AUC, average precision, Wilson intervals, plots, error examples, and slices by length and punycode. These do not establish unseen-DGA-family performance because the dataset lacks family labels.

The frozen baseline artifacts are in `releases/final-001` and `output/PiGuard_ML_final-001.zip`. The ZIP's SHA-256 is `57aafa7e699fff8a18f694937a4924d561e27d0ecab41f572ca02575cb58f51e`. `output/PiGuard_ML_Source.zip` contains the updated source and activation script, without logs, state, or credentials.

## Trusted inference

Obtain the manifest digest through the same trusted channel as your training export. Merely reading a digest supplied with an unknown download does not establish trust. `joblib` must never load an untrusted artifact.

```bash
.venv/bin/python piguard_dga_inference.py \
  --release runs/new-run/candidates/compact_random_forest \
  --manifest-sha256 TRUSTED_64_CHARACTER_DIGEST \
  example.com www.example.co.uk
```

Use `--csv domains.csv` for a CSV containing `domain`; use `--mode label` only for dataset-style base labels. DNS mode rejects URLs, IP literals, malformed names, local/special-use names, and unknown suffixes. Output is JSON lines with a DGA score, threshold, decision, model ID, and retained feature values, or an explicit skip reason. `dga_probability` remains a deprecated compatibility alias; it is not an infection probability. Existing `--model`/`--contract` arguments must identify files within the selected release.

The manifest is checked before deserialization. Runtime Python and dependency versions, feature source, PSL hash, class mapping, and reference predictions must agree. Model releases are immutable; replacing a PSL or feature file requires retraining.

## Observer behavior

Configuration is JSON:

```json
{
  "source_db": "/etc/pihole/pihole-FTL.db",
  "state_db": "/var/lib/piguard/state.db",
  "release": "/opt/piguard/releases/RELEASE/artifacts",
  "manifest_sha256": "TRUSTED_64_CHARACTER_DIGEST",
  "dns_server": "127.0.0.1"
}
```

Relative paths resolve against the configuration file's directory. Run:

```bash
.venv/bin/python -m piguard.observer --config config.json
.venv/bin/python -m piguard.dashboard --config config.json
```

The collector polls every 15 seconds, materializes up to 500 source records in a short read-only transaction, closes the source, and scores locally. A model-aware cache holds at most 10,000 labels. Pi-hole commonly persists records every 60 seconds; the installed interval must be checked before claiming the three-minute alert target.

First startup tails from the current source watermark. Results, counts, and checkpoint advance atomically. A changed checkpoint from another observer aborts a stale batch. Replacement, truncation, or missing checkpoint anchors create a visible gap and resume from the current watermark. This explicitly sacrifices uncertain historical coverage rather than silently duplicating it. SQLite errors back off without modifying DNS.

For deliberate historical replay, use `--replay` with a **new, separate state database**. `--once` processes a bounded cycle, useful for controlled tests. Do not replay into the live review store.

State retains alert domain/model/day groups for 14 days and domain-free daily counters for 90 days. Client identifiers and benign raw query histories are not copied. Review history is retained with its alert. Historical scores, thresholds, feature values, and feature versions remain tied to the original decision. Daily grouping can resurface a previously reviewed domain on another day; there is no hidden allowlist or automatic retraining.

An empty queue does not establish health. `/healthz` returns 503 for missing/stale collection, missing model readiness, or observer errors. It reports the separate DNS probe state. A quiet but readable source is distinguished from a failed read; observing queries on a day does not prove uninterrupted coverage.

## Pi installation

The evaluated `final-001` compact forest was activated on the observed Pi on 2026-10-25. It passed Pi-side integrity and reference checks; the live health endpoint reports `model_stage=evaluated` with no backlog or error. The release is staged in `~/PiGuard_ML_20261025/releases/final-001` for recovery or a fresh install. Installation or upgrade requires the operator's sudo password in their own terminal. The activation script uses manifest SHA-256 `fc4f50f35b2f70d976cb10036e0eb6dff2253f5ef54b5c21d685683b33cf8b21`:

```bash
cd ~/PiGuard_ML_20261025
bash scripts/activate_final.sh
```

The generic installer accepts `sudo bash scripts/install_pi.sh RELEASE_DIRECTORY TRUSTED_MANIFEST_SHA256`; a provisional candidate requires `--experimental`. The final release remains alert-only.

The installer creates a dedicated `piguard` account, a versioned root-owned release, an isolated environment, and `/var/lib/piguard` state. It grants named read-only ACLs solely on the Pi-hole query DB and existing WAL/SHM files; it does not add the account to the `pihole` group or grant access to administrative credentials. A small path/timer helper reapplies these ACLs after file recreation. The installer checks the actual `queries` schema, feature contract, and reference predictions before activation.

Observer and dashboard run as separate systemd services. Dashboard listens only on `127.0.0.1:8080`; reach it from the Mac through an SSH tunnel:

```bash
ssh -N -L 8080:127.0.0.1:8080 krat0s@KREO.local
```

Open http://127.0.0.1:8080. If mDNS is unavailable, use the known IP with `-o HostKeyAlias=KREO.local -o StrictHostKeyChecking=yes`; do not disable host-key checking. SSH supplies access control. Reviews require CSRF tokens, text is escaped, and CSV output protects against formula injection. The local session expires when the dashboard process restarts.

Readiness failures revert the current release pointer when a previous version exists; first-install failures stop the new services. Recovery commands:

```bash
sudo bash /opt/piguard/current/scripts/rollback_pi.sh
sudo bash /opt/piguard/current/scripts/stop_pi.sh
journalctl -u piguard-observer -u piguard-dashboard --since '30 minutes ago'
```

Stopping PiGuard disables its observer/dashboard and read-access refresh, preserving releases and alert data. Pi-hole itself and client DNS settings remain unchanged. Systemd/journald handles service logs; application messages omit raw query names.

## Local dashboard preview

```bash
.venv/bin/python scripts/make_preview.py
.venv/bin/python -m piguard.dashboard --config state/preview/config.json --port 8087
```

The fixture generator uses the included baseline run. It creates explicitly synthetic records and never resolves the generated names. Its existing state is preserved on reruns. The browser review screenshot is local QA, not live Pi-hole evidence.

## Acceptance and seven-day trial

The final model met the locked Pi-side selection limits: scorer peak RSS ≤256 MiB and warm uncached batch500 p95 ≤2 seconds. Deployment acceptance still needs a controlled DNS comparison with ML disabled/enabled using the same workload, once one-client DNS is reliable. Measure combined dashboard/scorer peak RSS against the 320 MiB target, alert appearance against three minutes, DNS p95 overhead against max(2 ms, 10%), and look for ML-induced timeouts, OOM, or sustained swap. Per-service systemd hard caps do not establish these results.

Keep the model and threshold frozen during seven days. Review every alert, record collection gaps, and distinguish benign, unresolved, and investigation-required cases. An initial usability target is at most five newly surfaced benign domain/model/day alerts per observed day on average. Do not call unreviewed household traffic benign.

```bash
.venv/bin/python -m piguard.report --state /var/lib/piguard/state.db \
  --days 7 --output observation-7days.json
```

The report uses complete UTC days and explicitly reports evidence limits. If alert burden is excessive, use a separate calibration period for the next version; the frozen `final-001` threshold should not be silently changed.

## Current Mac DNS recovery

The 2026-10-25 attempt to restore Mac Wi-Fi DNS to Pi-hole was rolled back after the user reported ChatGPT repeatedly reconnecting. Automatic DNS restored connectivity, confirmed by the user. Keep the Mac on automatic DNS until client integration is investigated and a retry is explicitly chosen. Successful explicit DNS queries and HTTPS probes did not establish reliable ordinary application connectivity. The ML software did not cause this incident: its services had not been installed or started on the Pi.

## References

- Pi-hole query DB: https://docs.pi-hole.net/database/query-database/
- Pi-hole configuration: https://docs.pi-hole.net/ftldns/configfile/
- Model persistence: https://scikit-learn.org/stable/model_persistence.html
- Public Suffix List: https://publicsuffix.org/list/
