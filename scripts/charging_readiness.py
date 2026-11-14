"""Read-only, reproducible acquisition versus reconstruction diagnostics."""
import argparse
import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from backend.acs.ingestion import utc
from backend.acs.examples.charging.tools import Period, raw_period, snapshot
from backend.acs.examples.charging.forecast import reconstruct, comparable_days

def report(db, cutoff, days=56):
    end=utc(cutoff)
    results=[]
    for site in db.execute('SELECT * FROM sites ORDER BY source,id').fetchall():
        args=Period(site_ids=[site['id']],start=end-timedelta(days=days),end=end)
        raw=raw_period(db,args,site['id'])
        eligible=[]
        for plug in db.execute('SELECT id,payload FROM plugs WHERE site_id=?',(site['id'],)):
            connectors=json.loads(plug['payload']).get('connectors',[])
            if connectors and all(str(c.get('power_type','')).startswith('AC') and 0<(c.get('max_electric_power') or 0)<=22000 for c in connectors): eligible.append(plug['id'])
        selected={p:raw[p] for p in eligible}
        gaps=[]
        for group in selected.values():
            times=sorted({utc(r['observed_at']) for r in group})
            gaps.extend((b-a).total_seconds()/60 for a,b in zip(times,times[1:]))
        sensitivity=[]
        for gap in (60,120,240,480):
            hours,_,_=reconstruct(selected,args.start,args.end,gap)
            sensitivity.append(dict(gap_minutes=gap,usable_hours=sum(h.demand_p1 is not None for h in hours),
                recent_usable_hours=sum(h.demand_p1 is not None for h in hours[-24:]),
                comparable_calendar_supported=comparable_days(hours,end,168),
                usable_fraction=sum(h.demand_p1 is not None for h in hours)/len(hours),
                positive_capacity_exposure_hours=sum(h.exposure_hours for h in hours),
                insufficient_exposure_hours=sum(h.exposure_hours<1/6 for h in hours),
                insufficient_nonfull_exposure_hours=sum(h.exposure_hours>=1/6 and h.exposure_hours-h.full_hours<1/6 for h in hours)))
        results.append(dict(site_id=site['id'],source=site['source'],name=site['name'],eligible_ac_points=len(eligible),
            points_without_observations=[p for p,g in selected.items() if not g],observations=sum(map(len,selected.values())),
            cadence_median_minutes=sorted(gaps)[len(gaps)//2] if gaps else None,
            acquisition_gaps_over_120_minutes=sum(g>120 for g in gaps),sensitivity=sensitivity,
            identity_mapping='unresolved; never joined across sources',historical_capacity='unverified'))
    return dict(cutoff=end.isoformat(),history_days=days,source_fingerprint=snapshot(db),sites=results,
        conclusion='Readiness diagnostics only. No threshold changed, no inference executed, no forecast analytically validated.')

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',default='data/acs.sqlite');p.add_argument('--cutoff',required=True);p.add_argument('--output',required=True)
    a=p.parse_args()
    db=sqlite3.connect(f'file:{Path(a.db).resolve()}?mode=ro',uri=True);db.row_factory=sqlite3.Row
    db.execute('BEGIN')
    try: result=report(db,a.cutoff)
    finally: db.close()
    Path(a.output).write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__': main()
