"""Stable checkout paths, independent of caller cwd and Python package depth."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / 'backend'
FRONTEND_ROOT = PROJECT_ROOT / 'frontend'
TOOLS_ROOT = PROJECT_ROOT / 'tools'
