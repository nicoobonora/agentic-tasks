"""Explicit test-only server, always uses a temporary database and controlled providers."""
import os
import json
import tempfile
import subprocess
import sys
import signal
import time
from pathlib import Path
from datetime import timedelta
import uvicorn
from tests.test_forecast import START,full_rows
from backend.acs.db import transaction
from backend.acs.providers import MockProvider,Result
from backend.acs.capabilities import ToolRequest
from backend.acs.models import QuestionDraft,Option,ObjectionDraft

class ControlledProvider:
    def generate(self,run,role,correction=None):
        result=MockProvider().generate(run,role,correction)
        result.turn.explanation='CONTROLLED SYNTHETIC INTEGRATION TEST. No live model.'
        if role=='critic' and run.cycle>1 and run.round==1:
            result.turn.objections=[ObjectionDraft(target_message_id=None,concern='Feasibility remains unverified',explanation='Synthetic reviewer requests an explicit conditional revision.',blocking=False,evidence_ids=[])]
            result.turn.needs_revision=True
            return result
        if role=='analyst' and run.cycle==1:
            result.turn.question=QuestionDraft(text='Confermi unità, area e priorità?',explanation='Colonnine non equivale automaticamente a punti. Budget e permessi restano mancanti.',options=[Option(id='points',label='Punti di ricarica a Bolzano',explanation='Obiettivo aziendale da verificare'),Option(id='clarify',label='Specificare il perimetro',explanation='Fornire informazioni mancanti')])
            return result
        if role=='analyst' and not run.proposal or role=='analyst' and run.cycle>1:
            called={c.request.name for c in run.tool_activity}
            period=dict(site_ids=['fixture-site'],start=START.isoformat(),end=(START+timedelta(days=56)).isoformat())
            requests=[('charging.discover_sites',{'area':'Bolzano'}),('charging.get_data_quality',period),('charging.get_usage_summary',period)]
            if 'manutenzione' in run.task.title.lower():
                requests += [('charging.request_forecast',dict(site_ids=['fixture-site'],cutoff=(START+timedelta(days=56)).isoformat(),history_days=56,horizon_hours=24)),('charging.compare_maintenance_windows',period)]
            else:
                requests += [('charging.assess_expansion',dict(quantity=20,quantity_unit='point',start_date='2026-11-14',deadline='2027-03-01'))]
            for name,args in requests:
                if name not in called:return Result(requests=[ToolRequest(call_id=name,name=name,arguments=args)])
            ids=[e.id for e in run.evidence if e.artifact_id]
            result.turn.evidence_ids=ids
            result.turn.draft.recommended_actions[0].evidence_ids=ids
            result.turn.draft.summary='SYNTHETIC TEST: proposta condizionata alle verifiche operative e ai dati disponibili.'
        return result

def seed():
    with transaction() as db:
        db.execute("INSERT INTO source_pages VALUES ('e','synthetic://fixture','2026-11-01T00:00:00Z','synthetic-hash','unused',1,'synthetic')")
        db.execute('INSERT INTO sites VALUES (?,?,?,?)',('fixture-site','BZ_PIAVE_01','Neogy-AMPECO',json.dumps({'evidence_id':'e','coordinates':{'x':11.35,'y':46.49}})))
        db.execute('INSERT INTO plugs VALUES (?,?,?,?)',('fixture-plug','fixture-site','Neogy-AMPECO',json.dumps({'evidence_id':'e','connectors':[{'power_type':'AC_3_PHASE','max_electric_power':22000}]})))
        for r in full_rows(56):db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?)',(r['id'],'fixture-plug',r['observed_at'],r['transaction_at'],r['status'],'e'))

def main():
    with tempfile.TemporaryDirectory(prefix='charging-e2e-') as directory:
        os.environ.update(ACS_DB=directory+'/test.sqlite',OPENAI_API_KEY='',ACS_MODEL='',ACS_CORS_ORIGINS='http://127.0.0.1:4175')
        os.environ['ACS_JOB_LEASE_SECONDS']='5'
        seed()
        child=None
        restarting=False
        def restart(signum,frame):
            nonlocal restarting
            restarting=True
        signal.signal(signal.SIGUSR1,restart)
        def stop(signum,frame): raise SystemExit(0)
        signal.signal(signal.SIGTERM,stop)
        signal.signal(signal.SIGINT,stop)
        Path('test-results').mkdir(exist_ok=True)
        Path('test-results/e2e-supervisor.pid').write_text(str(os.getpid()))
        try:
            child=subprocess.Popen([sys.executable,'-m','tests.e2e_app'],start_new_session=True)
            while child.poll() is None:
                if restarting:
                    os.killpg(child.pid,signal.SIGKILL);child.wait()
                    child=subprocess.Popen([sys.executable,'-m','tests.e2e_app'],start_new_session=True)
                    restarting=False
                time.sleep(.1)
        finally:
            if child and child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
if __name__=='__main__':main()
