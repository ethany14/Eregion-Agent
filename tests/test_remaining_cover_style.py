"""E5 effective writer/reviser policy; grounding remains independently enforced."""
import json
import os
import re
from pathlib import Path
from time import monotonic
import pytest
from test_career_flow import career,execute
from evals.cover_style_review import screens


@pytest.mark.parametrize('revise',[False,True])
def test_cover_letter_generation_and_revision_receive_specific_natural_opening_rules(monkeypatch,revise):
    import eregion.runtime.application_pack.workflow as module
    calls=[]
    monkeypatch.setattr(module,'shared_model',lambda:object())
    def invoke(model,schema,system,context):
        calls.append((schema,system,context));return 'synthetic structured artifact'
    monkeypatch.setattr(module,'invoke_structured',invoke)
    client=module.SharedPackModel()
    context='{"verified_job":"Python Engineer at Example: improve API reliability"}'
    result=client.revise_blocks('cover_letter',context) if revise else client.cover_letter(context)
    assert result=='synthetic structured artifact'
    schema,system,actual=calls[0]
    assert schema.__name__=='CoverLetter' and actual==context
    assert "specific role and the company's stated problem or need" in system
    assert 'only when verified' in system and "'This letter addresses'" in system
    assert 'Never invent company values' in system
    assert 'Cite the evidence ID, evidence version ID' in system
    assert "candidate evidence alone" in system
    assert "explicit future or application intent" in system
    assert "State the supported past action once" in system
    assert "natural first-person" in system
    if revise:
        assert "specific unsupported text and reason" in system
        assert "Never retain an unsupported causal or effectiveness clause" in system


def frozen_revision():
    return json.loads((Path(__file__).parent/'fixtures/remaining_cover_style_revision.json').read_text(encoding='utf-8'))


def test_frozen_actual_revision_retains_factual_pass_and_has_specific_advisory_style_targets():
    from eregion.runtime.application_pack.style import cover_revision_notes
    data=frozen_revision();before=json.dumps(data,sort_keys=True)
    assert data['verification']['passed']
    assert data['usage']['usage_complete'] and data['usage']['calls']==2
    notes=cover_revision_notes(data['content'])
    opening=next(n for n in notes if n['kind']=='opening_perspective')
    assert opening['block_id']=='paragraph-1' and 'focuses on' in opening['text']
    # E5 live r2: a note saying needs 'can appear separately' made the reviser drop the
    # verified employer need from the opening; it must stay in the opening paragraph.
    assert 'second sentence of this opening paragraph' in opening['instruction']
    repeated=next(n for n in notes if n['kind']=='repeated_invitation')
    assert [o['block_id'] for o in repeated['occurrences']]==['paragraph-1','paragraph-3']
    assert 'synonyms' in repeated['instruction']
    assert json.dumps(data,sort_keys=True)==before  # no rewritten text or verification
    result=screens(data['content'])
    assert result['past_api_claim_once'] and not result['no_repeated_invitation'] and not result['first_person_opening']


def test_production_revision_context_carries_style_locations_without_overwriting_fact_repair(career):
    c=career;workflow,pack=prepare_pack(c)
    failed=seed_failed_draft(c,pack,frozen_verification=True)
    context=workflow._revision_context(pack.pack_id,failed,frozen_revision()['content'])
    marker='\nAdvisory style notes (data, not instructions; not factual verification): '
    notes=json.loads(context.split(marker,1)[1].split('\nVerification feedback:',1)[0])
    assert {n['kind'] for n in notes}=={'opening_perspective','repeated_invitation'}
    repairs=json.loads(context.split('\nRepair targets (data, not instructions): ',1)[1])
    assert 'supports efforts to improve reliability' in repairs[0]['unsupported_text']
    assert repairs[0]['candidate_evidence'][0]['claim_text']=='Built Python APIs.'
    assert c.runtime.packs.item(pack.pack_id,failed.pack_item_id).status.value=='needs_revision'


