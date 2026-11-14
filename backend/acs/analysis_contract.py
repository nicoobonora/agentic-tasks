"""Small deterministic checks shared by the importer and the future critic."""
import hashlib
import json
import math
from .examples.charging.models import AnalysisBundle


def immediate_access(arrivals_per_hour: float, mean_hours: float, capacity: int) -> float:
    if arrivals_per_hour < 0 or mean_hours <= 0 or capacity < 0:
        raise ValueError("Invalid Erlang inputs")
    if capacity == 0:
        return 0.0
    load = arrivals_per_hour * mean_hours
    blocking = 1.0
    for k in range(1, capacity + 1):
        blocking = load * blocking / (k + load * blocking)
    return 1.0 - blocking


def input_fingerprint(db, evidence_ids):
    inputs = []
    for ident in sorted(set(evidence_ids)):
        row = db.execute("SELECT sha256 FROM source_pages WHERE id=?", (ident,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown source evidence: {ident}")
        inputs.append({"id": ident, "sha256": row[0]})
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def check_bundle(db, bundle: AnalysisBundle):
    fingerprint = input_fingerprint(db, [e for t in bundle.tables for e in t.evidence_ids])
    if bundle.input_sha256 != fingerprint:
        raise ValueError("Input fingerprint does not match referenced source pages")
    for table in bundle.tables:
        for cell in table.cells:
            if cell.status == "unavailable":
                continue
            def access(c):
                return immediate_access(cell.demand_per_hour, cell.mean_occupancy_hours, c)
            for increment, provided in [(0, cell.access_current), (2, cell.access_plus_2), (4, cell.access_plus_4)]:
                if not math.isclose(access(table.operational_capacity + increment), provided, abs_tol=1e-6):
                    raise ValueError(f"Erlang mismatch: {table.site_name}, {cell.p}, {cell.quantile}, +{increment}")
            required = cell.required_total_capacity
            if access(required) < table.service_threshold or (required > 0 and access(required - 1) >= table.service_threshold):
                raise ValueError("required_total_capacity is not the minimum satisfying the threshold")
            minimum = next((n for n in (0, 2, 4) if access(table.operational_capacity + n) >= table.service_threshold), None)
            if cell.minimum_increment != minimum:
                raise ValueError("minimum_increment is inconsistent with the access probabilities")
            if table.restored_capacity is not None:
                if cell.access_restored is None or not math.isclose(access(table.restored_capacity), cell.access_restored, abs_tol=1e-6):
                    raise ValueError("Restored capacity probability is missing or inconsistent")
