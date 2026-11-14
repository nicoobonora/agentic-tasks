"""Test-only injection lives outside production app configuration."""
import uvicorn
from backend.acs.api import app
from backend.acs import investigation,jobs
from tests.e2e_server import ControlledProvider
investigation.provider_for=lambda run:ControlledProvider()
jobs.JOB_MODULE='tests.e2e_numerical_worker'
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=8015,log_level='warning')
