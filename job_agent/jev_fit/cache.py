"""Persistent validated Jev decisions; hashes and answers, no raw documents."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import time
from .core import boolean, validate_answers
from .settings import digest, canonical
CACHE_SCHEMA = 1
_initialized, _initialized_lock = set(), threading.Lock()

class DecisionCache:
    """Atomic local cache. Stores hashes, validated answers and provenance only.

    Unknown is a valid outcome, cached briefly instead of silently becoming yes.
    Expired, corrupt, partial and wrong-version entries are treated as misses.
    """
    def __init__(self, path, *, ttl=86400, unknown_ttl=300, clock=None):
        self.path, self.ttl, self.unknown_ttl, self.clock = Path(path), ttl, unknown_ttl, clock or time.time
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Switching to WAL needs exclusive access and SQLite does not wait for it, so
        # concurrent first analyses on a new file raised "database is locked". WAL is
        # a persistent file setting: switch it once per file per process, under a lock.
        key = str(self.path.resolve())
        with _initialized_lock:
            with self.connect() as db:
                if key not in _initialized:
                    try:
                        db.execute('PRAGMA journal_mode=WAL')
                        _initialized.add(key)
                    except sqlite3.OperationalError:
                        pass  # Another process holds the file; retry on the next init.
                db.execute('CREATE TABLE IF NOT EXISTS decisions (key TEXT PRIMARY KEY, body TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.execute('PRAGMA busy_timeout=15000')
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, key, model):
        return self.get_many([key], model).get(key)

    def get_many(self, keys, model):
        found = {}
        try:
            with self.connect() as db:
                for key in dict.fromkeys(keys):
                    row = db.execute('SELECT body FROM decisions WHERE key=?', (key,)).fetchone()
                    if row is None:
                        continue
                    try:
                        body = json.loads(row[0])
                        checksum = body.pop('checksum')
                        if checksum != digest(body) or body['key'] != key or body['schema'] != CACHE_SCHEMA:
                            continue
                        if body['model'] != model or not body['created_at'] <= self.clock() < body['expires_at']:
                            continue
                        validate_answers({'model': model, 'answers': {'q': body['answer']}}, {'q': {'type': 'noul'}})
                        found[key] = body
                    except (ValueError, TypeError, KeyError, AttributeError):
                        continue
        except sqlite3.DatabaseError:
            return {}
        return found

    def put(self, key, model, answer, provenance):
        self.put_many([(key, answer, provenance)], model)

    def put_many(self, entries, model):
        now = self.clock()
        rows = []
        for key, answer, provenance in entries:
            validate_answers({'model': model, 'answers': {'q': answer}}, {'q': {'type': 'noul'}})
            body = {'schema': CACHE_SCHEMA, 'key': key, 'model': model,
                    'created_at': now, 'expires_at': now + (self.unknown_ttl if boolean(answer) is None else self.ttl),
                    'answer': answer, 'provenance': provenance}
            body['checksum'] = digest(body)
            rows.append((key, canonical(body)))
        with self.connect() as db:
            db.executemany('INSERT OR REPLACE INTO decisions VALUES (?,?)', rows)

