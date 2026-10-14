"""Disposition of scored jobs (closeout C1): pending, recommended, excluded, needs evidence.

A scored job is not a recommendation and not an exclusion. Each one needs an explicit,
traceable outcome bound to the current user request and score version; new evidence,
a changed score or a new user request reopens it.
"""
from eregion.runtime.tasks.loop import TEXT, function

APP = {'application_id': TEXT}
# Kept short: it is sent on every request. The rules live in known_results.instruction.
TOOL = function('decide_job',
    'Outcome for a scored job not presented as an opportunity: exclude (a hard qualification the user explicitly does '
    'not meet, closed, duplicate, clearly unrelated, or violating the stated location/level) or needs_evidence (the '
    'posting itself is too unclear to present). Unknown personal facts are a to_confirm recommendation, not this.',
    {**APP, 'decision': {'type': 'string', 'enum': ['exclude', 'needs_evidence']}, 'reason': TEXT, 'missing': TEXT},
    ['application_id', 'decision', 'reason'])
DISCOVERY = {'search_jobs', 'screen_jobs'}


def binding(state, application_id):
    """A decision holds only for this user request and this score."""
    return [state.get('chat_revision'), (state.get('analyses') or {}).get(application_id)]


def statuses(state):
    # decision_status, not status: the archive treats a status field as a live resource.
    recommended = {r.get('application_id') for r in state.get('recommendations', [])}
    decided = state.get('job_decisions') or {}
    rows = {}
    for app, evidence in (state.get('scored_job_evidence') or {}).items():
        if app in recommended:
            rows[app] = {'decision_status': 'recommended'}
            continue
        record = decided.get(app)
        if record and record.get('binding') == binding(state, app):
            rows[app] = {'decision_status': 'excluded' if record['decision'] == 'exclude' else 'needs_evidence',
                         'reason': record['reason'], **({'missing': record['missing']} if record.get('missing') else {})}
        else:
            rows[app] = {'decision_status': 'pending', **({'reopened': True} if record else {})}
    return rows


def pending(state):
    return [app for app, row in statuses(state).items() if row['decision_status'] == 'pending']


def decide(repository, task_id, state, args):
    app = args['application_id']
    if app not in (state.get('scored_job_evidence') or {}):
        raise ValueError('Only a job scored in this conversation can be decided.')
    if any(r.get('application_id') == app for r in state.get('recommendations', [])):
        raise ValueError('This job is already recommended.')
    if args.get('decision') not in {'exclude', 'needs_evidence'}:
        raise ValueError('decision must be exclude or needs_evidence.')
    reason = args.get('reason')
    if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 1000:
        raise ValueError('Give a specific reason (one or two sentences).')
    if args['decision'] == 'needs_evidence' and not (args.get('missing') or '').strip():
        raise ValueError('needs_evidence requires what is missing.')
    record = {'decision': args['decision'], 'reason': reason.strip()[:1000],
              'missing': (args.get('missing') or '').strip()[:500] or None, 'binding': binding(state, app)}
    repository.change(task_id, lambda s: {'job_decisions': {**(s.get('job_decisions') or {}), app: record}})
    return {'decided': True, 'application_id': app, 'decision': args['decision']}


def gate(state, name, args):
    """Discovery waits until every scored job in this request has an outcome."""
    open_jobs = pending(state)
    if name not in DISCOVERY or not open_jobs:
        return None
    evidence = state.get('scored_job_evidence') or {}
    return {'error': 'Decide the scored jobs before searching for more.', 'error_code': 'pending_decisions',
            'no_new_evidence': True,
            'pending': [{k: evidence[a].get(k) for k in ('application_id', 'title', 'company', 'url', 'match_score',
                         'qualification_evidence','decision_brief') if k in evidence[a]} for a in open_jobs],
            'next': 'For each pending job call recommend_job (with caveats) or decide_job (exclude with the specific '
                    'reason, or needs_evidence with what is missing). Then search again for remaining gaps.'}


def terminal_delivery(state):
    """Saved results for a stop without a model reply (no model call)."""
    evidence = state.get('scored_job_evidence') or {}
    lines = []
    for r in state.get('recommendations', []):
        label = r.get('tier_label') or 'Recommended'
        lines.append(f"- {label}: {r.get('title')} — {r.get('company') or 'company not stated'} — "
                     f"{r.get('url')} — score {r.get('match_score')}")
    for app, row in statuses(state).items():
        if row['decision_status'] == 'recommended':
            continue
        e = evidence.get(app, {})
        label = {'pending': 'Scored, not yet decided', 'excluded': 'Scored, excluded',
                 'needs_evidence': 'Scored, needs evidence'}[row['decision_status']]
        detail = f" ({row['reason']})" if row.get('reason') else ''
        lines.append(f"- {label}: {e.get('title')} — {e.get('url')} — score {e.get('match_score')}{detail}")
    return lines
