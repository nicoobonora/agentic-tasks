import json
from backend.acs.db import transaction, ROOT, documents
from backend.acs.normalize import rebuild

def main():
    with transaction() as db:
        print(json.dumps(rebuild(db), indent=2))
        out = ROOT / "data/exports"
        out.mkdir(parents=True, exist_ok=True)
        for table in ("sites", "plugs", "observations", "transitions", "heartbeats", "episodes"):
            with (out / f"{table}.jsonl").open("w") as f:
                for row in db.execute(f"SELECT * FROM {table}"):
                    f.write(json.dumps(dict(row)) + "\n")
        (out / "quality.json").write_text(json.dumps(documents(db, "quality"), indent=2))
        (out / "manifest.json").write_text(json.dumps([dict(r) for r in db.execute("SELECT * FROM source_pages")], indent=2))

if __name__ == "__main__":
    main()
