"""Application composition root for server-authorized capabilities.

Only registered profiles can grant tools. Domain behavior is supplied by the profile,
not inferred from task text or tool names.
"""
from dataclasses import dataclass
from typing import Callable

@dataclass(frozen=True)
class CapabilityProfile:
    id: str
    version: str
    instructions: str
    schemas: Callable
    normalize: Callable
    snapshot: Callable
    execute: Callable
    validate_turn: Callable
    analytical_tools: frozenset[str]
    execute_job: Callable
    context: Callable

def get_profile(ident):
    if ident is None:return None
    # Explicit server composition, not model-controlled dynamic imports.
    from .examples.charging.profile import capability
    profiles={'charging':capability}
    if ident not in profiles:raise ValueError('Unknown capability profile')
    return profiles[ident]()