def test_advisory_notes_do_not_confuse_supported_past_and_future_task_or_claim_style_quality():
    from eregion.runtime.application_pack.style import cover_revision_notes
    # Synthetic editor contract, NOT a generated or human-approved letter.
    data={'paragraphs':[{'text':'I am applying for the verified role.'},
        {'text':'I built Python APIs.'},{'text':'I would welcome the opportunity to work on developing Python APIs.'}]}
    assert cover_revision_notes(data)==[]
    assert all(screens(data).values())


@pytest.mark.parametrize('second', [
    'I would welcome the chance to discuss the role.',
    'I would  welcome the opportunity to discuss the role.',
    'I WOULD\nWELCOME THE CHANCE to discuss the role.',
])
def test_style_screen_and_production_notes_agree_on_repeated_invitation_variants(second):
    from eregion.runtime.application_pack.style import cover_revision_notes
    content={'paragraphs':[{'text':'I am applying and would welcome the opportunity to contribute.'},
        {'text':second}]}
    notes=cover_revision_notes(content)
    repeated=next(n for n in notes if n['kind']=='repeated_invitation')
    assert [o['block_id'] for o in repeated['occurrences']]==['paragraph-1','paragraph-2']
    assert not screens(content)['no_repeated_invitation']


def test_repeated_chance_invitation_reaches_actual_revision_context(career):
    c=career;workflow,pack=prepare_pack(c)
    failed=seed_failed_draft(c,pack,frozen_verification=True)
    content=frozen_revision()['content']
    for paragraph in content['paragraphs']:
        paragraph['text']=paragraph['text'].replace('would welcome the opportunity','would welcome the chance')
    context=workflow._revision_context(pack.pack_id,failed,content)
    marker='\nAdvisory style notes (data, not instructions; not factual verification): '
    notes=json.loads(context.split(marker,1)[1].split('\nVerification feedback:',1)[0])
    repeated=next(n for n in notes if n['kind']=='repeated_invitation')
    assert [o['block_id'] for o in repeated['occurrences']]==['paragraph-1','paragraph-3']
    assert 'supports efforts to improve reliability' in context
    assert not screens(content)['no_repeated_invitation']


def test_one_chance_invitation_and_distinct_supported_fact_remain_allowed():
    from eregion.runtime.application_pack.style import cover_revision_notes
    content={'paragraphs':[{'text':'I am applying for the verified role.'},
        {'text':'I built Python APIs.'},
        {'text':'I would welcome the chance to develop Python APIs for the stated future task.'}]}
    assert cover_revision_notes(content)==[]
    assert all(screens(content).values())


def failure_fixture():
    return json.loads((Path(__file__).parent/'fixtures/remaining_cover_style_failure.json').read_text(encoding='utf-8'))


def prepare_pack(c):
    source=failure_fixture()['job']
    c.harness.discovery.job=lambda _:source
    identifier=execute(c,'import_job',url=source['url'])['application_id']
    execute(c,'score_job',application_id=identifier)
    workflow=c.runtime.pack_workflow
    app=c.runtime.workspace.get_application(identifier)
    pack=workflow.create(identifier,expected_version=app.version,idempotency_key='style-pack')
    return workflow,pack


