"""The live lane must exercise its writer's semantic judge, without paid IO."""
import json
import pytest
from test_application_pack import setup
from test_integrated_p7 import pending
from test_integrated_p8_material_live import use_revision_model
from eregion.runtime.application_pack.types import CoverLetter, ItemStatus


@pytest.mark.parametrize('supported', [True, False])
def test_live_lane_paraphrase_uses_injected_judge(setup, monkeypatch, supported):
    monkeypatch.setenv('JOB_AGENT_OPT_MATERIAL_PATCHES', '0')
    workflow, packs, *_ = setup
    pack, item, original = pending(setup)
    calls = []

    class Writer:
        def revise_blocks(self, artifact_type, context):
            content = json.loads(json.dumps(original))
            content['paragraphs'][0]['text'] = 'I am applying for the Backend Engineer role.'
            content['paragraphs'][1]['text'] = 'I have built Python APIs.'
            return CoverLetter.model_validate(content)

        def verify_claims(self, claims):
            calls.extend(claims)
            return {c['claim_id'] for c in claims} if supported else set()

    use_revision_model(workflow, Writer())
    done = workflow.continue_item(pack.pack_id, item.pack_item_id)
    assert len(calls) == 1
    assert calls[0]['claim'] == 'I have built Python APIs.'
    assert done.status == (ItemStatus.AWAITING_REVIEW if supported else ItemStatus.NEEDS_REVISION)
    assert done.verification.passed is supported
    assert done.revision_count == 1
