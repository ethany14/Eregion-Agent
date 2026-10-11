"""Progress is a change in observed evidence, not a newly generated control token."""


def search_evidence(value):
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    from agent_runtime.career.alerts import job_key
    rows=[]
    for job in value.get('jobs',[]):
        url=job.get('url','')
        parts=urlsplit(url)
        query=urlencode([(key,v) for key,v in parse_qsl(parts.query) if key.lower() not in
            {'msockid','msclkid','gclid','fbclid'}])
        clean=urlunsplit(parts._replace(query=query,fragment=''))
        try:identity=job_key(clean)
        except ValueError:identity=clean
        row={'identity':identity}
        # A search-engine snippet's title/order is presentation. Actual board
        # metadata changes can still be new evidence about a candidate.
        if job.get('source')!='public_search':
            row.update({k:job[k] for k in ('title','company','location') if k in job})
        rows.append(row)
    return {'jobs':sorted(rows,key=lambda row:str(row)),**{k:value[k] for k in
        ('errors','sources_checked','skipped_sources','error','error_code') if k in value}}


def browser_evidence(value):
    if isinstance(value, list):
        return [browser_evidence(v) for v in value]
    if not isinstance(value, dict):
        return value
    if value.get('page_evidence_hash'):
        # SCAN's errors are a filtered view, like controls/text. Real alert
        # contents already participate in the unfiltered source hash. Keep
        # blocked explicitly: recovery may change it without changing DOM text.
        return {k:value[k] for k in ('url','frame_url','page_evidence_hash','blocked') if k in value}
    transient = {'observation_id', 'screenshot_id', 'ref', 'region_ref', 'image',
                 'progress_feedback', 'tabs', 'frames'}
    return {k: browser_evidence(v) for k, v in value.items() if k not in transient}
