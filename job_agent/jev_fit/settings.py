"""The existing TYPESAFE_ENABLED switch selects fit scoring, with pinned models."""
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'jev-fit-production-1'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def settings(environ=None):
    return {**dotenv_values(ROOT / '.env'), **(os.environ if environ is None else environ)}


def enabled(environ=None):
    return str(settings(environ).get('TYPESAFE_ENABLED') or 'false').strip().lower() in {'true', '1', 'yes'}


@dataclass(frozen=True)
class Settings:
    key: str = field(repr=False)
    model: str = 'jev-1.13.0'
    base_url: str = 'https://api.typesafe.ai'
    timeout: float = 12
    cache_path: Path | None = None
    ttl: float = 86400
    unknown_ttl: float = 300

    @classmethod
    def load(cls, *, cache_path=None, environ=None):
        values = settings(environ)
        model = str(values.get('TYPESAFE_FIT_MODEL') or values.get('TYPESAFE_DEFAULT_MODEL') or 'jev-1.13.0').strip()
        if model in {'jev-latest', 'jev-preview'}:
            model = 'jev-1.13.0'  # Fit thresholds/cache are validated against an exact release.
        if not re.fullmatch(r'jev-\d+\.\d+\.\d+', model):
            raise ValueError('Fit scoring requires an exact Jev model release.')
        base = str(values.get('TYPESAFE_BASE_URL') or 'https://api.typesafe.ai').strip().rstrip('/')
        if base != 'https://api.typesafe.ai':
            raise ValueError('Jev fit scoring requires the official Typesafe endpoint.')
        timeout = float(values.get('TYPESAFE_FIT_TIMEOUT') or 12)
        if not .1 <= timeout <= 60:
            raise ValueError('TYPESAFE_FIT_TIMEOUT must be between 0.1 and 60 seconds.')
        configured_path = values.get('TYPESAFE_FIT_CACHE_PATH')
        path = Path(configured_path) if configured_path else cache_path
        return cls(key=str(values.get('TYPESAFE_API_KEY') or '').strip(), model=model,
                   base_url=base, timeout=timeout,
                   cache_path=Path(path) if path else ROOT / '.cache' / 'jev-fit.sqlite3')

    def signature(self):
        files = ('settings.py', 'core.py', 'cache.py', 'transport.py', 'service.py', 'projection.py')
        code = {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() for name in files}
        for name in ('schemas.py', 'domain.py', 'resume_sources.py', 'resume_headers.py'):
            code[name] = hashlib.sha256((ROOT / 'job_agent' / name).read_bytes()).hexdigest()
        return digest([VERSION, self.model, self.base_url, self.timeout, self.ttl,
                       self.unknown_ttl, digest(self.key), code])


def database_cache_path(analysis_cache):
    sessions = getattr(analysis_cache, 'sessions', None)
    engine = getattr(sessions, 'kw', {}).get('bind')
    url = getattr(engine, 'url', None)
    if url is not None and url.drivername.startswith('sqlite') and url.database not in {None, '', ':memory:'}:
        return Path(url.database).resolve().with_suffix('.jev-fit.sqlite3')
    return None
