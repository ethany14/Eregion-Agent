"""Map Jev evidence decisions into existing application contracts without guessing."""
import re
from job_agent.schemas import (ResumeAnalysis, ResumeEvidence, ResumeSourceEntry,
    JobAnalysis, JobRequirement, SkillMatch, SkillEvidence, ScoreBreakdown, MissingRequirement)
from job_agent.domain import normalize_resume_analysis, validate_resume_source_metadata
from job_agent.resume_sources import complete_source_evidence
from .core import expected_score, resume_blocks
from .settings import digest


def resume_projection(text):
    """Preserve exact source spans and common inline/wrapped entry headers."""
    from job_agent.resume_layout import entry_spans
    evidence,entries,education=[],[],[]
    kinds={'summary':'summary','profile':'summary','education':'education','教育':'education',
           'experience':'experience','employment':'experience','work experience':'experience',
           'professional experience':'experience','工作经历':'experience','project':'project',
           'projects':'project','项目经历':'project','skills':'skills','technical skills':'skills','技能':'skills'}
    blocks = []
    for section in resume_blocks(text):
        lines = list(re.finditer(r'(?m)^.*$', section['text']))
        label = lines[0].group().strip().rstrip(':')
        kind = kinds.get(label.casefold(), 'other')
        if kind in {'experience', 'project', 'education'}:
            offset = section['text'].find('\n') + 1
            body = section['text'][offset:]
            for a, b, metadata in entry_spans(body, kind):
                blocks.append({'text': body[a:b], 'start': section['start']+offset+a,
                               'label': label, 'kind': kind, 'metadata': metadata})
        else:
            blocks.append({**section, 'label': label, 'kind': kind})
    for block in blocks:
        lines=[line.strip()for line in block['text'].splitlines()if line.strip()]
        label, kind = block['label'], block['kind']
        metadata=block.get('metadata',{})
        if kind=='skills':metadata={'heading':label}
        if not block['text'].strip():continue
        identifier='jev-source-'+digest([block['start'],block['text']])[:16]
        eid=identifier+'-evidence'
        evidence.append(ResumeEvidence(evidence_id=eid,source_entry_id=identifier,
            source_section=label if kind!='other' else 'Resume',exact_text=block['text']))
        entries.append(ResumeSourceEntry(source_entry_id=identifier,entry_type=kind,
            **metadata,evidence_ids=[eid]))
        if kind=='education':education.append(block['text'])
    analysis=ResumeAnalysis(summary='',skills=[],education=education,evidence=evidence,source_entries=entries)
    analysis=normalize_resume_analysis(complete_source_evidence(analysis,text))
    validate_resume_source_metadata(analysis,text)
    return analysis


def project(raw, resume_text, job_text, *, model, expires_at):
    requirements=[]
    matches=[]
    for m in raw['matches']:
        conditional=m['status']in {'needs_confirmation','confirmed_condition'}
        r=JobRequirement(requirement_id=m['requirement_id'],requirement_group_id=m['requirement_id'],
            canonical_name=m['text'],display_name=m['text'],original_text=m['text'],source_text=m['text'],
            atomic_text=m['text'],category='eligibility' if conditional else 'other',
            verification_mode='user_confirmation' if conditional else 'resume_evidence',level=m['level'])
        requirements.append(r)
        probabilities=[a['noul']for a in (m.get('full_support'),m.get('related_evidence'),m.get('requires_confirmation'))if a]
        confidence=min((max(p,1-p)for p in probabilities),default=0)
        reason=m['reason']
        if m['status']=='unknown':reason='Jev was not decisive about this requirement; it counts by its probability of being met.'
        elif m['status']=='confirmed_condition':reason='The supplied personal condition is satisfied.' if m['condition_satisfied'] else 'The supplied personal condition is not satisfied.'
        matches.append(SkillEvidence(requirement_id=r.requirement_id,job_skill=r.display_name,
            requirement_level=r.level,match_status=m['status'],match_reason=reason,
            condition_satisfied=m.get('condition_satisfied'),confidence=confidence,
            resume_evidence=[c['exact_text']for c in m['citations']]))
    by_id={r.requirement_id:r for r in requirements}
    missing=lambda level:[MissingRequirement(canonical_name=m.job_skill,original_text=by_id[m.requirement_id].original_text)
        for m in matches if m.requirement_level==level and m.match_status in {'missing','partial'}]
    total=raw['score']
    groups={level:expected_score([m for m in raw['matches']if m['level']==level])['score']for level in ('required','preferred')}
    resolved=sum(m.get('resolved_by')=='main_model' for m in raw['matches'])
    explanation=(f'Evidence-based Jev alignment. Each requirement counts by its probability of being met (certainty {raw.get("certainty",0):.0%}). Personal conditions are reported separately.'
        +(f' {resolved} requirement(s) Jev could not decide were resolved by the main model with quoted evidence.' if resolved else ''))
    match=SkillMatch(matches=matches,explanation=explanation,
        recommendations=['Review unresolved requirements and personal conditions before applying.']if any(m.match_status in {'unknown','needs_confirmation'}for m in matches)else [],
        missing_required_requirements=missing('required'),missing_preferred_requirements=missing('preferred'),
        confirmation_requirements=[r for r in requirements if next(m for m in matches if m.requirement_id==r.requirement_id).match_status=='needs_confirmation'],
        overall_score=total,score_breakdown=ScoreBreakdown(overall_score=total,required_score=groups['required'],preferred_score=groups['preferred']),
        score_range=raw['score_range'],analysis_status=raw['status'],algorithm='jev-only',valid_until=expires_at,
        decision_details={'model':model,'resume_sha256':raw['resume_sha256'],'jd_sha256':raw['jd_sha256'],
          'extraction':[{'id':u['id'],'start':u['start'],'end':u['end'],'classification':u['classification']}for u in raw['extraction']],
          'decisions':[{'requirement_id':m['requirement_id'],'initial':m['initial_decisions'],'focused':m['focused_decisions'],
                       'clarified_full_support':m.get('clarified_full_support'),
                       'resolved_by':m.get('resolved_by','jev'),
                       'citation_scope':m.get('citation_scope'),'citation_verification':m.get('citation_verification'),
                       'citations':[{'sha256':c['sha256'],'spans':c['spans']}for c in m['citations']]}for m in raw['matches']]})
    # A title cannot be inferred safely from an arbitrary first line of a JD.
    job=JobAnalysis(title=None,summary='',requirements=requirements,responsibilities=[])
    return resume_projection(resume_text),job,match
