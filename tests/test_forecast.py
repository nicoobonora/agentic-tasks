from datetime import datetime, timedelta, timezone
import json
import pytest
from backend.acs.examples.charging.forecast import reconstruct, forecast_site, seasonal, score, values, Timestral
from backend.acs.db import connect

START=datetime(2026,9,1,tzinfo=timezone.utc)

def observation(i, hour, status, transaction=None):
    t=START+timedelta(hours=hour)
    return dict(id=str(i), observed_at=t.isoformat(),transaction_at=(transaction or t).isoformat(),status=status,source_page_id='e')

def test_reconstruction_gap_censoring_zero_and_correction():
    rows=[observation(0,0,'AVAILABLE'),observation(1,.5,'CHARGING'),observation(2,1,'AVAILABLE'),
          observation(3,2,'AVAILABLE'),observation(4,8,'AVAILABLE')]
    h,d,e=reconstruct({'p':rows},START,START+timedelta(hours=9))
    assert h[0].exposure_hours==1 and h[0].full_hours==.5
    assert h[0].observed_starts==1 and h[0].demand_p1==2 and h[0].demand_p05==1.5
    assert h[1].demand_p1==0  # observed zero, not missing
    assert h[2].demand_p1 is None and h[7].exposure_hours==0 and h[8].exposure_hours==0
    assert d==[.5] and e=={'e'}

def test_no_lookahead_or_late_revision_and_whole_group_required():
    rows=[observation(0,0,'AVAILABLE'),observation(1,1,'AVAILABLE'),observation(2,2,'CHARGING'),
          observation(3,1,'CHARGING',START+timedelta(hours=5))]
    h,_,_=reconstruct({'p':rows},START,START+timedelta(hours=1))
    assert h[0].mean_occupied==0
    h,_,_=reconstruct({'p':rows},START,START+timedelta(minutes=30))
    assert h==[]
    h,_,_=reconstruct({'p':rows,'missing':[]},START,START+timedelta(hours=3))
    assert all(x.demand_p1 is None for x in h)

def test_zero_capacity_and_full_capacity_do_not_become_zero_demand():
    for state in ['OUTOFORDER','CHARGING','UNKNOWN']:
        h,_,_=reconstruct({'p':[observation(0,0,state),observation(1,1,state)]},START,START+timedelta(hours=1))
        assert h[0].demand_p1 is None

def test_seasonal_does_not_use_holdout_values():
    np=pytest.importorskip('numpy')
    history=np.tile(np.arange(168,dtype=float),4)[None,:].repeat(2,axis=0)
    q=seasonal(history,168)
    assert np.array_equal(q[0,:,1],history[0,-168:])
    assert (q[:,:,0]<=q[:,:,1]).all() and (q[:,:,1]<=q[:,:,2]).all()

class FakePredictor:
    """Explicit deterministic test double, never selected by production configuration."""
    def __init__(self): self.lengths=[]
    def predict(self, history, start, horizon):
        import numpy as np
        self.lengths.append(history.shape[1])
        return np.full((2,horizon,3),2.)

def full_rows(days=42):
    # One half-hour charging episode every hour, known throughout.
    return [observation(i,i/2,'AVAILABLE' if i%2==0 else 'CHARGING') for i in range(days*48+1)]

def test_backtest_boundaries_selection_and_capacity():
    pytest.importorskip('numpy')
    predictor=FakePredictor()
    site=forecast_site({'id':'s','name':'BZ_PIAVE_01'},{'p':full_rows()}, {'e'}, START,
        START+timedelta(days=42),168,2,predictor,120,10,.25)
    assert site.status=='available' and len(site.points)==336
    assert predictor.lengths==[28*24,35*24,42*24]
    assert len(site.backtest)==4 and all(s.samples==336 for s in site.backtest)
    assert site.selected_method=='seasonal_naive'
    assert site.scenario_capacity==1 and site.complete_episodes>20


def test_timestral_adapter_shapes_and_bad_output():
    np=pytest.importorskip('numpy')
    class Output:
        def quantile(self,q): return np.full((1,2,24),q)
    class Model:
        def forecast(self,context,**kwargs):
            assert context.shape==(1,2,336)
            assert kwargs['known_covariates'].shape==(1,4,360)
            return Output()
    adapter=Timestral.__new__(Timestral);adapter.model=Model()
    assert adapter.predict(np.ones((2,336)),START,24).shape==(2,24,3)
    Output.quantile=lambda self,q:np.full((1,2,24),float('nan'))
    with pytest.raises(ValueError,match='non-finite'):
        adapter.predict(np.ones((2,336)),START,24)


