"""Bounded read-only charging queries. No arbitrary SQL, URLs or filesystem inputs."""
import json
from datetime import datetime, timezone, timedelta
from typing import Literal
from pydantic import Field, AwareDatetime, model_validator
from ...capabilities import Contract, ToolOutcome
from ...tools import digest, artifact

class Discover(Contract):
    area: str | None = Field(default=None, max_length=100)
    source: Literal['Neogy', 'Neogy-AMPECO'] = 'Neogy-AMPECO'
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=25, ge=1, le=100)

class Sites(Contract):
    site_ids: list[str] = Field(min_length=1, max_length=10)

class Period(Sites):
    start: AwareDatetime
    end: AwareDatetime
    gap_minutes: int = Field(default=120, ge=1, le=480)

    @model_validator(mode='after')
    def bounded(self):
        self.start=self.start.astimezone(timezone.utc)
        self.end=self.end.astimezone(timezone.utc)
        if not timedelta(0) < self.end-self.start <= timedelta(days=180):
            raise ValueError('Period must be positive and at most 180 days')
        return self

class EvidenceArgs(Contract):
    evidence_id: str = Field(min_length=1, max_length=200)
    path: str | None = Field(default=None,max_length=300,description='Optional dot-separated path within immutable data; list indexes are decimal integers')
    offset: int = Field(default=0,ge=0,le=100000)
    limit: int = Field(default=50,ge=1,le=100)

SCHEMAS = {'charging.discover_sites': Discover, 'charging.get_inventory': Sites,
           'charging.get_data_quality': Period, 'charging.get_evidence': EvidenceArgs}

def normalize(name, arguments):
    from .operations import Records, Expansion
    SCHEMAS.update({"charging.get_operational_inputs": Records, "charging.assess_expansion": Expansion})
    from .metrics import Windows
    from .metrics import HourlyPeriod
    SCHEMAS.update({'charging.get_usage_summary': HourlyPeriod, 'charging.compare_maintenance_windows': Windows})
    if name not in SCHEMAS:
        raise ValueError('Unknown charging tool')
    return SCHEMAS[name].model_validate(arguments)

def snapshot(db):
    # Includes metadata and every source page hash, not mutable latest pointers.
    return digest({t:[list(r) for r in db.execute(sql)] for t,sql in {
        'pages':'SELECT id,sha256,acquired_at,kind,row_count FROM source_pages ORDER BY id',
        'observations':'SELECT count(*),max(id),max(transaction_at),max(observed_at) FROM observations',
        'sites':'SELECT id,name,source,payload FROM sites ORDER BY id',
        'plugs':'SELECT id,site_id,source,payload FROM plugs ORDER BY id',
        'operational':"SELECT id,payload FROM documents WHERE kind='charging_operational' ORDER BY id"}.items()})

def outcome(db, name, data, status='available', limitations=None):
    return ToolOutcome(status=status, summary=f'{name}: {status}. '+json.dumps(data,ensure_ascii=False)[:3000],
        data=data, limitations=limitations or ['Source identity joins are unvalidated; inventory is a current snapshot, not historical capacity.'],
        source_fingerprint=snapshot(db), method=name, queried_at=datetime.now(timezone.utc))

def coordinates(payload):
    # Native ODH station metadata uses scoordinate/pcoordinate or normalized coordinate.
    c = payload.get('coordinates') or payload.get('coordinate') or payload.get('pcoordinate') or payload.get('scoordinate') or {}
    return c if isinstance(c, dict) else {}