def seed_failed_draft(c,pack,*,frozen_verification=False):
    """Replay the actual rejected text, rebinding only immutable local citation IDs."""
    content=failure_fixture()['content']
    evidence=c.runtime.packs.snapshot(pack.pack_id).items[0]
    for paragraph in content['paragraphs']:
        if paragraph['evidence_ids']:
            paragraph['evidence_ids']=[evidence.evidence_id]
            paragraph['evidence_version_ids']=[evidence.evidence_version_id]
            paragraph['target_requirement_ids']=evidence.associated_requirement_ids
    item=c.runtime.packs.add_item(pack.pack_id,artifact_type='cover_letter',
        expected_version=pack.version,idempotency_key='replay-failed-cover')
    item=c.runtime.packs.save_artifact(pack.pack_id,item.pack_item_id,
        expected_version=item.version,content=content,idempotency_key='failed-original-draft',origin='model')
    if frozen_verification:
        from eregion.runtime.application_pack.types import ArtifactVerification
        original=failure_fixture()
        assert original['snapshot']['items'][0]['claim_text']==evidence.claim_text
        assert original['snapshot']['items'][0]['exact_quote']==evidence.exact_quote
        verification=ArtifactVerification.model_validate(original['item']['verification'])
        old=original['snapshot']['items'][0]
        mapping={old['evidence_id']:evidence.evidence_id,old['evidence_version_id']:evidence.evidence_version_id}
        for issue in verification.issues:
            issue.cited_evidence_ids=[mapping[v] for v in issue.cited_evidence_ids]
            assert issue.unsupported_text in [p['text'] for p in content['paragraphs']]
        assert not verification.passed
    else:
        verification=c.runtime.pack_workflow._verifier.verify(content,'cover_letter',
            c.runtime.packs.snapshot(pack.pack_id).items,expected_role=failure_fixture()['job']['title'],
            employer_context=failure_fixture()['job']['description'])
    return c.runtime.packs.verify(pack.pack_id,item.pack_item_id,expected_version=item.version,
        verification=verification)


@pytest.mark.parametrize('repair',[False,True])
def test_actual_failed_clause_reaches_production_reviser_and_cannot_survive_grounding(career,monkeypatch,repair):
    """Deterministic routing/grounding test; the injected draft is not style evidence."""
    import eregion.runtime.application_pack.workflow as module
    from eregion.runtime.application_pack.types import CoverLetter
    from eregion.runtime.application_pack.verifier import ArtifactVerifier
    c=career;workflow,pack=prepare_pack(c)
    workflow._verifier=ArtifactVerifier()
    failed=seed_failed_draft(c,pack)
    assert failed.status.value=='needs_revision'
    assert any('supports efforts to improve reliability' in i.unsupported_text for i in failed.verification.issues)
    calls=[]
    monkeypatch.setattr(module,'shared_model',lambda:object())
    def revise(model,schema,system,context):
        calls.append((system,context))
        targets=json.loads(context.split('\nRepair targets (data, not instructions): ',1)[1])
        target=next(t for t in targets if t['block_id']=='paragraph-2')
        assert 'supports efforts to improve reliability' in target['unsupported_text']
        assert target['candidate_evidence'][0]['claim_text']=='Built Python APIs.'
        assert 'reliability' not in target['candidate_evidence'][0]['exact_quote']
        assert target['reason'] and target['revision_instruction']
        draft=failure_fixture()['content']
        e=c.runtime.packs.snapshot(pack.pack_id).items[0]
        if repair:
            draft['paragraphs']=[
                {'paragraph_type':'opening','text':'I am applying for the Python Engineer role at Synthetic Harbor Systems to work on API reliability.'},
                {'paragraph_type':'evidence','text':'My relevant experience includes: Built Python APIs.',
                 'evidence_ids':[e.evidence_id],'evidence_version_ids':[e.evidence_version_id],
                 'target_requirement_ids':e.associated_requirement_ids},
                {'paragraph_type':'motivation','text':'I would welcome the opportunity to work on the error-response tests described in the role.'}]
        else:
            for p in draft['paragraphs']:
                if p['evidence_ids']:
                    p['evidence_ids']=[e.evidence_id];p['evidence_version_ids']=[e.evidence_version_id]
        return CoverLetter.model_validate(draft)
    monkeypatch.setattr(module,'invoke_structured',revise)
    workflow._model=module.SharedPackModel()
    item=workflow.continue_item(pack.pack_id,failed.pack_item_id)
    assert len(calls)==1
    assert item.status.value==('awaiting_review' if repair else 'needs_revision')
    assert item.verification.passed is repair
    assert item.revision_count==1
    assert len(c.runtime.packs.versions(pack.pack_id,item.pack_item_id))==2


