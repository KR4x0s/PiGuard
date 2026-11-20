"""Score trusted releases; legacy CLI domain/CSV entry points are retained."""
import argparse
import csv
import json
from pathlib import Path
from piguard.model import Scorer


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("domains", nargs="*")
    p.add_argument("--csv", type=Path)
    p.add_argument("--release", type=Path, default=Path("artifacts"))
    p.add_argument("--manifest-sha256", required=True, help="Digest from your trusted training export")
    p.add_argument("--mode", choices=["dns", "label"], default="dns")
    p.add_argument("--model", type=Path, help="Compatibility: must be the model within --release")
    p.add_argument("--contract", type=Path, help="Compatibility: must be the contract within --release")
    args = p.parse_args()
    for explicit, name in [(args.model, "piguard_dga_model.joblib"), (args.contract, "feature_contract.json")]:
        if explicit and explicit.resolve() != (args.release / name).resolve():
            p.error("Model and contract must belong to the same --release")
    domains = list(args.domains)
    if args.csv:
        with args.csv.open(newline="") as handle:
            reader = csv.DictReader(handle)
            if "domain" not in (reader.fieldnames or []):
                p.error("CSV requires a domain column")
            domains.extend(row["domain"] for row in reader)
    if not domains:
        p.error("Supply domains or --csv")
    scorer = Scorer(args.release, args.manifest_sha256)
    for start in range(0, len(domains), 500):
        for result in scorer.score(domains[start:start + 500], args.mode):
            print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
