"""Validate Paolo's/analytical module output before making it visible to clients."""
import argparse
from pathlib import Path
from backend.acs.examples.charging.models import AnalysisBundle
from backend.acs.db import transaction, put, get
from backend.acs.analysis_contract import check_bundle

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    bundle = AnalysisBundle.model_validate_json(args.file.read_text())
    with transaction() as db:
        check_bundle(db, bundle)
        previous = get(db, "analysis", bundle.id)
        if previous is not None and previous != bundle.model_dump(mode="json"):
            raise ValueError("An analysis id is immutable; publish a new id")
        put(db, "analysis", bundle.id, bundle.model_dump(mode="json"))
    print(f"Imported {bundle.id}")

if __name__ == "__main__":
    main()
