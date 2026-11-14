"""Exercise two domains through HTTP. Human answers are explicitly simulated test input."""
import argparse
import json
import time
from uuid import uuid4
import httpx


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['auto','mock','model'],default='mock')
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    args=parser.parse_args()
    with httpx.Client(base_url=args.base_url,timeout=30) as client:
        response=client.get('/examples/charging/task');response.raise_for_status()
        tasks=[response.json(),{'title':'Guida per nuovi volontari',
            'description':'Proporre una guida breve di accoglienza per i volontari di una biblioteca.',
            'context':'Usare risorse già disponibili. Il primo risultato desiderato è una guida di due pagine.',
            'attachments':[{'name':'Disponibilità','text':'I volontari sono disponibili sabato mattina.'}]}]
        for task in tasks:
            body={'task':task,'max_rounds':2,'idempotency_key':str(uuid4())}
            if args.mode != 'auto':
                body['mode'] = args.mode
            response=client.post('/api/v2/runs',json=body)
            response.raise_for_status();run=response.json();deadline=time.monotonic()+900;answers=0
            while time.monotonic()<deadline:
                response=client.get('/api/v2/runs/'+run['id']);response.raise_for_status();run=response.json()
                if run['state']=='failed':
                    raise RuntimeError(run['error'])
                if run['state']=='proposal_ready':
                    print(json.dumps({'task':task['title'],'mode':run['mode'],'run_id':run['id'],
                        'state':run['state'],'proposal_version':run['proposal_version'],'status':run['proposal']['status'],
                        'messages':len(run['messages']),'simulated_human_answers':answers},ensure_ascii=False),flush=True)
                    break
                if run['state']=='awaiting_input':
                    if answers>=3:
                        raise RuntimeError('Smoke stopped after three simulated human answers; inspect run '+run['id'])
                    question=run['question']
                    response=client.post('/api/v2/runs/'+run['id']+'/answers',json={
                        'proposal_version':run['proposal_version'],'idempotency_key':str(uuid4()),'question_id':question['id'],
                        'option_id':question['options'][0]['id'],'actor':'Smoke-test operator (simulated)',
                        'text':'Risposta simulata di test: preferisco un primo passo limitato e reversibile. Conservare le incertezze e non inventare dati mancanti.',
                        'finalize_with_unresolved':question['reason']=='round_limit'})
                    response.raise_for_status();answers+=1
                time.sleep(.25)
            else:
                raise RuntimeError('Smoke timeout; persisted run '+run['id'])

if __name__=='__main__':
    main()
