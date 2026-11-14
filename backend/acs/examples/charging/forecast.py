"""Offline Timestral pipeline. No model imports or downloads in the HTTP server."""
import hashlib
import json
import math
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .forecast_models import ForecastBundle, SiteForecast, Hour, ForecastPoint, Score
from .models import AnalysisBundle, ControlTable, Cell
from ...analysis_contract import input_fingerprint, immediate_access, check_bundle
from ...db import transaction, get, put
from ...ingestion import utc

MODEL = 'mistralai/Timestral-28M'
REVISION = '49b26409ac87b5935539a5d8ffe7f397b720db47'
VERSION = 'timestral-charging-v1'
SITES = ('BZ_C_RISPARMIO_01', 'BZ_PIAVE_01', 'RENON_01')
KNOWN = {'AVAILABLE', 'CHARGING', 'INOPERATIVE', 'OUTOFORDER', 'REMOVED', 'BLOCKED', 'RESERVED'}
OPERATIONAL = {'AVAILABLE', 'CHARGING'}
LIMITATIONS = [
    'Conditional estimates, not measured latent demand or certified capacity recommendations.',
    'Current AC <=22kW registry assumed constant over this window; legacy and DC excluded.',
    'State held only between consecutive observations within the declared gap threshold.',
    'Demand correction assumes stationary arrivals during observable exposure and independent blocking.',
    'Missing hours remain missing; zero capacity and fully saturated hours do not imply zero demand.',
    'Complete episode durations may underrepresent long/censored occupancies; no energy inferred.',
    'Calendar uses Europe/Rome hour and weekday only; holidays, weather and school vacations not included.',
    'Backtest uses records whose valid and transaction times precede each cutoff; registry history is not certified.',
    'Pointwise quantiles are not simultaneous intervals or quantiles of a daily maximum.',
]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def reconstruct(raw, start, end, gap_minutes=120, min_minutes=10):
    """Exact interval sweep; no forward-fill across gaps or beyond last observation.

    Only fully known group states contribute exposure. Starts are counted only
    from AVAILABLE with the other plugs known at that instant. E/F/A are hourly.
    Reconstruct separately at each backtest cutoff to prevent lookahead.
    """
    n = int((end-start).total_seconds() // 3600)
    buckets = [[0., 0., 0, 0., 0.] for _ in range(n)]  # E,F,A,occupied,operational
    events = defaultdict(list)
    starts = defaultdict(list)
    durations, evidence = [], set()
    for plug, all_rows in raw.items():
        effective = {}
        for row in all_rows:
            if utc(row['observed_at']) <= end and utc(row['transaction_at']) <= end:
                effective[row['observed_at']] = row
        rows = sorted(effective.values(), key=lambda r: utc(r['observed_at']))
        episode_start = None
        for a, b in zip(rows, rows[1:]):
            ta, tb = utc(a['observed_at']), utc(b['observed_at'])
            valid = 0 < (tb-ta).total_seconds() <= gap_minutes*60
            if not valid:
                episode_start = None
                continue
            if tb >= start and ta < end:
                evidence.update([a['source_page_id'], b['source_page_id']])
                if a['status'] in KNOWN:
                    events[max(start,ta)].append((plug,a['status']))
                    events[min(end,tb)].append((plug,None))
            if a['status'] == 'AVAILABLE' and b['status'] == 'CHARGING':
                episode_start = tb
                starts[tb].append(plug)
            elif a['status'] == 'CHARGING' and b['status'] != 'CHARGING':
                if episode_start is not None and episode_start >= start:
                    seconds = (tb-episode_start).total_seconds()
                    if 120 <= seconds < 48*3600:
                        durations.append(seconds/3600)
                episode_start = None
    state = {p: None for p in raw}
    previous = start
    for time in sorted(set(events) | set(starts) | {start, end}):
        if not start <= time <= end:
            continue
        known = bool(state) and all(v is not None for v in state.values())
        capacity = sum(v in OPERATIONAL for v in state.values())
        occupied = sum(v == 'CHARGING' for v in state.values())
        if known and capacity:
            cursor = previous
            while cursor < time:
                i = int((cursor-start).total_seconds()//3600)
                stop = min(time, start+timedelta(hours=i+1))
                if 0 <= i < n:
                    seconds = (stop-cursor).total_seconds()
                    buckets[i][0] += seconds
                    buckets[i][1] += seconds if occupied == capacity else 0
                    buckets[i][3] += occupied*seconds
                    buckets[i][4] += capacity*seconds
                cursor = stop
            if time < end:
                i = int((time-start).total_seconds()//3600)
                buckets[i][2] += sum(state[p] == 'AVAILABLE' for p in starts[time])
        # End intervals first, then start intervals at the same timestamp.
        for p, status in sorted(events[time], key=lambda x: x[1] is not None):
            state[p] = status
        previous = time
    hours = []
    for i, (e,f,a,o,c) in enumerate(buckets):
        # Both total and non-full exposure must exceed the declared minimum.
        usable = e >= min_minutes*60 and e-f >= min_minutes*60
        rate = a/(e/3600) if e else None
        corrected = a/((e-f)/3600) if usable else None
        hours.append(Hour(time=start+timedelta(hours=i), exposure_hours=e/3600, full_hours=f/3600,
            observed_starts=a, mean_occupied=o/e if e else None, mean_operational=c/e if e else None,
            demand_p1=corrected, demand_p05=(rate+corrected)/2 if usable else None))
    return hours, durations, evidence


def values(hours):
    import numpy as np
    return np.array([[h.demand_p1 if h.demand_p1 is not None else np.nan for h in hours],
                     [h.demand_p05 if h.demand_p05 is not None else np.nan for h in hours]])


def calendar(start, length):
    import numpy as np
    result=[]
    for i in range(length):
        t=(start+timedelta(hours=i)).astimezone(ZoneInfo('Europe/Rome'))
        result.append([math.sin(2*math.pi*t.hour/24), math.cos(2*math.pi*t.hour/24),
                       math.sin(2*math.pi*t.weekday()/7), math.cos(2*math.pi*t.weekday()/7)])
    return np.array(result).T


class Timestral:
    def __init__(self, offline=False):
        import torch
        from timestral import TimestralForecaster
        torch.set_num_threads(4)
        self.model = TimestralForecaster.from_pretrained(MODEL, revision=REVISION,
            device='cpu', local_files_only=offline)

    def predict(self, history, start, horizon):
        import numpy as np
        out = self.model.forecast(history[None, :, :], prediction_length=horizon,
            known_covariates=calendar(start, history.shape[1]+horizon)[None,:,:])
        def array(q):
            value=out.quantile(q)
            if hasattr(value,'detach'):
                value=value.detach().cpu().numpy()
            return np.asarray(value).reshape(2,horizon)
        result=np.stack([array(.1),array(.5),array(.9)],axis=-1)
        if not np.isfinite(result).all() or (np.diff(result,axis=-1)<-1e-6).any():
            raise ValueError('Timestral returned non-finite or unordered quantiles')
        return np.maximum(result,0)


def seasonal(history, horizon):
    """Same UTC hour last week; empirical residual interval from training only."""
    import numpy as np
    predicted=np.array([history[:, -168+i%168] for i in range(horizon)]).T
    result=np.repeat(predicted[:,:,None],3,axis=-1)
    for v in range(2):
        residuals=history[v,168:]-history[v,:-168]
        residuals=residuals[np.isfinite(residuals)]
        if len(residuals) >= 24:
            result[v,:,0]=predicted[v]+min(0,float(np.quantile(residuals,.1)))
            result[v,:,2]=predicted[v]+max(0,float(np.quantile(residuals,.9)))
        else:
            result[v,:,:]=np.nan
    return np.maximum(result,0)


def score(method, fold, cutoff, actual, predicted, mask):
    import numpy as np
    if not mask.any():
        return Score(method=method,fold=fold,cutoff=cutoff,samples=0,mae=None,pinball=None,coverage_80=None)
    y, q=actual[mask],predicted[mask]
    error=y[:,None]-q
    loss=np.maximum(np.array([.1,.5,.9])*error, (np.array([.1,.5,.9])-1)*error)
    return Score(method=method,fold=fold,cutoff=cutoff,samples=len(y),
        mae=float(np.abs(y-q[:,1]).mean()),pinball=float(loss.mean()),
        coverage_80=float(((y>=q[:,0]) & (y<=q[:,2])).mean()))


def comparable_days(hours, future_start, horizon):
    """Require four distinct observed dates for each future local weekday/hour."""
    support=defaultdict(set)
    for h in hours:
        if h.demand_p1 is not None:
            local=h.time.astimezone(ZoneInfo('Europe/Rome'))
            support[(local.weekday(),local.hour)].add(local.date())
    for i in range(horizon):
        local=(future_start+timedelta(hours=i)).astimezone(ZoneInfo('Europe/Rome'))
        if len(support[(local.weekday(),local.hour)])<4:
            return False
    return True


def forecast_site(site, raw, metadata_evidence, start, end, horizon, folds, predictor, gap, min_minutes, min_fraction):
    import numpy as np
    hours,durations,evidence=reconstruct(raw,start,end,gap,min_minutes)
    history=values(hours)
    valid=float(np.isfinite(history).mean()) if history.size else 0
    result=SiteForecast(site_id=site['id'],site_name=site['name'],plug_ids=sorted(raw),status='unavailable',
        reason=None,selected_method=None,valid_fraction=valid,evidence_ids=sorted(evidence|metadata_evidence),
        hours=hours,points=[],backtest=[],mean_occupancy_hours=float(np.mean(durations)) if durations else None,
        complete_episodes=len(durations),scenario_capacity=None,limitations=list(LIMITATIONS))
    if not raw or valid < min_fraction or not np.isfinite(history[:,-24:]).any():
        result.reason='Insufficient observed hourly coverage or no usable hours in the last day.'
        return result
    if not comparable_days(hours,end,horizon):
        result.reason='Fewer than four comparable observed dates for a future weekday/hour.'
        return result
    for fold in range(folds):
        cutoff=end-timedelta(hours=horizon*(folds-fold))
        train,_,_=reconstruct(raw,start,cutoff,gap,min_minutes)
        train_values=values(train)
        if len(train)<336 or np.isfinite(train_values).mean()<min_fraction:
            result.reason='Insufficient training coverage for backtest.'
            return result
        if not comparable_days(train,cutoff,horizon):
            result.reason='Fewer than four comparable observed dates in backtest training.'
            return result
        offset=len(train)
        actual=history[:,offset:offset+horizon]
        predictions={'timestral':predictor.predict(train_values,start,horizon),
                     'seasonal_naive':seasonal(train_values,horizon)}
        # Compare both methods on identical observed targets; report the sample count.
        mask=np.isfinite(actual)&np.isfinite(predictions['seasonal_naive']).all(axis=-1)
        for method,predicted in predictions.items():
            result.backtest.append(score(method,fold,cutoff,actual,predicted,mask))
        if int(mask.sum()) < max(24, int(horizon*2*.25)):
            result.reason='Too few common held-out observations to compare methods.'
            return result
    totals={method:sum(s.pinball*s.samples for s in result.backtest if s.method==method)/
                    sum(s.samples for s in result.backtest if s.method==method)
            for method in ('timestral','seasonal_naive')}
    final={'timestral':predictor.predict(history,start,horizon),'seasonal_naive':seasonal(history,horizon)}
    eligible=[m for m in totals if np.isfinite(final[m]).all()]
    method=min(eligible,key=lambda m:totals[m])
    result.selected_method=method
    result.status='available'
    result.points=[ForecastPoint(time=end+timedelta(hours=i),p=p,p10=float(final[method][v,i,0]),
        p50=float(final[method][v,i,1]),p90=float(final[method][v,i,2])) for v,p in enumerate((1.,.5)) for i in range(horizon)]
    # Registry is not assumed operational: modal mean capacity on well-covered recent hours.
    recent=[h.mean_operational for h in hours[-168:] if h.exposure_hours>=.9 and h.mean_operational is not None
            and abs(h.mean_operational-round(h.mean_operational))<1e-6]
    if len(recent)>=24:
        counts={int(c):recent.count(c) for c in set(recent)}
        c=max(counts,key=counts.get)
        if counts[c]/len(recent)>=.9:
            result.scenario_capacity=c
    return result


def analysis_bundle(bundle):
    threshold=bundle.parameters.get("service_threshold", .9)
    tables=[]
    for site in bundle.sites:
        cells=[]
        reason=site.reason
        if site.scenario_capacity is None:
            reason=reason or 'No stable operational capacity in recent well-covered hours.'
        if site.complete_episodes<20:
            reason=reason or 'Fewer than 20 complete occupancy episodes.'
        for p in (1.,.5):
            for quantile,field in [('p50','p50'),('high','p90')]:
                if reason:
                    cells.append(Cell(p=p,quantile=quantile,status='unavailable',reason=reason))
                    continue
                demand=max(getattr(point,field) for point in site.points if point.p==p)
                duration=site.mean_occupancy_hours
                access=lambda c: immediate_access(demand,duration,c)
                required=next((c for c in range(1001) if access(c)>=threshold),None)
                if required is None:
                    cells.append(Cell(p=p,quantile=quantile,status='unavailable',reason='Capacity exceeds search bound 1000.'))
                    continue
                c=site.scenario_capacity
                cells.append(Cell(p=p,quantile=quantile,status='available',demand_per_hour=demand,
                    mean_occupancy_hours=duration,access_current=access(c),access_plus_2=access(c+2),access_plus_4=access(c+4),
                    access_restored=access(len(site.plug_ids)) if site.site_name=='RENON_01' else None,
                    required_total_capacity=required,minimum_increment=next((d for d in (0,2,4) if access(c+d)>=threshold),None)))
        tables.append(ControlTable(site_name=site.site_name,method=site.selected_method or 'timestral',
            period_start=bundle.forecast_start.date(),period_end=(bundle.forecast_start+timedelta(hours=bundle.horizon_hours)-timedelta(seconds=1)).date(),
            measure_nature='Conditional Erlang-B scenarios from peak hourly corrected demand, not an investment recommendation.',
            high_quantile_definition='pointwise_p90_peak',operational_capacity=site.scenario_capacity or 0,
            registry_capacity=len(site.plug_ids),restored_capacity=len(site.plug_ids) if site.site_name=='RENON_01' else None,
            service_threshold=threshold,cells=cells,evidence_ids=site.evidence_ids,limitations=site.limitations))
    return AnalysisBundle(schema_version="1.0" if len(bundle.sites)==3 else "1.1", id=bundle.analysis_id,generated_at=bundle.generated_at,input_sha256=bundle.input_sha256,
        input_start=bundle.input_start,input_end=bundle.forecast_start,method_version=VERSION,
        cleaning_parameters=bundle.parameters,reconstruction_parameters={'formula':'A/E + p*(A/(E-F)-A/E)',
            'duration':'mean complete episodes 120s..48h; >=20 required',
            'capacity':'modal recent capacity; >=24 hours with >=90% exposure and >=90% agreement',
            'scenario':'Erlang-B stationary Poisson arrivals, independent holding times, no queue; assumptions not verified'},
        model_name=MODEL,model_version=REVISION,covariates=bundle.covariates,
        backtest={s.site_name:[b.model_dump(mode='json') for b in s.backtest] for s in bundle.sites},tables=tables)


def run(end=None, days=56, horizon=168, folds=2, gap=120, min_minutes=10, min_fraction=.25, offline=False, predictor=None, site_ids=None, service_threshold=.9, publish=True, db_path=None):
    if not 0 < service_threshold < 1:
        raise ValueError('Service threshold must be a probability between zero and one')
    if site_ids is not None and (not site_ids or len(site_ids)>3 or len(set(site_ids))!=len(site_ids)):
        raise ValueError('Select one to three distinct supported site IDs')
    if not 1<=horizon<=168 or not 1<=folds<=4 or not 1<=gap<=480 or not 1<=min_minutes<=60 or not 0<min_fraction<=1:
        raise ValueError('Invalid horizon, folds, gap, exposure or coverage settings')
    if not 28<=days<=180 or days*24-folds*horizon<336:
        raise ValueError('Need >=14 training days before the first backtest fold (28..180 total days)')
    end=utc(end) if end else datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    if end.minute or end.second or end.microsecond:
        raise ValueError('Forecast start must be aligned to a UTC hour')
    start=end-timedelta(days=days)
    inputs=[]
    with transaction(db_path) as db:
        for name in (site_ids if site_ids is not None else SITES):
            site=db.execute("SELECT * FROM sites WHERE source='Neogy-AMPECO' AND "+("id=?" if site_ids is not None else "name=?"),(name,)).fetchone()
            if site is None:
                raise ValueError(f'Missing current registry for {name}; download data first')
            if site['name'] not in SITES:
                raise ValueError('Unsupported site; forecasting currently supports the three validated AC groups only')
            raw={}
            metadata={json.loads(site['payload'])['evidence_id']}
            for plug in db.execute('SELECT * FROM plugs WHERE site_id=?',(site['id'],)):
                payload=json.loads(plug['payload'])
                connectors=payload['connectors']
                if not connectors or not all(str(c.get('power_type','')).startswith('AC') and
                    0<(c.get('max_electric_power') or 0)<=22000 for c in connectors):
                    continue
                metadata.add(payload['evidence_id'])
                raw[plug['id']]=[dict(r) for r in db.execute(
                    'SELECT * FROM observations WHERE plug_id=? AND observed_at>=? AND observed_at<=? ORDER BY observed_at,transaction_at,id',
                    (plug['id'],(start-timedelta(minutes=gap)).isoformat().replace('+00:00','Z'),
                     end.isoformat().replace('+00:00','Z')))]
            inputs.append((dict(site),raw,metadata))
    # Weights are loaded only after all eligibility checks reach actual inference.
    class Counted:
        calls=0
        backend=predictor
        def predict(self, *args):
            if self.backend is None:
                self.backend=Timestral(offline)
            self.calls += 1
            return self.backend.predict(*args)
    counted=Counted()
    sites=[forecast_site(site,raw,meta,start,end,horizon,folds,counted,gap,min_minutes,min_fraction) for site,raw,meta in inputs]
    evidence=sorted({e for s in sites for e in s.evidence_ids})
    with transaction(db_path) as db:
        fingerprint=input_fingerprint(db,evidence)
    ident='forecast:'+str(uuid.uuid4())
    bundle=ForecastBundle(id=ident,generated_at=datetime.now(timezone.utc),model_name=MODEL,model_revision=REVISION,
        method_version=VERSION,input_sha256=fingerprint,
        series_sha256=hashlib.sha256(canonical([s.model_dump(mode='json')['hours'] for s in sites]).encode()).hexdigest(),
        input_start=start,forecast_start=end,horizon_hours=horizon,
        parameters={'service_threshold':service_threshold,'history_days':days,'gap_minutes':gap,'minimum_exposure_minutes':min_minutes,
                    'minimum_valid_fraction':min_fraction,'folds':folds,'selection':'minimum common-sample mean pinball; finite future required',
                    'minimum_comparable_days':4,'model_inference_calls':counted.calls,'imputed_fraction':0,'source':'Neogy-AMPECO','group':'AC <=22kW'},
        covariates=['local_hour_sin','local_hour_cos','local_weekday_sin','local_weekday_cos'],sites=sites,
        analysis_id='analysis:'+ident.split(':')[1],limitations=list(LIMITATIONS))
    analysis=analysis_bundle(bundle)
    if not publish:
        return bundle, analysis
    with transaction(db_path) as db:
        check_bundle(db,analysis)
        for kind,obj in [('forecast',bundle),('analysis',analysis)]:
            if get(db,kind,obj.id) is not None:
                raise ValueError('Artifact ID already exists')
            put(db,kind,obj.id,obj.model_dump(mode='json'))
    return bundle