def test_full_pipeline_persistence_api_and_analysis(tmp_path,monkeypatch):
    pytest.importorskip('numpy')
    from backend.acs.examples.charging.forecast import run,SITES
    from backend.acs.analysis_contract import check_bundle
    from backend.acs.examples.charging.models import AnalysisBundle
    from backend.acs.api import app
    from fastapi.testclient import TestClient
    path=tmp_path/'forecast.sqlite';monkeypatch.setenv('ACS_DB',str(path))
    db=connect(path)
    db.execute("INSERT INTO source_pages VALUES ('e','u','t','sha','p',1,'history')")
    for i,name in enumerate(SITES):
        sid=f's{i}';pid=f'p{i}'
        db.execute('INSERT INTO sites VALUES (?,?,?,?)',(sid,name,'Neogy-AMPECO',json.dumps({'id':sid,'name':name,'evidence_id':'e'})))
        db.execute('INSERT INTO plugs VALUES (?,?,?,?)',(pid,sid,'Neogy-AMPECO',json.dumps({'evidence_id':'e','connectors':[{'power_type':'AC_3_PHASE','max_electric_power':22000}]})))
        for r in full_rows():
            db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?)',(pid+r['id'],pid,r['observed_at'],r['transaction_at'],r['status'],'e'))
    db.commit();db.close()
    result=run(end=(START+timedelta(days=42)).isoformat(),days=42,predictor=FakePredictor())
    with TestClient(app) as client:
        listed=client.get('/examples/charging/api/v1/forecasts').json()
        assert listed[0]['id']==result.id
        assert client.get('/examples/charging/api/v1/forecasts/'+result.id).status_code==200
        assert client.get('/examples/charging/api/v1/forecasts/missing').status_code==404
        analysis=AnalysisBundle.model_validate(client.get('/examples/charging/api/v1/analysis').json()[0])
        db=connect(path);check_bundle(db,analysis);db.close()
        assert all(c.status=='available' for t in analysis.tables for c in t.cells)
        task=client.get('/examples/charging/task').json()
        assert result.id in task['attachments'][0]['text']
    subset, paired = run(end=(START+timedelta(days=42)).isoformat(),days=42,predictor=FakePredictor(),site_ids=['s1'],service_threshold=.95,publish=False)
    assert [s.site_id for s in subset.sites]==['s1']
    assert paired.schema_version=='1.1' and paired.tables[0].service_threshold==.95
    assert subset.analysis_id==paired.id
    db=connect(path);check_bundle(db,paired);db.execute('DELETE FROM observations');db.commit();db.close()
    monkeypatch.setattr('backend.acs.examples.charging.forecast.Timestral',lambda *a: (_ for _ in ()).throw(AssertionError('Weights loaded on unavailable input')))
    unavailable,_=run(end=(START+timedelta(days=42)).isoformat(),days=42,site_ids=['s1'],publish=False)
    assert unavailable.parameters['model_inference_calls']==0
    assert unavailable.sites[0].points==[]


def test_comparable_days_and_unavailable_never_calls_model():
    from backend.acs.examples.charging.forecast import comparable_days
    pytest.importorskip('numpy')
    hours,_,_=reconstruct({'p':full_rows(28)},START,START+timedelta(days=28))
    assert comparable_days(hours,START+timedelta(days=28),168)
    assert not comparable_days(hours[:21*24],START+timedelta(days=28),168)
    predictor=FakePredictor()
    site=forecast_site({'id':'s','name':'BZ_PIAVE_01'},{'p':[]},{'e'},START,
        START+timedelta(days=42),168,2,predictor,120,10,.25)
    assert site.status=='unavailable' and site.points==[] and predictor.lengths==[]

def test_request_bounds():
    from backend.acs.examples.charging.forecast import run
    import pytest
    for kwargs in ({'horizon':169},{'site_ids':[]},{'service_threshold':1},{'end':'2026-11-14T00:30:00Z'}):
        with pytest.raises(ValueError): run(**kwargs)
