"""Verified public board metadata; stale entries never enter automatic selection."""
import json
import os
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from agent_runtime.auto_apply.contracts import public_https_url

DIRECTORY = Path(__file__).with_name('board_directory.json')
MIN_FAMILY_TITLES = 2
FAMILIES = {
    'data/analytics': r'\b(data|analytics|analyst|business intelligence)\b',
    'backend': r'\b(backend|back.end|software|platform|infrastructure)\b',
    # Not bare "design": "Design Engineer" / "Design Verification" are engineering roles.
    'design': r'\b(ux|ui|user experience|(?:product|visual|interaction|graphic|ux|ui) design|designer)\b',
    'ML': r'\b(ml|machine learning|artificial intelligence|ai)\b',
}


class BoardEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    platform: Literal['greenhouse', 'lever', 'ashby', 'workday']
    company: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    host: str | None = None
    site: str | None = None
    display_name: str = Field(min_length=1)
    domains: list[str]
    locations: list[str]
    # Where each role family was actually observed on this board. Board-wide labels
    # alone let a company with data roles only in Paris match "data analyst, NYC".
    family_locations: dict[str, list[str]] | None = None
    source_url: str
    verified_at: date
    verified_by: Literal['public_api_get']
    job_count_at_verification: int = Field(ge=0, strict=True)
    notes: str

    @field_validator('source_url')
    @classmethod
    def public_url(cls, value):
        return public_https_url(value)

    @field_validator('domains', 'locations')
    @classmethod
    def nonempty(cls, values):
        if any(not v.strip() for v in values): raise ValueError('Empty coverage labels are invalid.')
        return values

    @model_validator(mode='after')
    def valid_board(self):
        if self.verified_at > datetime.now(UTC).date(): raise ValueError('Future verification date.')
        if self.platform == 'workday':
            if not re.fullmatch(re.escape(self.company) + r'\.wd\d+\.myworkdayjobs\.com', self.host or ''):
                raise ValueError('Invalid Workday tenant host.')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', self.site or ''): raise ValueError('Invalid Workday site.')
        return self


def load_directory(path=None):
    rows = json.loads(Path(path or DIRECTORY).read_text(encoding='utf-8'))
    if not isinstance(rows, list): raise ValueError('Directory must be an array.')
    entries = [BoardEntry.model_validate(row).model_dump(mode='json', exclude_none=True) for row in rows]
    from .discovery import board_source
    if len({board_source(row) for row in entries}) != len(entries): raise ValueError('Duplicate board.')
    return entries


def role_families(query):
    return {family for family, pattern in FAMILIES.items() if re.search(pattern, query, re.I)}


def location_covered(requested, observed):
    from .discovery import location_matches
    def normalize(s):
        s = s.casefold().strip()
        return {'nyc':'new york, ny', 'california':'ca', 'remote-us':'remote us',
                'remote, us':'remote us', 'austin':'austin, tx'}.get(s, s)
    requested, observed = normalize(requested), normalize(observed)
    if requested == 'remote us':
        return 'remote' in observed and bool(re.search(r'\b(united states|us|usa)\b', observed))
    if requested == 'ca': return bool(re.search(r'\bcalifornia\b|(?:^|,)\s*ca(?:,|$)', observed))
    return not requested or location_matches(requested, observed)


def select_boards(query, location='', *, entries=None, today=None, max_age=None):
    from .discovery import board_source
    today = today or datetime.now(UTC).date()
    max_age = max(0, int(os.getenv('JOB_AGENT_BOARD_DIRECTORY_MAX_AGE_DAYS', '30'))) if max_age is None else max_age
    selected, stale = [], []
    for row in load_directory() if entries is None else entries:
        families = role_families(query).intersection(row['domains'])
        if not families: continue
        coverage = row.get('family_locations')
        places = [p for f in families for p in coverage.get(f, [])] if coverage else row['locations']
        matching = sum(location_covered(location, place) for place in places)
        if not matching: continue
        if (today - date.fromisoformat(row['verified_at'])).days > max_age:
            stale.append(board_source(row))
        else: selected.append((matching, row))
    # Search fans out to the first few boards only: most matching family/location
    # observations first, not alphabetical order. Ties keep directory order.
    selected.sort(key=lambda item: -item[0])
    return [row for _, row in selected], stale


def api_url(board):
    platform, company = board['platform'], board['company']
    if platform == 'greenhouse': return f'https://boards-api.greenhouse.io/v1/boards/{company}/jobs'
    if platform == 'lever': return f'https://api.lever.co/v0/postings/{company}?mode=json'
    if platform == 'ashby': return f'https://api.ashbyhq.com/posting-api/job-board/{company}'
    # Workday search requires POST. Never claim that a GET verified its listing.
    raise ValueError('Workday listing verification requires POST; public_api_get cannot certify it.')


def verify(board, discovery):
    body, _ = discovery.read(api_url(board))
    payload = json.loads(body)
    jobs = payload if board['platform'] == 'lever' else payload['jobs']
    if not isinstance(jobs, list): raise ValueError('Expected board job array.')
    locations, counts, family_places = set(), {}, {}
    for job in jobs:
        title = job.get('text', '') if board['platform'] == 'lever' else job.get('title', '')
        place = job.get('categories', {}).get('location', '') if board['platform'] == 'lever' else job.get('location', '')
        if isinstance(place, dict): place = place.get('name', '')
        if place: locations.add(place)
        for family in role_families(title):
            counts[family] = counts.get(family, 0) + 1
            if place: family_places.setdefault(family, set()).add(place)
    # A single incidental title ("Data Center Technician") is not role-family coverage.
    families = sorted(f for f, n in counts.items() if n >= MIN_FAMILY_TITLES)
    return {**board, 'verified_at': datetime.now(UTC).date().isoformat(), 'verified_by':'public_api_get',
            'job_count_at_verification':len(jobs), 'domains':families, 'locations':sorted(locations),
            'family_locations':{f: sorted(family_places.get(f, ())) for f in families}}
