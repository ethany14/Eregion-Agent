"""L3: opt-in real writer, synthetic frozen evidence and existing verifier."""
import json
import os
import time
from pathlib import Path
import pytest
from test_application_pack import setup
from test_integrated_p7 import pending
from agent_runtime.application_pack.workflow import SharedPackModel
from agent_runtime.application_pack.types import ItemStatus
from agent_runtime.provider_usage import UsageLedger, usage_scope, capture_provider_attempts
from evals.opt_report import wire_summary
from agent_runtime.application_pack.verifier import ArtifactVerifier


def use_revision_model(workflow, model):
    """Keep the injected writer and semantic judge paired as in production init."""
    workflow._model = model
    workflow._verifier = ArtifactVerifier(getattr(model, 'verify_claims', None))

@pytest.mark.skipif(os.getenv('JOB_AGENT_LIVE_MATERIAL_PATCHES') != '1',
                   reason='L3 paid material comparison; explicit networked reviewer opt-in required')
@pytest.mark.parametrize('variant', ['full', 'patch'])
def test_live_material_revision(setup, monkeypatch, variant):
    output = os.getenv('OPT_LIVE_OUTPUT')
    assert output, 'Set an unused output directory for each L3 pair'
    target = Path(output) / (variant + '.json')
    assert not target.exists(), 'Never overwrite a paid attempt'
    target.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('JOB_AGENT_OPT_MATERIAL_PATCHES', str(int(variant == 'patch')))
    monkeypatch.setenv('JOB_AGENT_TASK_MAX_INPUT_TOKENS', '80000')
    monkeypatch.setenv('JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS', '6')
    workflow, packs, _, _, _, db = setup
    pack, item, original = pending(setup)
    use_revision_model(workflow, SharedPackModel())
    ledger = UsageLedger(db.session_factory)
    task_id = 'l3-' + pack.pack_id
    start = time.monotonic()
    done = None
    with capture_provider_attempts() as attempts:
        try:
            with usage_scope(task_id=task_id, run_id=task_id, purpose='material_revision', ledger=ledger):
                done = workflow.continue_item(pack.pack_id, item.pack_item_id)
        finally:
            target.write_text(json.dumps({'variant': variant,
                'status': str(done.status) if done else 'interrupted',
                'seconds': time.monotonic() - start, 'provider_usage': ledger.summary(task_id=task_id),
                'wire': wire_summary(attempts), 'human_style_review': 'pending',
                'original': original, 'artifact': packs.artifact(pack.pack_id, item.pack_item_id)},
                indent=2, default=str), encoding='utf-8')
    assert done.status == ItemStatus.AWAITING_REVIEW