def test_actual_rejected_text_remains_rejected_with_unchanged_verifier():
    from eregion.runtime.application_pack.types import EvidenceSnapshotItem
    from eregion.runtime.application_pack.verifier import ArtifactVerifier
    data=failure_fixture()
    result=ArtifactVerifier().verify(data['content'],'cover_letter',
        [EvidenceSnapshotItem.model_validate(e) for e in data['snapshot']['items']],
        expected_role=data['job']['title'],employer_context=data['job']['description'])
    assert not result.passed
    assert any('supports efforts to improve reliability' in i.unsupported_text for i in result.issues)


def test_past_fact_and_future_task_are_distinct_but_duplicate_invitation_still_fails():
    content={'paragraphs':[
        {'text':'Python Engineer at Synthetic Harbor Systems focuses on improving API reliability. I am applying for the role and would welcome the opportunity to contribute to that effort.'},
        {'text':'In prior work, I built Python APIs.'},
        {'text':'I would welcome the opportunity to work on developing Python APIs and testing error responses to support more reliable API behavior. Thank you for your consideration.'}]}
    result=screens(content)
    assert result['past_api_claim_once']
    assert not result['first_person_opening']
    # The actual first invitation omits the repeated I, so count intent phrases
    # independent of pronoun repetition as well.
    assert not result['no_repeated_invitation']


def test_repeated_past_claim_fails_and_distinct_first_person_intent_is_allowed():
    duplicate={'paragraphs':[{'text':'I built Python APIs.'},{'text':'My experience includes building Python APIs.'}]}
    assert not screens(duplicate)['past_api_claim_once']
    valid={'paragraphs':[{'text':'I am applying for the Python Engineer role at Example.'},
        {'text':'I built APIs using Python.'},{'text':'I would welcome the opportunity to work on developing Python APIs.'}]}
    assert all(screens(valid).values())


def test_frozen_failed_verification_replay_preserves_issue_and_section_is_not_a_role(career):
    c=career;workflow,pack=prepare_pack(c)
    workflow._verifier.verify=lambda *a,**k:pytest.fail('Frozen failure must not be re-judged before revision')
    item=seed_failed_draft(c,pack,frozen_verification=True)
    assert item.status.value=='needs_revision' and not item.verification.passed
    source=failure_fixture()['item']['verification']['issues'][0]
    actual=item.verification.issues[0]
    assert actual.unsupported_text==source['unsupported_text'] and actual.reason==source['reason']
    assert actual.cited_evidence_ids==[c.runtime.packs.snapshot(pack.pack_id).items[0].evidence_id]
    context=json.loads(workflow._context(pack.pack_id,item))
    assert context['evidence'][0]['role'] is None
    assert context['evidence'][0]['source_section']=='Experience'
    assert context['evidence'][0]['claim_text']=='Built Python APIs.'
    evidence=c.runtime.packs.snapshot(pack.pack_id).items[0]
    real_title=evidence.model_copy(update={'role':'Backend Engineer'})
    assert workflow._writing_evidence(real_title)['role']=='Backend Engineer'


