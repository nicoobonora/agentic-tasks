"""Server-selected charging workspace; never selected by model prose."""
PROFILE_ID = 'charging'
PROFILE_VERSION = '1'
INSTRUCTIONS = '''This workspace concerns charging infrastructure only. For unrelated goals explain
scope and request clarification. Discover sites and retrieve quality before site-specific
factual conclusions. Status observations are not official sessions, energy, unmet demand,
physical faults, maintenance requirements or investment feasibility. Keep sources separate.
Human answers are preferences/assumptions, not independently verified observations.
Use tools for calculations. Cite immutable evidence and structured metric references for
numerical claims (exact path, value, unit, site and period). Copy metric_reference_examples
from tool results; paths are rooted in artifact data, using dot-separated indexes.
Do not assert a supported number if no compatible typed metric is available.
Never attach metric_references to unavailable results (including empty maintenance rankings).
For unavailable results state qualitative reasons without quantitative factual claims.
A claim may cite unavailable evidence qualitatively but must not invent a metric.
When maintenance windows are unavailable, ask the human which missing operational
inputs or data-refresh plan to prioritize. Draft only a conditional investigation
plan; keep claims qualitative unless copying an available metric reference exactly. Unavailable means unknown, not zero.
March 1 2027 is a delivery deadline, not a supported forecast horizon. Forecasts support at
most 168 hours. Clarify stations versus chargers/points/sites, geography, budget and service
policy. Missing permits, quotes, connection capacity and maintenance records remain unknown.
The forecast policy defaults to 90%; the simulated catalog's 95% is a different explicit
scenario. Never silently mix them. Approving a proposal executes nothing.
Critic must discuss evidence sufficiency, competing interpretations and open objections.'''

def capability():
    from ...profiles import CapabilityProfile
    from . import tools
    from .validation import validate
    from .service import execute_job
    def schemas():
        tools.normalize('charging.discover_sites', {})
        return tools.SCHEMAS
    return CapabilityProfile(PROFILE_ID, PROFILE_VERSION, INSTRUCTIONS, schemas,
        tools.normalize,tools.snapshot,tools.execute,validate,
        frozenset({'charging.request_forecast'}),execute_job,tools.context_data)
