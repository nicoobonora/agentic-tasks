"""Portable offline handoff including SQLite and source evidence. No network required."""
import argparse
import sqlite3
import tarfile
import tempfile
from pathlib import Path
from backend.acs.db import transaction, ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='data/exports/acs-snapshot.tar.gz')
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        backup_path = Path(temp)/'acs.sqlite'
        with transaction() as db:
            backup = sqlite3.connect(backup_path)
            db.backup(backup)
            pages = db.execute('SELECT id,path FROM source_pages').fetchall()
            for row in pages:
                backup.execute('UPDATE source_pages SET path=? WHERE id=?', ('data/raw/'+Path(row['path']).name,row['id']))
            backup.commit()
            backup.close()
        with tarfile.open(output,'w:gz') as archive:
            archive.add(backup_path, arcname='data/acs.sqlite')
            for path in sorted({ROOT / row['path'] for row in pages}):
                archive.add(path, arcname='data/raw/'+path.name)
    print(f'Offline snapshot: {output}')

if __name__ == '__main__':
    main()
