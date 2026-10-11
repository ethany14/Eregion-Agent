"""C16 causal lock regression: real SQLite, event-gated offline providers."""
import json
from threading import Event, Thread

import httpx
import pytest

from test_career_flow import career
from test_remaining_interview_async import answered, chat, service_for
from test_remaining_interview_fifo import prepared, wait_for


@pytest.mark.parametrize('question_owner', ['answer_deferred', 'evaluate_deferred'])
def test_fast_feedback_failure_commits_while_next_question_provider_is_blocked(
        career, tmp_path, monkeypatch, question_owner):
    c = career
    controller, identifier = prepared(c)
    q1 = controller.interviews.get(identifier).current_question_id
    question_started, release_question = Event(), Event()
    provider_failed, failure_committed = Event(), Event()
    original_question, original_evaluate = controller.model.question, controller.model.evaluate
    original_failure = controller.interviews.feedback_failed
    errors, workers = [], []
    service = None
    # Exercise evaluate_deferred's own next-question generation separately from
    # the main-chat answer queue path. Both use production persisted ownership.
    if question_owner == 'evaluate_deferred':
        controller.answer_deferred(identifier, 'A1: I built Python APIs.',
            question_id=q1, idempotency_key='lock-A1', dispatch=lambda: None)
        current = controller.interviews.get(identifier)
        answer, _ = controller.interviews.save_answer(identifier, current.current_question_id,
            'A2: I tested the API.', current.version, 'lock-A2')
        controller.interviews.defer_feedback(identifier, answer.answer_id)

    def blocked_question(context):
        question_started.set()
        assert release_question.wait(12), 'test must release the offline question provider'
        return original_question(context)

    def fast_failure(context):
        if context['answer_untrusted'].startswith('A1:'):
            assert question_started.wait(5)
            provider_failed.set()
            raise httpx.ConnectError('Synthetic offline feedback connection failure')
        return original_evaluate(context)

    def persist_failure(*args, **kwargs):
        result = original_failure(*args, **kwargs)
        failure_committed.set()  # after the production repository transaction
        return result

    monkeypatch.setattr(controller.model, 'question', blocked_question)
    monkeypatch.setattr(controller.model, 'evaluate', fast_failure)
    monkeypatch.setattr(controller.interviews, 'feedback_failed', persist_failure)

    def run(job):
        try:
            controller.evaluate_deferred(identifier, job)
        except Exception as exc:
            errors.append(type(exc).__name__)

    try:
        if question_owner == 'answer_deferred':
            service = service_for(c)
            chat(service, c, identifier, 'A1: I built Python APIs.')
        else:
            jobs = controller.interviews.feedback_jobs(identifier)
            workers.append(Thread(target=run, args=(jobs[1],)))
            workers[-1].start()
            assert question_started.wait(5)
            workers.append(Thread(target=run, args=(jobs[0],)))
            workers[-1].start()
        assert question_started.wait(5) and provider_failed.wait(5)
        saved_before_release = failure_committed.wait(2)
        snapshot = {
            'scope': 'Real production SQLite/controller; synthetic event-gated providers; no network/real latency assertion.',
            'question_owner': question_owner,
            'question_still_blocked': not release_question.is_set(),
            'feedback_provider_failed': provider_failed.is_set(),
            'failure_committed_before_question_release': saved_before_release,
            'session': controller.interviews.get(identifier).model_dump(mode='json'),
            'jobs': controller.interviews.feedback_jobs(identifier),
            'turns': controller.interviews.turns(identifier),
            'queue': c.repository.get(c.state['task_id']).get('interview_queue', []),
        }
        (tmp_path / 'failure-before-question-release.json').write_text(
            json.dumps(snapshot, indent=2), encoding='utf-8')
        assert saved_before_release, 'FEEDBACK_FAILED waited for the blocked next-question RPC'
        first = next(j for j in snapshot['jobs'] if j['question_id'] == q1)
        assert first['status'] == 'failed'
        assert first['failure']['error_type'] == 'ConnectError'
        assert first['answer_id'] == answered(controller, identifier)[0]['answer']['answer_id']
        assert snapshot['session']['questions_completed'] == (0 if question_owner == 'answer_deferred' else 1)
    finally:
        release_question.set()
        if service:
            service.close()
        for worker in workers:
            worker.join(timeout=8)
        (tmp_path / 'failure-after-question-release.json').write_text(json.dumps({
            'session': controller.interviews.get(identifier).model_dump(mode='json'),
            'jobs': controller.interviews.feedback_jobs(identifier),
            'turns': controller.interviews.turns(identifier), 'errors': errors,
        }, indent=2), encoding='utf-8')
    assert not errors and all(not w.is_alive() for w in workers)
    assert controller.interviews.get(identifier).status.value == 'awaiting_answer'
    assert len(answered(controller, identifier)) == (1 if question_owner == 'answer_deferred' else 2)
    assert controller.interviews.feedback_jobs(identifier)[0]['status'] == 'failed'


