import sys
import time
from backend.acs.jobs import execute
from tests.test_forecast import FakePredictor
if __name__=='__main__':
    time.sleep(3)  # Test-only delay makes browser refresh/restart observable.
    execute(sys.argv[1],sys.argv[2],predictor=FakePredictor())
