"""Charging-specific numerical capture, validation and publication payloads."""
import os
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime,timezone
from ...db import ROOT,transaction
from ...tools import digest
from ...capabilities import ToolOutcome
from ...analysis_contract import check_bundle
from .tools import snapshot
from .forecast import run

def execute_job(call,predictor=None):
    p=call.normalized_parameters
    source=sqlite3.connect(f"file:{Path(os.getenv('ACS_DB',ROOT/'data/acs.sqlite')).resolve()}?mode=ro",uri=True)
    with tempfile.TemporaryDirectory(prefix='forecast-source-') as directory:
        captured=Path(directory)/'source.sqlite'
        dest=sqlite3.connect(captured)
        try:source.backup(dest)
        finally:source.close();dest.close()
        with transaction(captured) as db:
            expected=digest(dict(tool=call.request.name,parameters=p,source=snapshot(db),version=call.method_version))
            if expected!=call.cache_key:raise ValueError('Source snapshot changed before job capture; request a new calculation')
        bundle,analysis=run(end=p['cutoff'],days=p['history_days'],horizon=p['horizon_hours'],gap=p['gap_minutes'],
            min_fraction=p['minimum_valid_fraction'],site_ids=p['site_ids'],service_threshold=p['service_threshold'],
            offline=p['offline'],publish=False,predictor=predictor,db_path=captured)
        with transaction(captured) as db:check_bundle(db,analysis)
    data=bundle.model_dump(mode='json')
    for site in data['sites']:site.pop('hours',None)
    data['analysis']=analysis.model_dump(mode='json')
    outcome=ToolOutcome(status='available' if any(s.status=='available' for s in bundle.sites) else 'unavailable',
        summary='Forecast '+bundle.id+': '+ '; '.join(s.site_name+': '+(s.selected_method or s.reason or s.status) for s in bundle.sites),
        data=data,limitations=bundle.limitations,source_fingerprint=bundle.input_sha256,method=bundle.method_version,
        queried_at=datetime.now(timezone.utc),origin='forecast')
    return outcome,[(kind,obj.id,obj.model_dump(mode='json')) for kind,obj in [('forecast',bundle),('analysis',analysis)]]
