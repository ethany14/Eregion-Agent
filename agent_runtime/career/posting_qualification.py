"""Conservative rejection of explicitly non-vacancy recruiting pages."""
import re


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
    text=job.get('description','')
    network=r'talent\s+(?:network|community|pool)'
    network_application=re.search(r'\b(?:apply|register|sign up|submit)\b[^.!?\n]{0,140}\b'+network,text,re.I)
    placements=re.search(r'\bprogram\s+(?:places|connects)\s+[^.!?\n]{0,100}\b(?:roles|employers)\b',text,re.I)
    explicit_non_vacancy=re.search(r'\b(?:not (?:a |an? actual |an? current )?(?:vacancy|job opening|open position)|future opportunities|expression of interest)\b',text,re.I)
    # A second, optional network CTA must not negate a concrete role's own
    # application. Both a role-specific action and opening evidence are needed.
    target_application=re.search(r'\bapply\s+(?:for|to)\s+(?:this|the)\s+(?:role|position|job|vacancy)\b',text,re.I)
    concrete=re.search(r'\b(?:we are hiring|this (?:full[- ]time |part[- ]time )?(?:position|role)|requisition\s+[A-Za-z0-9-]+)\b',text,re.I)
    if (network_application or placements or (explicit_non_vacancy and re.search(network,text,re.I))) and not (target_application and concrete):
        raise PostingRejected('This is a talent network/program or future-opportunity page, not evidence of a specific current vacancy. Find an identifiable current posting; do not import, score or recommend this page as an open job.',code='not_current_vacancy')
    if re.fullmatch(r'\s*(?:job description|job details|careers?|opportunities|current opportunities|overview)\s*',job.get('title',''),re.I):
        raise PostingRejected('The captured title is a generic page label, not a verified posting identity. Locate the target role heading in its own detail region; model-supplied import metadata cannot establish the title.',code='unverified_title')
    return job
