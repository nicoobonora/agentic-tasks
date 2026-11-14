"""Explicit local import; never callable by model with arbitrary file paths."""
import argparse,json
from pathlib import Path
from backend.acs.db import transaction
from backend.acs.examples.charging.operations import OperationalRecord,import_record

def main():
    p=argparse.ArgumentParser();p.add_argument('path');a=p.parse_args()
    records=[OperationalRecord.model_validate(r) for r in json.loads(Path(a.path).read_text())]
    with transaction() as db:
        for r in records:import_record(db,r)
if __name__=='__main__':main()
