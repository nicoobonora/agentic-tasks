PYTHON ?= .venv/bin/python

.PHONY: setup download prepare api mock test contracts forecast-setup forecast
setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt
	npm ci

download:
	$(PYTHON) -m scripts.download_data --network --legacy

prepare:
	$(PYTHON) -m scripts.prepare_data

api:
	$(PYTHON) -m uvicorn backend.acs.api:app --host 127.0.0.1 --port 8000

mock:
	ACS_DB=data/mock.sqlite $(PYTHON) -m uvicorn backend.acs.api:app --host 127.0.0.1 --port 8001

test:
	$(PYTHON) -m pytest -q
	npm run typecheck

contracts:
	$(PYTHON) -m scripts.export_contracts
	npm run contracts:types

forecast-setup:
	.venv/bin/pip install -r requirements-forecast.txt

forecast:
	$(PYTHON) -m scripts.forecast_charging
