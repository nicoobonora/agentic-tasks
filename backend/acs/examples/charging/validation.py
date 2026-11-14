"""Checks citation identity and typed numerical equality, not semantic truth of prose."""
import math
import re
from datetime import timedelta
from ...tools import artifact
from ...db import transaction
from ...ingestion import utc

def validate(run,turn):
    indexed={e.id:e for e in run.evidence}
    with transaction() as db:
        for claim in turn.claims:
            if claim.basis=='supported':
                observed=[indexed[e] for e in claim.evidence_ids if e in indexed and indexed[e].origin in ('observation','derived_metric','forecast')]
                if not observed:raise ValueError('Charging factual claims require retrieved observational/analytical evidence, not human preferences')
                if re.search(r'(?<![\w])\d+(?![\w])',re.sub(r'\d{4}-\d{2}-\d{2}', '', claim.statement)) and not claim.metric_references:
                    raise ValueError('Numerical supported claims require structured metric references')
            for ref in claim.metric_references:
                if ref.evidence_id not in claim.evidence_ids or ref.evidence_id not in indexed:
                    raise ValueError('Metric reference must cite attached claim evidence')
                evidence=indexed[ref.evidence_id]
                if evidence.origin not in ('observation','derived_metric','forecast') or not evidence.artifact_id:
                    raise ValueError('Assumptions and simulated business inputs are not observed metrics')
                result=artifact(db,run.id,evidence.artifact_id)['outcome']
                if result['status']!='available':raise ValueError('Unavailable/error result cannot support a numerical assertion')
                value=result['data'];ancestors=[value]
                parts=ref.path.removeprefix('data.').strip('/').replace('/', '.').split('.')
                try:
                    for part in parts:
                        value=value[int(part)] if isinstance(value,list) else value[part]
                        if isinstance(value,dict):ancestors.append(value)
                except (KeyError,IndexError,ValueError,TypeError):raise ValueError('Unknown metric path '+ref.path+'; use a supplied metric_reference_examples entry, with path rooted in artifact data (e.g. sites.0.observed_starts)')
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isclose(value,ref.value,rel_tol=1e-6,abs_tol=1e-9):
                    raise ValueError('Metric value mismatch (relative tolerance 1e-6; absolute 1e-9)')
                site=next((a for a in reversed(ancestors) if 'site_id' in a),None)
                if not site or site['site_id']!=ref.site_id or site.get('status')=='unavailable':raise ValueError('Metric site/status mismatch')
                root=result['data'];field=parts[-1]
                unit=site.get('units',{}).get(field)
                if evidence.origin=='forecast' and field in ('p10','p50','p90'):unit='estimated requests/hour'
                if unit!=ref.unit:raise ValueError(f'Metric {ref.path}: unit {ref.unit!r} does not match canonical unit {unit!r}. Copy the tool metric_reference_examples verbatim; omit unsupported numerical assertions.')
                start=site.get('start') or root.get('forecast_start')
                end=site.get('end')
                if not end and root.get('forecast_start'):
                    end=(utc(root['forecast_start'])+timedelta(hours=root['horizon_hours'])).isoformat()
                if not start or not end or utc(start)!=ref.start or utc(end)!=ref.end:raise ValueError('Metric period mismatch')
