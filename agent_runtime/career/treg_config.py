"""Treg configuration: process environment > project-root .env > defaults (P4b).

Users configure their own Treg key; nothing is hosted or shared. Filling in a key never
enables a paid call by itself. Values are read into a mapping; os.environ is not modified.
An explicitly empty process variable means "not configured" and does not fall back to .env.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path

REPO_ENV = Path(__file__).resolve().parents[2] / '.env'
KEYS = ('TREG_TOKEN', 'TREG_ORG', 'JOB_AGENT_TREG_ENABLED', 'JOB_AGENT_JOB_API_FIRST',
        'JOB_AGENT_TREG_SEARCH_PROVIDER', 'JOB_AGENT_TREG_CRAWL4AI_SCRAPE_ENABLED',
        'JOB_AGENT_TREG_TASK_MAX_COST_USD', 'JOB_AGENT_TREG_DAILY_MAX_COST_USD', 'JOB_AGENT_TREG_MAX_ATTEMPTS',
        'JOB_AGENT_TREG_MAX_RESULTS', 'JOB_AGENT_TREG_MAX_PAGES', 'JOB_AGENT_TREG_MAX_CONCURRENCY',
        'JOB_AGENT_TREG_CALL_MAX_COST_USD', 'JOB_AGENT_TREG_LIVE_API_TEST')
DEFAULTS = {'JOB_AGENT_TREG_ENABLED': '0', 'JOB_AGENT_JOB_API_FIRST': '0', 'JOB_AGENT_TREG_SEARCH_PROVIDER': '',
            'JOB_AGENT_TREG_CRAWL4AI_SCRAPE_ENABLED': '0', 'JOB_AGENT_TREG_TASK_MAX_COST_USD': '0.10',
            'JOB_AGENT_TREG_DAILY_MAX_COST_USD': '0.50', 'JOB_AGENT_TREG_MAX_ATTEMPTS': '20',
            'JOB_AGENT_TREG_MAX_RESULTS': '10', 'JOB_AGENT_TREG_MAX_PAGES': '2', 'JOB_AGENT_TREG_MAX_CONCURRENCY': '2',
            'JOB_AGENT_TREG_CALL_MAX_COST_USD': '0.01', 'JOB_AGENT_TREG_LIVE_API_TEST': '0'}
PLACEHOLDERS = {'', 'changeme', 'your-treg-token', 'your_token_here', '<token>', 'xxx'}
PROVIDERS = {'anyapi', 'crawl4ai'}
MICRO = Decimal('1000000')


class TregConfigError(ValueError):
    """Invalid Treg settings block Treg only; other job sources keep working."""


@dataclass(frozen=True)
class TregConfig:
    token: str | None
    org: str | None
    enabled: bool
    api_first: bool
    search_provider: str | None
    scrape_enabled: bool
    task_max_micro: int
    daily_max_micro: int
    call_max_micro: int
    max_attempts: int
    max_results: int
    max_pages: int
    max_concurrency: int
    live_api_test: bool

    @property
    def configured(self):
        return bool(self.token)

    def usable(self):
        """Why Treg cannot be called, or None. Never includes the token."""
        if not self.enabled:
            return 'treg_disabled'
        if not self.configured:
            return 'treg_token_missing'
        return None

    def __repr__(self):  # never print the token
        return (f'TregConfig(configured={self.configured}, enabled={self.enabled}, api_first={self.api_first}, '
                f'search_provider={self.search_provider!r}, scrape_enabled={self.scrape_enabled})')


def _flag(value, name):
    text = str(value).strip().lower()
    if text in {'1', 'true', 'yes', 'on'}:
        return True
    if text in {'0', 'false', 'no', 'off', ''}:
        return False
    raise TregConfigError(f'{name} must be 0 or 1.')


def _usd_micro(value, name):
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        raise TregConfigError(f'{name} must be a decimal USD amount.') from None
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -6:
        raise TregConfigError(f'{name} must be a non-negative USD amount with at most 6 decimals.')
    return int(amount * MICRO)


def _count(value, name, low=1, high=1000):
    text = str(value).strip()
    if not text.isdigit() or not low <= int(text) <= high:
        raise TregConfigError(f'{name} must be an integer between {low} and {high}.')
    return int(text)


def settings(environ=None, env_path=REPO_ENV):
    """Resolved raw settings: environment wins, explicit empty environment wins too."""
    from dotenv import dotenv_values
    environment = os.environ if environ is None else environ
    try:
        file_values = dotenv_values(env_path) if Path(env_path).is_file() else {}
    except OSError:
        file_values = {}
    resolved = {}
    for key in KEYS:
        if key in environment:
            resolved[key] = environment[key]
        elif file_values.get(key) is not None:
            resolved[key] = file_values[key]
        else:
            resolved[key] = DEFAULTS.get(key, '')
    return resolved


def load(environ=None, env_path=REPO_ENV):
    raw = settings(environ, env_path)
    token = (raw['TREG_TOKEN'] or '').strip()
    provider = (raw['JOB_AGENT_TREG_SEARCH_PROVIDER'] or '').strip().lower() or None
    if provider is not None and provider not in PROVIDERS:
        raise TregConfigError('JOB_AGENT_TREG_SEARCH_PROVIDER must be anyapi or crawl4ai.')
    return TregConfig(
        token=None if token.lower() in PLACEHOLDERS else token,
        org=(raw['TREG_ORG'] or '').strip() or None,
        enabled=_flag(raw['JOB_AGENT_TREG_ENABLED'], 'JOB_AGENT_TREG_ENABLED'),
        api_first=_flag(raw['JOB_AGENT_JOB_API_FIRST'], 'JOB_AGENT_JOB_API_FIRST'),
        search_provider=provider,
        scrape_enabled=_flag(raw['JOB_AGENT_TREG_CRAWL4AI_SCRAPE_ENABLED'], 'JOB_AGENT_TREG_CRAWL4AI_SCRAPE_ENABLED'),
        task_max_micro=_usd_micro(raw['JOB_AGENT_TREG_TASK_MAX_COST_USD'], 'JOB_AGENT_TREG_TASK_MAX_COST_USD'),
        daily_max_micro=_usd_micro(raw['JOB_AGENT_TREG_DAILY_MAX_COST_USD'], 'JOB_AGENT_TREG_DAILY_MAX_COST_USD'),
        call_max_micro=_usd_micro(raw['JOB_AGENT_TREG_CALL_MAX_COST_USD'], 'JOB_AGENT_TREG_CALL_MAX_COST_USD'),
        max_attempts=_count(raw['JOB_AGENT_TREG_MAX_ATTEMPTS'], 'JOB_AGENT_TREG_MAX_ATTEMPTS'),
        max_results=_count(raw['JOB_AGENT_TREG_MAX_RESULTS'], 'JOB_AGENT_TREG_MAX_RESULTS', high=100),
        max_pages=_count(raw['JOB_AGENT_TREG_MAX_PAGES'], 'JOB_AGENT_TREG_MAX_PAGES', high=20),
        max_concurrency=_count(raw['JOB_AGENT_TREG_MAX_CONCURRENCY'], 'JOB_AGENT_TREG_MAX_CONCURRENCY', high=8),
        live_api_test=_flag(raw['JOB_AGENT_TREG_LIVE_API_TEST'], 'JOB_AGENT_TREG_LIVE_API_TEST'))
