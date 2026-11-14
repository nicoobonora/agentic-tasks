"""Real local Timestral inference, backtests, persistence and JSON export."""
import argparse
from pathlib import Path
from backend.acs.examples.charging.forecast import run

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--end', help='Forecast origin, ISO UTC hour; default current UTC hour')
    parser.add_argument('--history-days',type=int,default=56)
    parser.add_argument('--horizon-hours',type=int,default=168)
    parser.add_argument('--folds',type=int,default=2)
    parser.add_argument('--gap-minutes',type=int,default=120)
    parser.add_argument('--minimum-exposure-minutes',type=int,default=10)
    parser.add_argument('--minimum-valid-fraction',type=float,default=.25)
    parser.add_argument('--offline',action='store_true',help='Require model weights already cached')
    parser.add_argument('--output',type=Path,default=Path('data/exports/forecast-latest.json'))
    args=parser.parse_args()
    bundle=run(end=args.end,days=args.history_days,horizon=args.horizon_hours,folds=args.folds,
        gap=args.gap_minutes,min_minutes=args.minimum_exposure_minutes,min_fraction=args.minimum_valid_fraction,offline=args.offline)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(bundle.model_dump_json(indent=2)+'\n')
    print(f'Saved {bundle.id}; analysis {bundle.analysis_id}; {args.output}')
    for site in bundle.sites:
        print(f'{site.site_name}: {site.status}, observed hours {site.valid_fraction:.1%}, method={site.selected_method}, reason={site.reason}')

if __name__=='__main__':
    main()
