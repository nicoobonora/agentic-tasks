import json
from datetime import timedelta
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.acs.api import app
from backend.acs.db import connect, transaction
from backend.acs.ingestion import ODHClient, windows, utc, CONFIG
from backend.acs.normalize import rebuild

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('ACS_DB', str(tmp_path/'test.sqlite'))
    return TestClient(app)

META = {'pcode': 's1', 'pname': 'BZ_PIAVE_01', 'pmetadata': {}, 'pcoordinate': None,
        'scode': 'p1', 'sname': 'plug', 'smetadata': {'connectors': []}}

def test_windows_contiguous_and_bounded():
    start, end = utc('2024-11-01T00:00:00Z'), utc('2026-06-10T00:00:00Z')
    chunks = list(windows(start, end, 5))
    assert chunks[0][0] == start and chunks[-1][1] == end
    assert all(b-a <= timedelta(days=5) for a,b in chunks)
    assert all(chunks[i][1] == chunks[i+1][0] for i in range(len(chunks)-1))
    with pytest.raises(ValueError):
        list(windows(end,start))

def test_real_adapter_pagination_cache_dedup_and_provenance(tmp_path, monkeypatch):
    monkeypatch.setitem(CONFIG, 'page_size', 2)
    calls = []
    def handler(request):
        calls.append(str(request.url))
        offset = int(request.url.params['offset'])
        if request.url.path.endswith('/EChargingPlug'):
            rows = [META] if offset == 0 else []
        else:
            rows = [{'scode': 'p1', 'mvalidtime': f'2026-10-01 {h:02}:00:00+0000', 'mvalue': 'CHARGING'} for h in range(3)][offset:offset+2]
        return httpx.Response(200, json={'data': rows})
    db = connect(tmp_path / 'data.sqlite')
    adapter = ODHClient(db, tmp_path / 'raw', httpx.Client(transport=httpx.MockTransport(handler)))
    adapter.metadata('Neogy-AMPECO')
    for _ in range(2):
        adapter.observations('Neogy-AMPECO', utc('2026-10-01T00:00:00Z'), utc('2026-10-02T00:00:00Z'))
    assert len(calls) == 3  # metadata and 2 pages, then cache
    assert db.execute('SELECT count(*) FROM observations').fetchone()[0] == 3
    counts = rebuild(db)
    assert counts['transitions'] == 1 and counts['heartbeats'] == 3
    ep = dict(db.execute('SELECT * FROM episodes').fetchone())
    assert ep['left_censored'] and ep['right_censored'] and ep['duration_seconds'] == 7200
    assert db.execute('SELECT count(*) FROM observation_pages').fetchone()[0] == 3
    db.close()

def test_gap_does_not_create_occupancy_across_missing_days(tmp_path):
    db = connect(tmp_path/'data.sqlite')
    db.execute("INSERT INTO sites VALUES ('s','s','source','{}')")
    db.execute("INSERT INTO plugs VALUES ('p','s','source',?)", (json.dumps({'connectors': []}),))
    db.execute("INSERT INTO source_pages VALUES ('e','url','date','hash','path',3,'history')")
    for i, (time, status) in enumerate([('2026-08-01T00:00:00Z','AVAILABLE'), ('2026-08-01T00:01:00Z','CHARGING'), ('2026-08-03T00:00:00Z','AVAILABLE')]):
        db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?)', (str(i),'p',time,time,status,'e'))
    rebuild(db)
    episode = dict(db.execute('SELECT * FROM episodes').fetchone())
    assert episode['duration_seconds'] == 0 and episode['right_censored']
    db.close()

def test_live_fallback_is_explicit(client, monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(ODHClient, 'metadata', fail)
    response = client.get('/examples/charging/api/v1/live?refresh=true')
    assert response.status_code == 200
    assert response.json()['mode'] == 'snapshot' and response.json()['stale']
    assert response.json()['warning']


def test_live_timeout_preserves_local_observations_and_evidence(client, monkeypatch, tmp_path):
    from backend.acs.examples.charging import api as charging_api
    with transaction() as db:
        adapter = ODHClient(db, tmp_path/'raw', httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={'data': [META] if request.url.path.endswith('/EChargingPlug') else [
                {'scode': 'p1', 'mvalidtime': '2026-10-01T00:00:00Z', 'mvalue': 'AVAILABLE'}]}))))
        try:
            adapter.metadata('Neogy-AMPECO')
            adapter.observations('Neogy-AMPECO', latest=True)
        finally:
            adapter.client.close()
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout('Controlled timeout', request=request)

    def live_adapter(db, **kwargs):
        assert kwargs == {'timeout': 5, 'attempts': 1}
        return ODHClient(db, tmp_path/'refresh', httpx.Client(transport=httpx.MockTransport(timeout)), **kwargs)

    monkeypatch.setattr(charging_api, 'ODHClient', live_adapter)
    response = client.get('/examples/charging/api/v1/live?refresh=true')
    assert response.status_code == 200
    data = response.json()
    assert data['mode'] == 'snapshot' and data['stale'] and data['warning']
    assert len(calls) == 1 and len(data['items']) == 1
    proof = data['items'][0]['source_page_id']
    metadata = client.get(f'/examples/charging/api/v1/evidence/{proof}').json()
    assert metadata['origin'] == 'real'
    assert client.get(metadata['raw_url']).json()['data'][0]['mvalue'] == 'AVAILABLE'


