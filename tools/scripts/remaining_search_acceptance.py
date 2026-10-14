"""Outcome/cost acceptance for the original paid search cases, also usable offline.

This checks deliverables, not merely whether the decision loop stopped. Unknown
metadata is a failed constraint, never inferred from the final model response.
"""
import math
import re

INPUT_LIMIT = 1_000_000
CALL_LIMIT = 60
US_STATES = 'al ak az ar ca co ct de fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj nm ny nc nd oh ok or pa ri sc sd tn tx ut vt va wa wv wi wy dc'.split()


def reply_job_scores(final):
    from eregion.runtime.career.reply_evidence import reply_job_scores as parse
    return parse(final)


def constraints(applicant, job):
    title = (job.get('title') or '').casefold()
    location = (job.get('location') or '').casefold()
    description = (job.get('description') or '').casefold()
    # The level belongs to this opening, not to colleagues the hire mentors.
    # A generic title without an explicit opening-level statement stays unknown.
    junior = bool(re.search(r'\b(junior|jr\.?|entry[- ]level|graduate)\b', title) or re.search(
        r'\b(?:entry[- ]level|junior)[ -]+(?:role|position|opportunity)\b|'
        r'\bthis (?:role|position) is (?:an? )?(?:entry[- ]level|junior)\b', description))
    for m in re.finditer(r'\b(?:seeking|hiring|recruiting|looking for)\s+(?:an?\s+)?(?:entry[- ]level|junior)\s+(?:professional|candidate|analyst|engineer|designer)\b',description):
        clause=re.split(r'[.!?\n]',description[:m.start()])[-1][-80:]
        if not re.search(r"\b(?:not|never|isn't|aren't|don't)\b",clause):junior=True
    low_ranges = re.finditer(
        r'(?:^|\n)\s*(?:[-*•]\s*)?'
        r'(?:(?:requires?|minimum(?: of)?|at least|must have|candidates? must have|you (?:have|bring)|'
        r'(?:the )?(?:ideal|successful) candidate (?:has|will have)|experience\s*:)\s+)?'
        r"(\d+)\s*[-–]\s*(\d+)\s+years?['’]?(?:\s+of)?\s+[^\n.;:!?]{0,80}?experience\b", description)
    junior = junior or any(0 <= int(m[1]) <= int(m[2]) <= 3 for m in low_ranges)
    minimum_years = re.finditer(
        r'\b(?:require[ds]?|minimum|at least|must have|you (?:have|bring))\s+(?:(?:at least|of)\s+)?(\d+)'
        r'(?:\s*[-–]\s*\d+)?\+?\s+years?\b|'
        r'\b(\d+)(?:\s*[-–]\s*\d+)?\+?\s+years? (?:of )?experience\s+(?:is )?required\b', description)
    if any(int(next(g for g in match.groups() if g is not None)) >= 4 for match in minimum_years):
        junior = False
    senior = bool(re.search(r'\b(senior|sr\.?)\b', title)) and not re.search(r'\b(staff|principal|director)\b', title)
    if applicant == 'backend':
        # An explicit City, US-state ZIP location is US evidence, too. A bare
        # "CA" or an employer office mentioned elsewhere is not sufficient.
        us_location = bool(re.search(r'\b(united states|usa|us|u\.s\.)\b', location) or re.search(
            r'\b[a-z][a-z .\'-]+,\s*(?:'+'|'.join(US_STATES)+r')\s+\d{5}(?:-\d{4})?\b', location))
        return {'role': bool(re.search(r'\bback[- ]?end\b', title)), 'seniority': bool(senior),
            'location': bool(re.search(r'\b(remote|fully remote|100% remote)\b', location)) and
                us_location}
    if applicant == 'analyst':
        ny_location=bool(re.search(r'\bnew york\b|\bnyc\b',location))
        if not ny_location and ' '.join(location.split()) in {'','remote','united states','united states (remote)','us remote'}:
            ny_location=any(re.search(r'\bnew york\b',m[1]) for m in re.finditer(
                r'(?m)^\s*(?:location\s*:|(?:this|the)\s+(?:role|position|job)\s+is\s+(?:based|located)\s+in)\s*([^\n.!?]{1,200})',description))
        return {'role': bool(re.search(r'\bdata analyst\b', title)), 'seniority': junior and
            not re.search(r'\b(senior|staff|principal|director)\b', title),
            'location': ny_location}
    if applicant == 'student':
        return {'role': bool(re.search(r'\b(machine learning|ml)\b', title)),
            'seniority': bool(re.search(r'\b(intern|internship)\b', title)),
            'location': bool(re.search(r'\b(california|ca|san francisco|mountain view|san jose|palo alto)\b', location))}
    if applicant == 'designer':
        return {'role': bool(re.search(r'\b(ux|user experience)\b', title)) and 'design' in title,
            'seniority': junior and not re.search(r'\b(senior|staff|principal|director)\b', title),
            'location': 'austin' in location}
    raise ValueError('Unknown original search case.')