def test_feedback_and_answer_share_one_question_draft_without_holding_transition_lock(career, monkeypatch):
    c = career
    controller, identifier = prepared(c)
    started, release = Event(), Event()
    original_question = controller.model.question
    calls = []

    def blocked_question(context):
        calls.append(context['plan_item']['plan_item_id'])
        started.set()
        assert release.wait(12)
        return original_question(context)

    monkeypatch.setattr(controller.model, 'question', blocked_question)
    service = service_for(c)
    try:
        chat(service, c, identifier, 'A1: I built Python APIs.')
        assert started.wait(5)
        wait_for(lambda: answered(controller, identifier)[0]['evaluation'])
        acquired = controller.transition_lock(identifier).acquire(blocking=False)
        if acquired:
            controller.transition_lock(identifier).release()
        assert acquired, 'Question provider must not own the transition lock'
        release.set()
        wait_for(lambda: controller.interviews.get(identifier).current_question_id)
        assert len(calls) == 1
        assert len(controller.interviews.questions(identifier)) == 2
        chat(service, c, identifier, 'End the interview.')
        assert wait_for(lambda: controller.interviews.report(identifier))
        assert controller.interviews.get(identifier).questions_completed == 1
    finally:
        release.set()
        service.close()


@pytest.mark.parametrize('terminal', ['cancel', 'end'])
@pytest.mark.parametrize('question_result', ['draft', 'failure'])
def test_terminal_during_question_rpc_discards_late_draft_or_failure(career, monkeypatch, terminal, question_result):
    c = career
    controller, identifier = prepared(c)
    started, release = Event(), Event()
    original_question = controller.model.question

    def blocked_question(context):
        started.set()
        assert release.wait(12)
        if question_result == 'failure':
            raise httpx.ConnectError('Synthetic offline question connection failure')
        return original_question(context)

    monkeypatch.setattr(controller.model, 'question', blocked_question)
    service = service_for(c)
    try:
        chat(service, c, identifier, 'A1: I built Python APIs.')
        assert started.wait(5)
        wait_for(lambda: answered(controller, identifier)[0]['evaluation'])
        with controller.transition_lock(identifier):
            current = controller.interviews.get(identifier)
            getattr(controller, terminal)(identifier, expected_version=current.version,
                idempotency_key=terminal+'-paused-question')
        release.set()
        wait_for(lambda: c.repository.get(c.state['task_id'])['interview_queue'][0]['status'] == 'done')
        assert controller.interviews.get(identifier).status.value == ('cancelled' if terminal == 'cancel' else 'completed')
        assert len(controller.interviews.questions(identifier)) == 1
        assert len(answered(controller, identifier)) == 1
        assert controller.interviews.get(identifier).questions_completed == 1
    finally:
        release.set()
        service.close()
