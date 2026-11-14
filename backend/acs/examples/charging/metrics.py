"""Observed occupancy and historical maintenance comparisons, never fault diagnosis."""
from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo
from pydantic import Field, AwareDatetime, model_validator
from .tools import Period, raw_period, outcome
from .forecast import reconstruct

ROME=ZoneInfo('Europe/Rome')

class HourlyPeriod(Period):
    start: AwareDatetime = Field(description='UTC whole-hour boundary, e.g. 2026-10-01T00:00:00Z')
    end: AwareDatetime = Field(description='UTC whole-hour boundary; round the selected observation cutoff down explicitly')

    @model_validator(mode='after')
    def aligned(self):
        if any((d.minute,d.second,d.microsecond)!=(0,0,0) for d in (self.start,self.end)):
            raise ValueError('Usage/windows require whole UTC hours; explicitly choose start/end at HH:00:00Z')
        return self

class Windows(HourlyPeriod):
    record_ids: list[str] = Field(default_factory=list,max_length=30)
    duration_hours: int = Field(default=2,ge=1,le=24)
    permitted_hours: list[int] = Field(default_factory=lambda:list(range(24)),min_length=1,max_length=24)
    minimum_coverage: float = Field(default=.9,gt=0,le=1)

    @model_validator(mode='after')
    def hours_valid(self):
        if any(not 0<=h<=23 for h in self.permitted_hours):
            raise ValueError('Hours must be 0..23 in Europe/Rome')
        return self

def observed(db,args):
    results=[]
    for ident in args.site_ids:
        raw=raw_period(db,args,ident)
        hours,durations,evidence=reconstruct(raw,args.start,args.end,args.gap_minutes)
        exposure=sum(h.exposure_hours for h in hours)
        occupied=sum((h.mean_occupied or 0)*h.exposure_hours for h in hours)
        operational=sum((h.mean_operational or 0)*h.exposure_hours for h in hours)
        profiles=defaultdict(lambda:dict(dates=set(),exposure_hours=0.,occupied_point_hours=0.,observed_starts=0))
        for h in hours:
            if not h.exposure_hours:continue
            local=h.time.astimezone(ROME);profile=profiles[(local.weekday(),local.hour)]
            profile['dates'].add(str(local.date()));profile['exposure_hours']+=h.exposure_hours
            profile['occupied_point_hours']+=(h.mean_occupied or 0)*h.exposure_hours;profile['observed_starts']+=h.observed_starts
        results.append(dict(site_id=ident,status='available' if exposure else 'unavailable',
            start=args.start.isoformat(),end=args.end.isoformat(),timezone='Europe/Rome',
            coverage=exposure/len(hours) if hours else 0, exposure_hours=exposure,
            observed_starts=sum(h.observed_starts for h in hours),occupied_point_hours=occupied,
            operational_point_hours=operational,occupancy_fraction=occupied/operational if operational else None,
            units={'coverage':'fraction','exposure_hours':'hours','observed_starts':'observed starts',
                   'occupied_point_hours':'point hours','operational_point_hours':'point hours','occupancy_fraction':'fraction'},
            local_profiles=[dict(weekday=k[0],hour=k[1],comparable_dates=len(v['dates']),**{a:b for a,b in v.items() if a!='dates'}) for k,v in sorted(profiles.items())],
            complete_episodes=len(durations),evidence_ids=sorted(evidence),
            hours=[h.model_dump(mode='json') for h in hours]))
    return results

def usage(db,args):
    sites=observed(db,args)
    result=outcome(db,'charging.get_usage_summary',{'sites':sites},'available' if any(s['status']=='available' for s in sites) else 'unavailable')
    result.origin='derived_metric'
    result.limitations += ['Coverage is observable positive operational exposure; zero capacity and unknown states are excluded, never quiet demand.',
        'Observed starts are not official sessions or latent demand. Complete episodes exclude censored durations.']
    return result

def maintenance(db,args):
    sites=observed(db,args)
    rankings=[]
    for site in sites:
        groups=defaultdict(list)
        hours=site['hours']
        for i in range(len(hours)-args.duration_hours+1):
            window=hours[i:i+args.duration_hours]
            from ...ingestion import utc
            local=[utc(h['time']).astimezone(ROME) for h in window]
            if any(t.hour not in args.permitted_hours for t in local): continue
            # Actual elapsed hours; repeated DST hour retains its offset and fold.
            if any(h['exposure_hours']<args.minimum_coverage for h in window): continue
            cost=sum(h['mean_occupied']*h['exposure_hours'] for h in window)
            groups[(local[0].weekday(),local[0].hour)].append((str(local[0].date()),cost,min(h['exposure_hours'] for h in window)))
        candidates=[]
        for (weekday,hour),samples in groups.items():
            # A repeated DST local hour is not a second independent comparable date.
            dates={d for d,_,_ in samples}
            if len(dates)<4: continue
            candidates.append(dict(weekday=weekday,local_start_hour=hour,comparable_dates=len(dates),
                mean_occupied_point_hours=sum(c for _,c,_ in samples)/len(samples),minimum_coverage=min(c for _,_,c in samples)))
        candidates.sort(key=lambda c:(c['mean_occupied_point_hours'],c['weekday'],c['local_start_hour']))
        from ...db import get
        records=[get(db,'charging_operational',ident) for ident in args.record_ids]
        verified=[r for r in records if r and r['site_id']==site['site_id'] and r['classification']=='verified' and r['effective_from']<=str(args.end.date())<=r['effective_until']]
        requirements=[r for r in verified if r['kind']=='maintenance_requirement']
        durations=[r['duration_hours'] for r in requirements if r.get('duration_hours') is not None]
        mismatch=any(d!=args.duration_hours for d in durations)
        due=[r['due_date'] for r in requirements if r.get('due_date')]
        need=('due' if min(due)<=str(args.end.date()) else 'not_due_as_of_cutoff') if due else 'unknown'
        if mismatch:candidates=[]
        rankings.append(dict(site_id=site['site_id'],start=args.start.isoformat(),end=args.end.isoformat(),units={'mean_occupied_point_hours':'point hours','comparable_dates':'dates','minimum_coverage':'fraction'},status='available' if candidates else 'unavailable',
            reason=None if candidates else 'Fewer than four comparable dates with adequate positive-capacity coverage.',
            candidates=candidates[:10],maintenance_need=need,need_as_of=args.end.isoformat(),duration_constraint='mismatch' if mismatch else 'verified' if durations else 'unknown',duration_elapsed_hours=args.duration_hours))
    result=outcome(db,'charging.compare_maintenance_windows',dict(sites=rankings,timezone='Europe/Rome',
        basis='Historical-pattern suggestions only; lower observed occupied point-hours ranks first.'),
        'available' if any(s['status']=='available' for s in rankings) else 'unavailable')
    result.origin='derived_metric'
    result.limitations += ['Maintenance need is unknown unless supplied effective, verified equipment records explicitly give a due date; status observations never diagnose faults.',
        'A future calendar date requires a forecast or explicit conditional assumption; no date is scheduled.']
    return result
