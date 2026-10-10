"""Progress is a change in observed evidence, not a newly generated control token."""


def browser_evidence(value):
    if isinstance(value, list):
        return [browser_evidence(v) for v in value]
    if not isinstance(value, dict):
        return value
    transient = {'observation_id', 'screenshot_id', 'ref', 'region_ref', 'image',
                 'progress_feedback', 'tabs', 'frames'}
    return {k: browser_evidence(v) for k, v in value.items() if k not in transient}
