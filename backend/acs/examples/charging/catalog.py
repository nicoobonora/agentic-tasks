import json
from ...db import ROOT
from ...errors import Conflict, require
from .models import Catalog

CATALOG = Catalog.model_validate_json((ROOT / "config/catalog.json").read_text()).model_dump(mode="json")

def catalog_document(ident):
    if ident == "catalog:policy":
        return CATALOG["policy"]
    for section in ("site_assessments", "products", "offers", "work_schedule", "contract_terms", "economic_parameters"):
        for index, item in enumerate(CATALOG[section]):
            key = item.get("id", item.get("site_name", str(index)))
            if ident == f"catalog:{section}:{key}":
                return item
    return None