def evaluate_search(summary, applicant, limits=None):
    from eregion.runtime.career.alerts import job_key
    failures = []
    def require(ok, reason):
        if not ok: failures.append(reason)
    require(summary.get('status') == 'completed' and not summary.get('error'), 'loop_not_completed_cleanly')
    require(0 < summary.get('calls', 0) <= CALL_LIMIT, 'main_call_budget')
    require(not summary.get('applications'), 'unexpected_application')
    require(not summary.get('schedules'), 'unexpected_schedule')
    usage = summary.get('usage') or {}
    require(usage.get('usage_complete') is True and not usage.get('pending') and
        usage.get('unknown_usage_calls') == 0, 'incomplete_usage')
    main_input = sum(g.get('input_tokens', 0) for g in usage.get('groups', []) if g.get('purpose') == 'agent')
    require(bool([g for g in usage.get('groups', []) if g.get('purpose') == 'agent']), 'missing_main_usage')
    # An explicitly recorded experiment profile may set the input cap; default unchanged.
    input_limit = (limits or {}).get('input_tokens', INPUT_LIMIT)
    require(main_input <= input_limit, 'main_input_budget')
    require(usage.get('input_tokens', input_limit + 1) <= input_limit, 'total_input_budget')
    if summary.get('qualification_method')=='model':
        audit=summary.get('audit_usage') or {}
        require(audit.get('usage_complete') is True and not audit.get('pending')
                and not audit.get('unknown_usage_calls') and audit.get('calls',7)<=6
                and audit.get('input_tokens',200001)<=200000
                and not summary.get('semantic_review_error'),'semantic_audit_incomplete')
    final = summary.get('final') or ''
    reply_scores = reply_job_scores(final)
    require('Send continue' not in final, 'budget_continuation')
    recommendations = {job_key(j['url']): j for j in summary.get('recommendations', []) if j.get('url')}
    if summary.get('acceptance_version') in {'tiered-recommendations-v2', 'tiered-recommendations-v3',
                                             'tiered-recommendations-v4', 'tiered-recommendations-v5'}:
        return _evaluate_v2(summary, recommendations, reply_scores, failures, require, main_input, usage, input_limit)
    seen, qualified, checked = set(), [], []
    for job in summary.get('verified_jobs', []):
        if summary.get('acceptance_version')=='tiered-recommendations-v1':
            from evals.tiered_audit import contract_checks as tiered_checks
            tests=tiered_checks(job,summary.get('semantic_review') or {},summary.get('user_request',''),
                                summary.get('audit_candidate_hash') or '')
        elif summary.get('qualification_method')=='model':
            from evals.search_semantic_audit import contract_checks
            tests=contract_checks(job,summary.get('semantic_review') or {},summary.get('user_request',''),
                                  summary.get('audit_candidate_hash') or '')
        else:
            # Historical report compatibility only; new live runs use blind model review.
            tests = constraints(applicant, job)
        score = job.get('match_score')
        tests['scored'] = type(score) in (int, float) and math.isfinite(score) and 0 <= score <= 100
        tests['retrieved'] = job.get('retrieved') is True
        url = job.get('url') or ''
        key = job_key(url) if url else ''
        rec = recommendations.get(key) or {}
        tests['recommended'] = bool(rec) and rec.get('match_score') == score
        tests['reply_url'] = bool(url) and url in final
        tests['reply_score'] = tests['scored'] and score in reply_scores.get(url, [])
        tests['eligible'] = not job.get('disqualified', False)
        tests['distinct'] = bool(key) and key not in seen
        seen.add(key)
        checked.append({'application_id': job.get('application_id'), 'url': url, 'title': job.get('title'),
            'location': job.get('location'), 'score': score, 'checks': tests})
        if all(tests.values()): qualified.append(key)
    require(len(qualified) >= 2, 'fewer_than_two_verified_scored_qualifying_recommendations')
    extra = {}
    if summary.get('acceptance_version') == 'tiered-recommendations-v1':
        review = summary.get('semantic_review') or {}
        counted = set(qualified)
        by_tier = {}
        for rec in recommendations.values():
            tier = rec.get('tier') or 'untiered'
            entry = by_tier.setdefault(tier, {'recommended': 0, 'counted': 0})
            entry['recommended'] += 1
            entry['counted'] += job_key(rec['url']) in counted
        disagreements = [{'url': rec['url'], 'production_tier': rec.get('tier'),
                          'audit_tier': (review.get(rec['url']) or {}).get('independent', {}).get('tier'),
                          'presentation': (review.get(rec['url']) or {}).get('presentation')}
                         for rec in recommendations.values()
                         if (review.get(rec['url']) or {}).get('independent', {}).get('tier') != rec.get('tier')]
        extra = {'acceptance_version': 'tiered-recommendations-v1', 'by_tier': by_tier, 'tier_disagreements': disagreements}
    return {'status': 'failed' if failures else 'passed', 'failures': failures, 'qualified_count': len(qualified), **extra,
        'main_input_tokens': main_input, 'total_input_tokens': usage.get('input_tokens'),
        'limits': {'main_calls': CALL_LIMIT, 'main_input_tokens': input_limit, 'total_input_tokens': input_limit},
        'jobs': checked}


