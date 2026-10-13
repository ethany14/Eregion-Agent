"""Posting identity shape checks; vacancy meaning belongs to the model."""


class PostingRejected(ValueError):
    """A source-backed exclusion, distinct from an unread/ambiguous page."""
    def __init__(self, reason, *, code):
        super().__init__(reason)
        self.code=code
        self.evidence={}
        self.repeated=False

    def outcome(self):
        return {'error':str(self),'error_code':'candidate_rejected','rejection_code':self.code,
            **self.evidence,'no_new_evidence':self.repeated,
            'next':'Exclude this unchanged candidate for this user turn. Use another posting/source. Recheck only after observed source changes or new user input.'}


def validate_posting(job):
    if not str(job.get('title') or '').strip():
        raise PostingRejected('The source has no captured posting title.',code='unverified_title')
    return job
