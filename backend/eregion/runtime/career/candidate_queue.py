"""Bounded candidate batches (default on for API-first; explicit flag overrides).

A query view over existing state (search candidates, read bodies, imported jobs, scores,
decisions, rejections); it stores no second copy of any status. Work already started is
finished before more discovery; unread candidates are offered a few at a time; the rest
stay deferred, never silently dropped. Formal read → qualify → import → score → decide
steps are unchanged.
"""
import os

from .alerts import job_key

BATCH_LIMIT = 20
DETAIL_LIMIT = 20


def enabled():
    from .treg_config import settings
    default = str(settings()['JOB_AGENT_JOB_API_FIRST']).strip().lower() in {'1','true','yes','on'}
    return os.getenv('JOB_AGENT_OPT_CANDIDATE_BATCHES', '1' if default else '0') == '1'


def view(state, recovery):
    from .decisions import statuses
    if not recovery:
        return None
    decided = statuses(state)
    evidence = state.get('scored_job_evidence') or {}
    scored_keys = {job_key(e['url']) for e in evidence.values() if e.get('url')}
    in_progress = []
    for item in recovery.get('read_not_imported', []):
        in_progress.append({'stage': 'import', 'url': item['url'], 'title': item.get('title'),
                            'next': {'tool': 'verify_and_score or import_job', 'arguments': {'url': item['url']}},
                            'alternative': 'dismiss_candidate with an exact source quote and reason if unsuitable'})
    for app in state.get('jobs', []):
        if app in evidence:
            continue
        if any(q.get('application_id')==app and q.get('revision')==state.get('chat_revision',0)
               and not q['qualified'] for q in state.get('candidate_qualifications',{}).values()):
            continue
        in_progress.append({'stage': 'score', 'application_id': app,
                            'next': {'tool': 'score_job', 'arguments': {'application_id': app}}})
    for app, row in decided.items():
        if row['decision_status'] == 'pending':
            e = evidence.get(app, {})
            in_progress.append({'stage': 'decide', 'application_id': app, 'title': e.get('title'),
                                'match_score': e.get('match_score'),
                                'next': {'tool': 'recommend_job or decide_job', 'arguments': {'application_id': app}}})
    unread = [c for c in recovery.get('pending_candidates', []) if job_key(c['url']) not in scored_keys]
    batch = unread[:BATCH_LIMIT]
    qualified = [r for r in state.get('recommendations', []) if not r.get('seniority_warning')]
    from .qualification import assess
    bodies = {job_key(j['url']): j for j in state.get('retrieved_jobs', {}).values() if j.get('url')}
    if enabled():
        qualified = [r for r in qualified if job_key(r.get('url', '')) in bodies
                     and assess(state, bodies[job_key(r['url'])])['qualified']]
    target = recovery.get('requested_count') or 0
    reached = bool(target) and len(qualified) >= target
    return {'batch_limit': BATCH_LIMIT, 'detail_limit': DETAIL_LIMIT, 'requested': target,
            'recommended_without_level_warning': len(qualified), 'target_reached': reached,
            'in_progress': in_progress[:DETAIL_LIMIT * 2], 'next_unread': batch[:DETAIL_LIMIT],
            'deferred_unread': max(0, len(unread) - DETAIL_LIMIT),
            'instruction': ('Target reached: finish with the saved results.' if reached else
                            'Finish in_progress items first, then process next_unread URLs with verify_and_score_jobs in a bounded batch. '
                            'Search again only when nothing actionable remains; deferred candidates are kept.')}


def gate(state, recovery, name):
    """Discovery waits while already-started candidate work is unfinished (decisions have their own gate)."""
    if not enabled() or name not in {'search_jobs', 'screen_jobs'}:
        return None
    current = view(state, recovery)
    started = [i for i in (current or {}).get('in_progress', []) if i['stage'] in {'import', 'score'}]
    if not started:
        return None
    return {'error': 'Finish the candidates already in progress before searching for more.',
            'error_code': 'candidates_in_progress', 'no_new_evidence': True, 'in_progress': started,
            'next': 'Use verify_and_score on read postings, or dismiss_candidate with source evidence; score imported jobs and decide them before more discovery.'}