def _evaluate_v2(summary, recommendations, reply_scores, failures, require, main_input, usage, input_limit):
    """tiered-recommendations-v2: no count threshold. Every shown job must be real, distinct,
    scored and free of substantive presentation errors; every scored job needs an outcome;
    the reply must explain results honestly. Counts and tier disagreements are reported."""
    from eregion.runtime.career.alerts import job_key
    from evals.tiered_audit import substantive_checks
    final = summary.get('final') or ''
    review = summary.get('semantic_review') or {}
    jobs = {job_key(j['url']): j for j in summary.get('verified_jobs', []) if j.get('url')}
    decided = set(summary.get('job_decisions') or {}) | {r.get('application_id') for r in recommendations.values()}
    undecided = [{'application_id': j.get('application_id'), 'url': j.get('url'), 'title': j.get('title')}
                 for j in jobs.values() if j.get('match_score') is not None and j.get('application_id') not in decided]
    require(not undecided, 'scored_jobs_without_outcome')
    reply = summary.get('reply_review') or {}
    require(bool(reply) and reply.get('explains_results_and_search') and not reply.get('hides_or_misreports_problems')
            and not reply.get('misstates_jobs'), 'final_reply_not_honest_or_unexplained')
    version = summary.get('acceptance_version')
    if version == 'tiered-recommendations-v3':
        # A clearly premature stop fails; a borderline one is an improvement suggestion only.
        require(reply.get('stop_assessment') != 'premature', 'search_stopped_prematurely')
    if version in {'tiered-recommendations-v4', 'tiered-recommendations-v5'}:
        # The stop itself is the model's choice and advisory here, unless the user asked for
        # an exhaustive search; what remains must be stated accurately with a way to continue.
        require(not (reply.get('user_asked_exhaustive') and reply.get('stop_assessment') == 'premature'),
                'search_stopped_prematurely')
        require(reply.get('continuation_stated', True) and reply.get('continuation_accurate', True),
                'continuation_missing_or_inaccurate')
    checked, clean, seen = [], [], set()
    for key, rec in recommendations.items():
        job = jobs.get(key) or {'url': rec['url']}
        tests = substantive_checks(job, review, summary.get('user_request', ''), summary.get('audit_candidate_hash') or '')
        score = job.get('match_score')
        tests['scored'] = type(score) in (int, float) and math.isfinite(score) and 0 <= score <= 100
        tests['retrieved'] = job.get('retrieved') is True
        tests['saved_score'] = rec.get('match_score') == score
        tests['tiered'] = rec.get('tier') in {'priority', 'stretch', 'to_confirm'}
        tests['reply_url'] = rec['url'] in final
        tests['reply_score'] = tests['scored'] and score in reply_scores.get(rec['url'], [])
        tests['eligible'] = not job.get('disqualified', False)
        tests['distinct'] = key not in seen
        seen.add(key)
        row = review.get(rec['url']) or {}
        checked.append({'application_id': rec.get('application_id'), 'url': rec['url'], 'title': rec.get('title'),
                        'tier': rec.get('tier'), 'audit_tier': (row.get('independent') or {}).get('tier'),
                        'score': score, 'checks': tests,
                        'minor_omissions': (row.get('presentation') or {}).get('minor_omissions', [])})
        if all(tests.values()):
            clean.append(key)
        else:
            failures.append('substantive_error:' + rec['url'])
    by_tier = {}
    for row in checked:
        entry = by_tier.setdefault(row['tier'] or 'untiered', {'shown': 0, 'clean': 0})
        entry['shown'] += 1
        entry['clean'] += job_key(row['url']) in clean
    disagreements = [{k: row[k] for k in ('url', 'tier', 'audit_tier')} for row in checked if row['audit_tier'] != row['tier']]
    return {'status': 'failed' if failures else 'passed', 'failures': failures,
            'acceptance_version': version, 'shown_count': len(checked), 'clean_count': len(clean),
            'by_tier': by_tier, 'tier_disagreements': disagreements, 'scored_without_outcome': undecided,
            'stop_assessment': reply.get('stop_assessment'), 'stop_review': reply.get('stop_review'),
            'improvement_suggestions': ([reply.get('stop_review')] if reply.get('stop_assessment') == 'borderline'
                                        or (version in {'tiered-recommendations-v4', 'tiered-recommendations-v5'} and reply.get('stop_assessment') == 'premature')
                                        else []),
            'reply_review': reply, 'main_input_tokens': main_input, 'total_input_tokens': usage.get('input_tokens'),
            'limits': {'main_calls': CALL_LIMIT, 'main_input_tokens': input_limit, 'total_input_tokens': input_limit},
            'jobs': checked}


