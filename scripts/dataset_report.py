"""Write a reproducible inventory, without asserting the plan's historical counts."""
import json
from backend.acs.db import transaction, ROOT, documents
from backend.acs.ingestion import now, CONFIG

def main():
    with transaction() as db:
        counts = {t: db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('sites','plugs','observations','source_pages','transitions','heartbeats','episodes')}
        sources = [dict(r) for r in db.execute('''SELECT p.source,count(DISTINCT p.id) plugs,count(o.id) observations,
            min(o.observed_at) first_observation,max(o.observed_at) last_observation
            FROM plugs p LEFT JOIN observations o ON p.id=o.plug_id GROUP BY p.source''')]
        report = {'generated_at': now(), 'counts': counts, 'sources': sources, 'selection': CONFIG,
            'limitations': ['Counts reflect this download, not the figures quoted in the plan.',
            'Historical and current feeds are separate; station-name matching is not a validated merge.',
            'No energy, official sessions or demand forecasts are observed.',
            'Gaps over the configured heartbeat threshold split intervals. DC coupling is flagged for review.',
            'Analysis tables and agent decisions are not computed by the foundation.']}
        (ROOT/'docs/dataset-report.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report['counts'],indent=2))

if __name__ == '__main__':
    main()
