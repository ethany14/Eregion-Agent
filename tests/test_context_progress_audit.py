from eregion.runtime.request_context import ContextArchive


def test_growing_assistant_narration_cannot_become_new_source_evidence():
    archive = ContextArchive()
    rows = []
    for i in range(4):
        rows.append({'id': str(i), 'at': '2026-10-12', 'role': 'assistant', 'text': 'I will check jobs.'})
        ref = archive.reference(rows)['context_ref']
        result = archive.read(ref)
        assert result['no_new_evidence'] and not result['content']
        assert result['error_code'] == 'assistant_progress_context'
    # Restart retains the distinction, and explicit audit does not manufacture progress.
    restored = ContextArchive(archive.values)
    audit = restored.read(ref, historical=True)
    assert audit['no_new_evidence'] and audit['historical'] and 'check jobs' in audit['content']


def test_user_messages_and_source_text_remain_readable():
    archive = ContextArchive()
    for value in ([{'id':'1','at':'now','role':'user','text':'Only search New York'}],
                  {'description':'A long job description'},
                  [{'title':'Data Analyst','url':'https://example.com/job'}]):
        result = archive.read(archive.reference(value)['context_ref'])
        assert result['content'] and not result.get('no_new_evidence')