def discover(db, args):
    rows = [dict(r) for r in db.execute('SELECT * FROM sites WHERE source=? ORDER BY id', (args.source,))]
    missing=[]
    if args.area and args.area.casefold() in ('bolzano','bozen'):
        selected=[]
        for r in rows:
            c=coordinates(json.loads(r['payload']))
            x,y=c.get('x'),c.get('y')
            if x is None or y is None:
                missing.append(r['id'])
            elif 11.27539 <= x <= 11.432577 and 46.444913 <= y <= 46.530384:
                selected.append(r)
        rows=selected
    elif args.area:
        rows=[r for r in rows if args.area.casefold() in r['name'].casefold() or args.area == r['id']]
    results=[dict(id=r['id'], name=r['name'], source=r['source'], coordinates=coordinates(json.loads(r['payload'])),
                  evidence_id=json.loads(r['payload']).get('evidence_id')) for r in rows]
    ambiguous=bool(args.area and args.area.casefold() not in ('bolzano','bozen') and len(rows)>1)
    return outcome(db,'charging.discover_sites',dict(sites=results[args.offset:args.offset+args.limit],total=len(rows),
        missing_coordinates=missing, area_rule='Bolzano context bounding box EPSG:4326 from config/sources.json; not municipal boundary',
        next_offset=args.offset+args.limit if len(rows)>args.offset+args.limit else None),
        'needs_clarification' if ambiguous else ('available' if rows else 'unavailable'))

def inventory(db,args):
    results=[]
    for ident in dict.fromkeys(args.site_ids):
        row=db.execute('SELECT * FROM sites WHERE id=?',(ident,)).fetchone()
        plugs=[dict(r) for r in db.execute('SELECT id,source,payload FROM plugs WHERE site_id=? ORDER BY id LIMIT 501',(ident,))]
        if len(plugs)>500:
            raise ValueError('Inventory exceeds bounded tool scope')
        results.append(dict(site_id=ident, status='available' if row else 'unavailable',
            inventory_count=len(plugs) if row else None, metadata=json.loads(row['payload']) if row else None,
            points=[dict(id=p['id'],source=p['source'],metadata=json.loads(p['payload'])) for p in plugs]))
    return outcome(db,'charging.get_inventory',{'sites':results},'available' if any(r['status']=='available' for r in results) else 'unavailable')

def raw_period(db,args,ident):
    raw={}
    for p in db.execute('SELECT id FROM plugs WHERE site_id=? ORDER BY id',(ident,)):
        rows=db.execute('SELECT * FROM observations WHERE plug_id=? AND observed_at>=? AND observed_at<=? AND transaction_at<=? ORDER BY observed_at,transaction_at,id LIMIT 200001',
            (p['id'],(args.start-timedelta(minutes=args.gap_minutes)).isoformat().replace('+00:00','Z'),args.end.isoformat().replace('+00:00','Z'),args.end.isoformat().replace('+00:00','Z'))).fetchall()
        if len(rows)>200000 or sum(map(len,raw.values()))+len(rows)>500000:
            raise ValueError('Observation budget exceeded; narrow the requested period')
        raw[p['id']]=[dict(r) for r in rows]
    return raw

