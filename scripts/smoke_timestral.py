"""Real inference smoke on an exported series; never publishes a usable forecast."""
import argparse
import json
import time
from pathlib import Path
from backend.acs.examples.charging.forecast import Timestral, values
from backend.acs.examples.charging.forecast_models import ForecastBundle

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=Path('data/exports/forecast-latest.json'))
    parser.add_argument('--output',type=Path,default=Path('data/exports/timestral-smoke.json'))
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args()
    bundle=ForecastBundle.model_validate_json(args.input.read_text())
    site=next((s for s in bundle.sites if any(h.demand_p1 is not None for h in s.hours)),None)
    if site is None:
        raise ValueError('No observed values in the input; cannot smoke-test on these data')
    started=time.monotonic()
    predicted=Timestral(offline=args.offline).predict(values(site.hours),bundle.input_start,bundle.horizon_hours)
    report={'model':bundle.model_name,'revision':bundle.model_revision,'live_model_verified':True,
        'input':'real ODH hourly reconstructed series, '+site.site_name,'input_forecast_id':bundle.id,
        'valid_fraction':site.valid_fraction,'shape':list(predicted.shape),'seconds':round(time.monotonic()-started,2),
        'first_hour_p1_quantiles':predicted[0,0].tolist(),'published_as_usable_forecast':False,
        'reason':'Adapter smoke only. This command does not override coverage or backtest requirements.'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
