"""Bounded candidate batches (P3, JOB_AGENT_OPT_CANDIDATE_BATCHES, default off).

A query view over existing state (search candidates, read bodies, imported jobs, scores,
decisions, rejections); it stores no second copy of any status. Work already started is
finished before more discovery; unread candidates are offered a few at a time; the rest
stay deferred, never silently dropped. Formal read → qualify → import → score → decide
steps are unchanged.
"""
import os

from .alerts import job_key

BATCH_LIMIT = 10
DETAIL_LIMIT = 5


def enabled():
    return os.getenv('JOB_AGENT_OPT_CANDIDATE_BATCHES', '0') == '1'


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
                            'next': {'tool': 'import_job', 'arguments': {'url': item['url']}}})
    for app in state.get('jobs', []):
        if app in evidence:
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
    target = recovery.get('requested_count') or 0
    reached = bool(target) and len(qualified) >= target
    return {'batch_limit': BATCH_LIMIT, 'detail_limit': DETAIL_LIMIT, 'requested': target,
            'recommended_without_level_warning': len(qualified), 'target_reached': reached,
            'in_progress': in_progress[:DETAIL_LIMIT * 2], 'next_unread': batch[:DETAIL_LIMIT],
            'deferred_unread': max(0, len(unread) - DETAIL_LIMIT),
            'instruction': ('Target reached: finish with the saved results.' if reached else
                            'Finish in_progress items first, then read next_unread candidates one at a time. '
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
            'next': 'Import read postings and score imported jobs (or decide them), then search for remaining gaps.'}