def quality(db,args):
    from ...ingestion import utc
    results=[]
    for ident in args.site_ids:
        raw=raw_period(db,args,ident)
        rows=[r for group in raw.values() for r in group]
        gaps=[]
        for group in raw.values():
            times=sorted({utc(r['observed_at']) for r in group})
            gaps.extend((b-a).total_seconds()/60 for a,b in zip(times,times[1:]))
        latest=max((r['observed_at'] for r in rows),default=None)
        pages=sorted({r['source_page_id'] for r in rows})
        results.append(dict(site_id=ident, status='available' if rows else 'unavailable', units={'observations':'observations','gap_count':'gaps','gap_minutes':'minutes','median_cadence_minutes':'minutes'}, points=len(raw) if raw else None, observations=len(rows),
            missing_points=[p for p,v in raw.items() if not v], latest_observation=latest,
            stale=latest is None or datetime.now(timezone.utc)-utc(latest)>timedelta(days=1),
            gap_count=sum(g>args.gap_minutes for g in gaps),gap_minutes=args.gap_minutes,
            median_cadence_minutes=sorted(gaps)[len(gaps)//2] if gaps else None,
            source_pages=[dict(db.execute('SELECT id,sha256,acquired_at FROM source_pages WHERE id=?',(p,)).fetchone()) for p in pages],
            start=args.start.isoformat(),end=args.end.isoformat()))
    return outcome(db,'charging.get_data_quality',dict(sites=results),'available' if any(r['observations'] for r in results) else 'unavailable')

def execute(db,run,name,args):
    if run.capability_profile != 'charging':
        raise ValueError('Tool not authorized by workspace profile')
    if name in ('charging.get_operational_inputs','charging.assess_expansion'):
        from .operations import read, expansion
        return read(db,args) if name.endswith('get_operational_inputs') else expansion(db,args)
    if name in ('charging.get_usage_summary','charging.compare_maintenance_windows'):
        from .metrics import usage, maintenance
        return usage(db,args) if name.endswith('get_usage_summary') else maintenance(db,args)
    if name=='charging.discover_sites': return discover(db,args)
    if name=='charging.get_inventory': return inventory(db,args)
    if name=='charging.get_data_quality': return quality(db,args)
    if name=='charging.get_evidence':
        stored=ToolOutcome.model_validate(artifact(db,run.id,args.evidence_id)['outcome'])
        if args.path:
            value=stored.data
            try:
                for part in args.path.split('.'):
                    value=value[int(part)] if isinstance(value,list) else value[part]
            except (KeyError,IndexError,ValueError,TypeError):raise ValueError('Unknown evidence detail path')
            if isinstance(value,list):value=value[args.offset:args.offset+args.limit]
            return stored.model_copy(update={'data':{'original_evidence_id':args.evidence_id,'path':args.path,'value':value},
                'summary':'Scoped detail from immutable evidence '+args.evidence_id+' at '+args.path})
        return stored
    raise ValueError('Unknown charging tool')

class ForecastArgs(Sites):
    site_ids: list[str] = Field(min_length=1,max_length=3)
    cutoff: AwareDatetime = Field(description='UTC whole-hour forecast origin, e.g. 2026-11-14T00:00:00Z; never substitute generation time')
    history_days: int = Field(default=56,ge=28,le=180)
    horizon_hours: int = Field(default=168,ge=1,le=168)
    service_threshold: float = Field(default=.9,gt=0,lt=1)
    gap_minutes: int = Field(default=120,ge=1,le=480)
    minimum_valid_fraction: float = Field(default=.25,gt=0,le=1)
    offline: bool = True

    @model_validator(mode='after')
    def origin_aligned(self):
        self.cutoff=self.cutoff.astimezone(timezone.utc)
        if self.cutoff.minute or self.cutoff.second or self.cutoff.microsecond:
            raise ValueError('Forecast cutoff must be a whole UTC hour')
        return self

SCHEMAS['charging.request_forecast']=ForecastArgs


def context_data(value):
    metrics=[]
    for i,site in enumerate(value.get('data',{}).get('sites',[])):
        if value.get('status')!='available' or site.get('status')=='unavailable' or not site.get('start') or not site.get('end'):continue
        for field,unit in site.get('units',{}).items():
            if isinstance(site.get(field),(int,float)):
                metrics.append(dict(evidence_id=value['evidence_id'],path=f'sites.{i}.{field}',value=site[field],unit=unit,site_id=site['site_id'],start=site['start'],end=site['end']))
        for j,candidate in enumerate(site.get('candidates',[])):
            for field,unit in site.get('units',{}).items():
                if isinstance(candidate.get(field),(int,float)):
                    metrics.append(dict(evidence_id=value['evidence_id'],path=f'sites.{i}.candidates.{j}.{field}',value=candidate[field],unit=unit,site_id=site['site_id'],start=site['start'],end=site['end']))
    value['metric_reference_examples']=metrics[:100]
    # Keep useful aggregate fields when hourly series exceed the prompt budget.
    value=json.loads(json.dumps(value))
    for site in value.get('data',{}).get('sites',[]):
        site.pop('hours',None)
        site.pop('source_pages',None)
    return value
