"""python -m scripts.download_data --network --legacy"""
import argparse
from datetime import datetime, timezone
from backend.acs.db import transaction
from backend.acs.ingestion import CONFIG, ODHClient, utc

def main():
    p = argparse.ArgumentParser(description="Download public OCPI observations from ODH, resumable")
    p.add_argument("--start", default=CONFIG["current_start"])
    p.add_argument("--end", default=datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat())
    p.add_argument("--legacy", action="store_true", help="Also download legacy history for selected and context sites")
    p.add_argument("--network", action="store_true", help="Include Bolzano network for cleaning/ranking/backtests")
    p.add_argument("--latest", action="store_true", help="Refresh live observations instead of history")
    args = p.parse_args()
    with transaction() as db:
        client = ODHClient(db)
        try:
            client.metadata("Neogy-AMPECO", args.network)
            client.observations("Neogy-AMPECO", utc(args.start), utc(args.end), args.network, args.latest)
            if args.legacy:
                client.metadata("Neogy")
                client.observations("Neogy", utc(CONFIG["legacy_start"]), utc(CONFIG["legacy_end"]))
        finally:
            client.client.close()

if __name__ == "__main__":
    main()
