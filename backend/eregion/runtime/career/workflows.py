"""Optional orchestration only; the granular handlers own all business effects."""
from eregion.runtime.tasks.loop import TEXT, function
from eregion.runtime.provider_usage import TaskProviderBudgetExceeded
from .alerts import job_key

TOOL = function('verify_and_score',
    'Read or reuse one saved posting, qualify, import and score it. Never recommends. '
    'On failure inspect completed_steps and use the indicated granular fallback.',
    {k: TEXT for k in ('url', 'region_ref', 'observation_id', 'message_id',
                      'job_text', 'title', 'company', 'location')}, ['url'])
RULE = ('\nFor a promising observed posting use verify_and_score to read, import and score in one call; '
        'do not first page through its complete archived JD. Decide recommend_job separately from its actual score '
        'and qualification evidence. For a posting already read, use verify_and_score to reuse it, or '
        'dismiss_candidate with an exact source quote and reason if unsuitable. Finish started candidates before '
        'searching again. A progress message or plan is not completed candidate work.\n')
FALLBACK = 'Use read_job, import_job, then score_job individually; inspect saved progress first.'


def run(harness, task_id, args, call_id):
    repo = harness.repository
    state = repo.get(task_id)
    key = harness.key(state, 'verify_and_score', {**args, 'url': job_key(args['url'])})
    record = dict(state.get('verification_workflows', {}).get(key, {}))
    completed = list(record.get('completed_steps', []))
    initial_analyses = state.get('analyses', {}).copy()

    def save(**changes):
        record.update(changes, completed_steps=list(completed))
        repo.change(task_id, lambda s: {'verification_workflows': {
            **s.get('verification_workflows', {}), key: dict(record)}})

    def step(name, arguments):
        order = ('read_job', 'import_job', 'score_job')
        # A revalidation can fail after inputs change. Do not describe a prior
        # score as completed for the current attempt; domain caches own reuse.
        completed[:] = [s for s in completed if order.index(s) < order.index(name)]
        save(pending_step=name)  # Intent before the existing handler's effects.
        from eregion.runtime.provider_usage import usage_scope
        with usage_scope(purpose=name):
            result = harness.execute(task_id, name, arguments, call_id=f'{call_id}:{name}')
        if result.get('error'):
            detail = {'completed_steps': list(completed), 'failed_step': name}
            if result.get('error_code') not in {'candidate_rejected', 'source_blocked'}:
                detail['fallback'] = FALLBACK
            save(failure=detail)
            result = {**result, **detail}
            return result
        if name not in completed:
            completed.append(name)
        save(pending_step=None, **({'retrieved_job': result} if name == 'read_job' else {}))
        return result

    current = 'read_job'
    try:
        saved = next((j for j in state.get('retrieved_jobs', {}).values()
                      if j.get('url') and job_key(j['url']) == job_key(args['url'])
                      and j.get('description')), None)
        if not saved and record.get('retrieved_job'):
            saved = record['retrieved_job']
            repo.change(task_id, lambda s: {'retrieved_jobs': dict(list({
                **s.get('retrieved_jobs', {}), saved['url']: saved}.items())[-20:])})
        if not saved and not args.get('job_text'):
            saved = step('read_job', {k: v for k, v in args.items()
                                    if k in ('url', 'region_ref', 'observation_id')})
            if saved.get('error'):
                return {**saved, 'completed_steps': completed, 'failed_step': current}
        elif saved and 'read_job' not in completed:
            completed.append('read_job')
            save(pending_step=None, retrieved_job=saved)
        # Import re-runs the shared candidate preflight and posting qualification,
        # even on resume. Workspace source/snapshot identity deduplicates effects.
        current = 'import_job'
        imported = step(current, {k: v for k, v in args.items()
                                 if k not in ('region_ref', 'observation_id')})
        if imported.get('error'):
            return {**imported, 'completed_steps': completed, 'failed_step': current}
        save(application_id=imported['application_id'])
        current = 'score_job'
        before_score = harness.job_summary(imported['application_id'], detail=True)
        result = step(current, {'application_id': imported['application_id']})
        if result.get('error'):
            return {**result, 'completed_steps': completed, 'failed_step': current}
        from .search_policy import opening_level
        result = {**result, 'completed_steps': completed,
                  'opening_level': opening_level(result.get('description', ''))}
        if (saved and imported['application_id'] in state.get('jobs', [])
                and initial_analyses == repo.get(task_id).get('analyses', {})
                and all(result.get(k) == before_score.get(k) for k in before_score if k != 'result_at')):
            result['no_new_evidence'] = True
        save(finished=True, failure=None)
        return result
    except TaskProviderBudgetExceeded as exc:
        detail = {'completed_steps': completed, 'failed_step': current}
        save(failure={**detail, 'reason': exc.reason})
        exc.workflow_detail = detail
        raise
    except Exception as exc:
        from .posting_qualification import PostingRejected
        from .source_health import SourceBlocked
        detail = {'completed_steps': completed, 'failed_step': current}
        if not isinstance(exc, (PostingRejected, SourceBlocked)):
            detail['fallback'] = FALLBACK
        save(failure={**detail, 'type': type(exc).__name__})
        exc.workflow_detail = detail
        raise
