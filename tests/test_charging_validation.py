from types import SimpleNamespace
import pytest
from backend.acs.examples.charging.validation import validate, has_quantity
from backend.acs.models import Claim


@pytest.mark.parametrize('statement', [
    'The data-quality result over 2026-09-19T00:00:00Z through 2026-11-14T00:00:00Z is unavailable.',
    'The comparison covers 2026-08-01 to 2026-11-14.',
    'Candidate slots fall between 06:00 and 22:00 Europe/Rome.',
    'The lowest-occupancy slot starts at 16:00–18:00 on Tuesday.',
    'Timestamp 2026-11-14T00:07:01.268+01:00 is the latest observation.',
    'BZ_PIAVE_01 has no recent observations.',
])
def test_calendar_references_are_not_quantities(statement):
    assert not has_quantity(statement)


@pytest.mark.parametrize('statement', [
    'Mean occupancy is 1.72 point hours.',
    'Coverage is 90% at 16:00.',
    'A 2-hour window was compared.',
    'There are 10 candidate slots.',
])
def test_quantities_still_detected(statement):
    assert has_quantity(statement)


def run_with_metric_evidence():
    return SimpleNamespace(id='run', evidence=[SimpleNamespace(id='artifact-1', origin='derived_metric', artifact_id='artifact-1')])


def turn(statement):
    return SimpleNamespace(claims=[Claim(statement=statement, basis='supported', evidence_ids=['artifact-1'])])


def test_supported_claim_with_timestamps_only_passes(tmp_path, monkeypatch):
    monkeypatch.setenv('ACS_DB', str(tmp_path/'test.sqlite'))
    validate(run_with_metric_evidence(), turn('No ranked slot exists between 2026-09-19T00:00:00Z and 2026-11-14T00:00:00Z within 06:00–22:00.'))


def test_supported_claim_with_quantity_still_needs_reference(tmp_path, monkeypatch):
    monkeypatch.setenv('ACS_DB', str(tmp_path/'test.sqlite'))
    with pytest.raises(ValueError, match='structured metric references'):
        validate(run_with_metric_evidence(), turn('Mean occupancy at 16:00 is 1.72 point hours.'))
