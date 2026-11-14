"""Load server configuration from the project root, independent of working directory."""
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def load_environment(root: Path = ROOT):
    # Explicit process values win, then local overrides, then shared defaults.
    # Disable interpolation so credentials containing ${...} remain literal.
    for name in ('.env.local', '.env'):
        load_dotenv(root / name, override=False, interpolate=False)
