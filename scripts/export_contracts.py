import json
from backend.acs.api import app
from backend.acs.examples.charging.api import app as charging_app
from backend.acs.examples.charging.models import AnalysisBundle
from backend.acs.models import StreamEvent, AgentTurn
from backend.acs.db import ROOT

def main():
    schemas = {'openapi': app.openapi(), 'analysis.schema': AnalysisBundle.model_json_schema(),
               'charging.openapi': charging_app.openapi(), 'events.schema': StreamEvent.model_json_schema(),
               'agent-turn.schema': AgentTurn.model_json_schema()}
    for name,value in schemas.items():
        (ROOT/'contracts'/f'{name}.json').write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')

if __name__ == '__main__':
    main()
