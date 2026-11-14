import json
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from backend.acs.db import transaction
from backend.acs.examples.charging.tools import normalize, execute, snapshot

@pytest.fixture
def db(tmp_path):
    with transaction(tmp_path/'test.sqlite') as db:
        for ident,name,x in [('a','DUP',11.35),('b','DUP',12),('c','Missing',None)]:
            db.execute('INSERT INTO sites VALUES (?,?,?,?)',(ident,name,'Neogy-AMPECO',json.dumps({'coordinates':{'x':x,'y':46.49}})))
        yield db

def call(db,name,args):
    name='charging.'+name
    return execute(db,SimpleNamespace(capability_profile='charging'),name,normalize(name,args))

def test_discovery_scope_and_ambiguity(db):
    r=call(db,'discover_sites',{'area':'Bolzano'})
    assert [s['id'] for s in r.data['sites']]==['a']
    assert r.data['missing_coordinates']==['c']
    assert call(db,'discover_sites',{'area':'DUP'}).status=='needs_clarification'
    assert call(db,'discover_sites',{'area':"' OR 1=1 --"}).status=='unavailable'
    assert call(db,'get_inventory',{'site_ids':['absent']}).data['sites'][0]['inventory_count'] is None
    before=snapshot(db)
    db.execute("UPDATE sites SET name='new',payload='{}' WHERE id='a'")
    assert before != snapshot(db)

def test_invalid_capabilities(db):
    for name,args in [('shell',{}),('charging.discover_sites',{'limit':1000}),('charging.get_inventory',{'site_ids':['a'],'sql':'x'})]:
        with pytest.raises((ValueError,ValidationError)): normalize(name,args)
    with pytest.raises(ValueError): execute(db,SimpleNamespace(capability_profile=None),'charging.discover_sites',normalize('charging.discover_sites',{}))

def test_empty_quality(db):
    r=call(db,'get_data_quality',dict(site_ids=['a'],start='2026-10-01T00:00:00Z',end='2026-11-01T00:00:00Z'))
    assert r.status=='unavailable'
    assert r.data['sites'][0]['stale']

def test_observed_metrics_unknown_and_windows(db):
    from datetime import datetime,timedelta,timezone
    db.execute("INSERT INTO source_pages VALUES ('page','url','2026-10-01','hash','unused',1,'test')")
    db.execute("INSERT INTO plugs VALUES ('plug','a','Neogy-AMPECO','{}')")
    start=datetime(2026,9,20,tzinfo=timezone.utc)
    # Synthetic regular available/charging observations across the Rome DST transition.
    for i in range(42*24+1):
        t=(start+timedelta(hours=i)).isoformat().replace('+00:00','Z')
        db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?)',(str(i),'plug',t,t,'CHARGING' if i%24 in (12,13) else 'AVAILABLE','page'))
    args=dict(site_ids=['a'],start=start.isoformat(),end=(start+timedelta(days=42)).isoformat())
    r=call(db,'get_usage_summary',args).data['sites'][0]
    assert r['observed_starts']==42
    assert r['occupied_point_hours']==84
    assert r['coverage']==1
    w=call(db,'compare_maintenance_windows',{**args,'duration_hours':2})
    assert w.status=='available'
    assert w.data['sites'][0]['maintenance_need']=='unknown'
    assert w.data['sites'][0]['candidates'][0]['mean_occupied_point_hours']==0
    short={**args,'end':(start+timedelta(days=7)).isoformat()}
    assert call(db,'compare_maintenance_windows',short).status=='unavailable'
    db.execute("UPDATE observations SET status='OUTOFORDER'")
    assert call(db,'compare_maintenance_windows',args).status=='unavailable'
    assert call(db,'get_usage_summary',args).data['sites'][0]['occupancy_fraction'] is None

def test_readiness_missing_points_and_cutoff(db):
    from scripts.charging_readiness import report
    db.execute('INSERT INTO plugs VALUES (?,?,?,?)',('p','a','Neogy-AMPECO',json.dumps({'connectors':[{'power_type':'AC_3_PHASE','max_electric_power':22000}]})))
    r=report(db,'2026-11-14T00:00:00Z')
    a=next(s for s in r['sites'] if s['site_id']=='a')
    assert a['points_without_observations']==['p']
    assert all(s['usable_hours']==0 for s in a['sensitivity'])

def test_operational_unknown_and_simulated_arithmetic(db):
    from backend.acs.examples.charging.operations import OperationalRecord,import_record
    args=dict(quantity=20,quantity_unit='point',start_date='2026-11-14',deadline='2027-03-01',budget_including_tax='10000')
    assert call(db,'assess_expansion',args).data['feasibility']=='unknown'
    import_record(db,OperationalRecord(id='quote',version=1,kind='quote',classification='simulated',provenance='Synthetic test',effective_from='2026-01-01',effective_until='2027-12-31',amount_ex_tax='1000',tax_rate='.22',quantity_unit='charger',points_per_charger=2))
    result=call(db,'assess_expansion',{**args,'record_ids':['quote:v1']})
    assert result.data['quoted_quantity']==10
    assert result.data['total_including_tax']=='12200.00'
    assert result.data['checks']['budget']=='violated'
    assert result.origin=='simulated_business'
    assert result.data['checks']['permits']=='unknown'