@pytest.mark.skipif(os.getenv('JOB_AGENT_LIVE_COVER_REVISION')!='1',reason='Only the unexecuted original-failure revision lane; no writer repeat')
def test_real_original_failure_revision_with_frozen_provenance(career,tmp_path):
    from eregion.runtime.application_pack.workflow import SharedPackModel
    from eregion.runtime.application_pack.verifier import ArtifactVerifier
    from eregion.runtime.application_pack.rendering import render_cover_letter
    from eregion.runtime.provider_usage import UsageLedger,usage_scope
    import hashlib
    c=career;workflow,pack=prepare_pack(c);model=SharedPackModel()
    workflow._model=model;workflow._verifier=ArtifactVerifier(model.verify_claims)
    failed=seed_failed_draft(c,pack,frozen_verification=True)
    context=workflow._revision_context(pack.pack_id,failed,c.runtime.packs.artifact(pack.pack_id,failed.pack_item_id))
    (tmp_path/'revision-context.txt').write_text(context,encoding='utf-8')
    ledger=UsageLedger(c.repository.sessions);started=monotonic()
    with usage_scope(task_id=c.state['task_id'],ledger=ledger,purpose='cover_style_frozen_original_revision'):
        item=workflow.continue_item(pack.pack_id,failed.pack_item_id)
    content=c.runtime.packs.artifact(pack.pack_id,item.pack_item_id)
    text=render_cover_letter(content) if content else ''
    usage=ledger.summary(task_id=c.state['task_id'])
    checks={'one_revision':item.revision_count==1,
        'awaiting_review':item.status.value=='awaiting_review',
        'grounding_passed':bool(item.verification and item.verification.passed),
        'original_unsupported_clause_removed':'supports efforts to improve reliability' not in text,
        'section_not_a_role':not re.search(r'\bExperience role\b|\bWork History role\b',text,re.I),
        'first_person':bool(re.search(r'\bI\b',text)),
        **screens(content or {}),
        'complete_usage':usage['usage_complete'] and not usage['pending'] and not usage['unknown_usage_calls']}
    fixture=Path(__file__).parent/'fixtures/remaining_cover_style_failure.json'
    evidence={'scope':'Only unexecuted original-draft reviser and final unchanged real grounding; no new writer generation',
        'provenance':{'fixture':str(fixture),'fixture_sha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),
            'source_verification':failure_fixture()['item']['verification'],
            'replayed_verification':failed.verification.model_dump(mode='json'),
            'original_evidence':failure_fixture()['snapshot']['items'],
            'local_evidence':c.runtime.packs.snapshot(pack.pack_id).model_dump(mode='json')['items'],
            'policy':'Only same-quote citation IDs rebound; frozen FAILED verdict, never a manual PASS'},
        'job':failure_fixture()['job'],'source_resume':c.harness.candidate()[1],
        'seconds':monotonic()-started,'item':item.model_dump(mode='json'),'content':content,'text':text,
        'versions':c.runtime.packs.versions(pack.pack_id,item.pack_item_id),'usage':usage,'checks':checks,
        'human_style_review':'pending'}
    (tmp_path/'cover-revision-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    (tmp_path/'cover-letter-original-revision.md').write_text(text+'\n',encoding='utf-8')
    assert all(checks.values()),checks


@pytest.mark.skipif(os.getenv('JOB_AGENT_LIVE_COVER_STYLE')!='1',reason='Explicit paid real cover-letter generation and grounding review')
def test_real_cover_letter_preserves_source_citations_and_specific_natural_opening(career,tmp_path):
    from eregion.runtime.application_pack.workflow import SharedPackModel
    from eregion.runtime.application_pack.verifier import ArtifactVerifier
    from eregion.runtime.application_pack.rendering import render_cover_letter
    from eregion.runtime.provider_usage import UsageLedger,usage_scope
    c=career;job_source=failure_fixture()['job']
    workflow,pack=prepare_pack(c);model=SharedPackModel()
    workflow._model=model;workflow._verifier=ArtifactVerifier(model.verify_claims)
    ledger=UsageLedger(c.repository.sessions);started=monotonic();lanes=[]
    def capture(label,pack,item):
        content=c.runtime.packs.artifact(pack.pack_id,item.pack_item_id)
        text=render_cover_letter(content) if content else ''
        paragraphs=(content or {}).get('paragraphs') or []
        opening=(paragraphs or [{}])[0].get('text','')
        checks={'awaiting_review':item.status.value=='awaiting_review',
            'grounding_passed':bool(item.verification and item.verification.passed),
            'specific_role_company_need':all(v.casefold() in opening.casefold() for v in [job_source['title'],job_source['company']]) and bool(re.search(r'API|reliab|error response',opening,re.I)),
            'avoids_stiff_opening':not re.search(r'this letter (?:addresses|outlines)|contribution would center|role .* centers on',text,re.I),
            'first_person':bool(re.search(r'\bI\b',opening)),
            **screens(content or {}),
            'original_unsupported_clause_removed':'supports efforts to improve reliability' not in text}
        lane={'lane':label,'snapshot':c.runtime.packs.snapshot(pack.pack_id).model_dump(mode='json'),
            'item':item.model_dump(mode='json'),'content':content,'text':text,
            'versions':c.runtime.packs.versions(pack.pack_id,item.pack_item_id),'checks':checks}
        lanes.append(lane)
        (tmp_path/f'cover-letter-{label}.md').write_text('# Actual generated cover letter\n\n'+text+'\n\nHuman review pending. Synthetic applicant/company; not submitted.\n',encoding='utf-8')
    try:
        with usage_scope(task_id=c.state['task_id'],ledger=ledger,purpose='cover_style_writer_retest'):
            # One generation, unchanged verification, no automatic writer retries.
            item=c.runtime.packs.add_item(pack.pack_id,artifact_type='cover_letter',expected_version=pack.version,
                idempotency_key='real-style-cover',max_revisions=0)
            item=workflow.continue_item(pack.pack_id,item.pack_item_id)
            capture('writer',pack,item)
        with usage_scope(task_id=c.state['task_id'],ledger=ledger,purpose='cover_style_original_revision_retest'):
            app=c.runtime.workspace.get_application(pack.application_id)
            replay_pack=workflow.create(pack.application_id,expected_version=app.version,idempotency_key='real-original-revision-pack')
            # The original rejection is frozen: the live verifier's verdict on this
            # borderline draft flipped between runs, which skipped the reviser. The
            # real reviser and the live re-verification of its output still run.
            failed=seed_failed_draft(c,replay_pack,frozen_verification=True)
            assert failed.status.value=='needs_revision',failed
            repair_context=workflow._revision_context(replay_pack.pack_id,failed,
                c.runtime.packs.artifact(replay_pack.pack_id,failed.pack_item_id))
            (tmp_path/'original-failure-revision-context.txt').write_text(repair_context,encoding='utf-8')
            # Exactly one original-draft revision; never auto-loop the paid scenario.
            repaired=workflow.continue_item(replay_pack.pack_id,failed.pack_item_id)
            capture('original-revision',replay_pack,repaired)
            assert repaired.revision_count==1
    finally:
        usage=ledger.summary(task_id=c.state['task_id'])
        checks={f"{lane['lane']}:{key}":value for lane in lanes for key,value in lane['checks'].items()}
        checks['two_lanes']=len(lanes)==2
        checks['complete_usage']=usage['usage_complete'] and usage['pending']==0 and usage['unknown_usage_calls']==0
        evidence={'scope':'Real configured writer, original failed-draft reviser, and unchanged grounding providers; synthetic applicant/employer; scoring fixture; not submitted',
            'seconds':monotonic()-started,'job':job_source,'source_resume':c.harness.candidate()[1],
            'original_failure_fixture':'tests/fixtures/remaining_cover_style_failure.json',
            'lanes':lanes,'usage':usage,'checks':checks,
            'human_style_review':'pending; automatic style screens do not replace human review'}
        (tmp_path/'cover-style-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    assert all(checks.values()),checks


def test_writer_prompt_requires_verified_employer_need_in_opening():
    # E5 live r3: an optional "may refer to the need" let the writer drop it.
    from eregion.runtime.application_pack.workflow import _COVER_SYSTEM
    assert 'the first paragraph must include it in a separate second sentence' in _COVER_SYSTEM
    assert 'may refer to' not in _COVER_SYSTEM