def run_metrics(state, finished_at, workspace=None):
    """Report-only workload metrics for a live search (no thresholds)."""
    import json as _json
    from collections import Counter
    from datetime import datetime
    def when(value):
        return datetime.fromisoformat(value) if isinstance(value, str) else value
    start = when(state['created_at'])
    history = state.get('history') or []
    first = next((h for h in history if h.get('tool') == 'recommend_job' and isinstance(h.get('result'), dict)
                  and not h['result'].get('error') and not h['result'].get('already_recommended')), None)
    linkedin = state.get('linkedin_mcp_state') or {}
    log = linkedin.get('log') or []
    detail_reads = Counter(_json.dumps(r.get('arguments'), sort_keys=True) for r in log
                           if r.get('tool') == 'get_job_details' and r.get('outcome') == 'ok')
    context_reads = Counter(_json.dumps({'tool': h['tool'], 'arguments': h.get('arguments')}, sort_keys=True)
                            for h in history if h.get('tool') in {'read_context', 'inspect_job', 'read_job'})
    repeated_scoring = None
    if workspace is not None:
        # Two match reports for the same attached posting mean the same job was scored twice
        # (a new posting body attached in between is a legitimate rescore).
        repeated_scoring = 0
        for app in state.get('jobs', []):
            attached = sorted(e.occurred_at for e in workspace.list_events(app) if e.event_type.value == 'snapshot_attached')
            snapshots = Counter(max((t for t in attached if t <= a.created_at), default=None)
                                for a in workspace.list_artifacts(app) if a.artifact_type.value == 'match_report')
            repeated_scoring += sum(n - 1 for n in snapshots.values() if n > 1)
    return {'seconds_to_first_recommendation': round((when(first['at']) - start).total_seconds(), 1) if first else None,
            'total_seconds': round((when(finished_at) - start).total_seconds(), 1),
            'linkedin_calls': linkedin.get('calls_used', 0),
            'linkedin_searches': sum(r.get('tool') == 'search_jobs' for r in log),
            'linkedin_detail_reads': sum(detail_reads.values()),
            'repeated_linkedin_detail_reads': sum(n - 1 for n in detail_reads.values()),
            'repeated_context_reads': sum(n - 1 for n in context_reads.values()),
            'repeated_scoring': repeated_scoring,
            'tool_counts': dict(Counter(h.get('tool') for h in history))}


if __name__ == '__main__':
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    root = Path(sys.argv[1])
    for path in sorted(root.glob('*/summary.json')):
        summary = json.loads(path.read_text(encoding='utf-8'))
        state = json.loads(path.with_name('transcript.json').read_text(encoding='utf-8'))
        goal = state['goal'].casefold()
        applicant = next(k for k, phrase in [('analyst','junior data analyst'),('backend','senior backend'),
            ('student','machine learning internship'),('designer','junior ux designer')] if phrase in goal)
        from eregion.runtime.career.alerts import job_key
        retrieved = {job_key(j['url']) for j in state.get('retrieved_jobs', {}).values() if j.get('url')}
        summary['recommendations'] = state.get('recommendations', [])
        for job in summary.get('verified_jobs', []):
            job['retrieved'] = bool(job.get('url')) and job_key(job['url']) in retrieved
        result = evaluate_search(summary, applicant)
        result['source'] = str(path)
        # Never overwrite the old result: this records the strengthened audit separately.
        destination = path.with_name('outcome-audit-v2.json')
        if destination.exists(): raise FileExistsError(destination)
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'case': applicant, **{k: result[k] for k in
            ('status','failures','qualified_count','main_input_tokens','total_input_tokens')}}, ensure_ascii=True))
