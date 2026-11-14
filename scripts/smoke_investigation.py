"""Explicit paid live protocol smoke, isolated consistent SQLite backup; never ordinary tests."""
import argparse,json,os,sqlite3,tempfile
from pathlib import Path
from backend.acs.config import load_environment
from backend.acs.db import transaction
from backend.acs.models import CreateRun
from backend.acs import discussion,jobs
from backend.acs.providers import settings

def main():
    p=argparse.ArgumentParser();p.add_argument('--source-db',default='data/acs.sqlite');p.add_argument('--output',default='docs/investigation-live.json');p.add_argument('--max-steps',type=int,default=8)
    p.add_argument('--scenario',choices=['expansion','maintenance','unrelated']);a=p.parse_args();load_environment();config=settings()
    if not config['key'] or not config['model']:raise SystemExit('Live validation unavailable: configure model and key')
    report={'classification':'live-protocol validation, not real-data analytical validation','model':config['model'],'generated_at':discussion.now().isoformat(),'scenarios':[]}
    with tempfile.TemporaryDirectory(prefix='charging-live-') as directory:
        dest=sqlite3.connect(directory+'/live.sqlite');source=sqlite3.connect(f'file:{Path(a.source_db).resolve()}?mode=ro',uri=True)
        source.backup(dest);source.close();dest.close();os.environ['ACS_DB']=directory+'/live.sqlite'
        for ident,title in [('expansion','Vogliamo aggiungere 20 colonnine entro il 1 marzo 2027.'),('maintenance','Quando dovremmo effettuare manutenzione delle colonnine nell’area di Bolzano?'),('unrelated','Scrivi una poesia sulla luna.')]:
            if a.scenario and ident!=a.scenario:continue
            run=discussion.create(CreateRun(task={'title':title,'description':title},mode='model',capability_profile='charging',idempotency_key='live-'+ident+'-'+directory))
            for _ in range(max(1,min(24,a.max_steps))):
                if run.state!='running':break
                discussion.step(run.id)
                with transaction() as db:run=discussion.load(db,run.id)
                if run.turn_progress and run.turn_progress.pending_job_id:
                    job=jobs.claim(run.turn_progress.pending_job_id)
                    if job:jobs.execute(job.id,job.lease_token)
            from backend.acs.tools import artifact
            with transaction() as db:
                outcomes={c.artifact_id:artifact(db,run.id,c.artifact_id) for c in run.tool_activity if c.artifact_id}
            report['scenarios'].append(dict(scenario=ident,state=run.state,error=run.error.model_dump() if run.error else None,
                artifacts=outcomes,tool_trace=[dict(name=c.request.name,status=c.status,artifact_id=c.artifact_id,parameters=c.normalized_parameters) for c in run.tool_activity],
                provider_attempts=run.provider_attempts,reported_successful_response_usage=run.model_usage,provider_requests_current_turn=run.turn_progress.provider_requests if run.turn_progress else None,
                public_messages=[dict(role=m.actor,text=m.content.text,explanation=m.content.explanation) for m in run.messages],
                question=run.question.text if run.question else None,
                limitation='Smoke stops at first human decision or bounded step count; no human answers or approvals fabricated.'))
            Path(a.output).write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
if __name__=='__main__':main()