@pytest.mark.parametrize('corruption', ['checksum', 'gzip'])
def test_raw_evidence_rejects_corruption(client, tmp_path, corruption):
    import gzip
    import hashlib
    raw = b'{"data": []}'
    path = tmp_path/'proof.gz'
    path.write_bytes(gzip.compress(b'changed' if corruption == 'checksum' else raw))
    if corruption == 'gzip':
        path.write_bytes(b'not gzip')
    with transaction() as db:
        db.execute('INSERT INTO source_pages VALUES (?,?,?,?,?,?,?)',
                   ('proof', 'https://example.test/data', '2026-11-14T00:00:00Z',
                    hashlib.sha256(raw).hexdigest(), str(path), 0, 'latest'))
    response = client.get('/examples/charging/api/v1/evidence/proof/raw')
    assert response.status_code == 409
    assert response.json()['code'] == 'corrupt_evidence'

def test_contract_export_matches_api():
    from backend.acs.db import ROOT
    assert json.loads((ROOT/'contracts/openapi.json').read_text()) == app.openapi()

def test_analysis_contract_rejects_duplicate_cells_and_invented_fingerprint(tmp_path):
    from backend.acs.examples.charging.models import AnalysisBundle
    from backend.acs.analysis_contract import check_bundle, input_fingerprint
    from backend.acs.db import ROOT
    from pydantic import ValidationError
    example = json.loads((ROOT/'contracts/examples/analysis.unavailable.json').read_text())
    broken = json.loads(json.dumps(example))
    broken['tables'][0]['cells'][3] = broken['tables'][0]['cells'][0]
    with pytest.raises(ValidationError):
        AnalysisBundle.model_validate(broken)
    db = connect(tmp_path/'analysis.sqlite')
    db.execute("INSERT INTO source_pages VALUES ('REPLACE_WITH_REAL_EVIDENCE_ID','u','t','sha','p',0,'history')")
    with pytest.raises(ValueError, match='fingerprint'):
        check_bundle(db, AnalysisBundle.model_validate(example))
    example['input_sha256'] = input_fingerprint(db,['REPLACE_WITH_REAL_EVIDENCE_ID'])
    check_bundle(db, AnalysisBundle.model_validate(example))
    db.close()

def test_erlang_and_minimum_increment(tmp_path):
    from backend.acs.analysis_contract import immediate_access, input_fingerprint, check_bundle
    from backend.acs.examples.charging.models import AnalysisBundle
    from backend.acs.db import ROOT
    assert immediate_access(1,1,1) == .5
    assert immediate_access(0,1,2) == 1
    assert immediate_access(0,1,0) == 0
    example = json.loads((ROOT/'contracts/examples/analysis.unavailable.json').read_text())
    db = connect(tmp_path/'analysis.sqlite')
    db.execute("INSERT INTO source_pages VALUES ('REPLACE_WITH_REAL_EVIDENCE_ID','u','t','sha','p',0,'history')")
    example['input_sha256'] = input_fingerprint(db,['REPLACE_WITH_REAL_EVIDENCE_ID'])
    table = example['tables'][0]
    table['operational_capacity'] = 2
    cell = table['cells'][0]
    cell.update(status='available',reason=None,demand_per_hour=1,mean_occupancy_hours=1,
        access_current=immediate_access(1,1,2),access_plus_2=immediate_access(1,1,4),access_plus_4=immediate_access(1,1,6),
        required_total_capacity=4,minimum_increment=2)
    check_bundle(db,AnalysisBundle.model_validate(example))
    cell['minimum_increment'] = 4
    with pytest.raises(ValueError,match='minimum_increment'):
        check_bundle(db,AnalysisBundle.model_validate(example))
    db.close()

def test_simulated_provenance_is_not_real(client):
    response = client.get('/examples/charging/api/v1/evidence/catalog:offers:OFFER-A')
    assert response.status_code == 200
    evidence = response.json()
    assert evidence['origin'] == 'simulated' and evidence['acquired_at'] is None
    raw = client.get(evidence['raw_url'])
    import hashlib
    assert hashlib.sha256(raw.content).hexdigest() == evidence['sha256']
