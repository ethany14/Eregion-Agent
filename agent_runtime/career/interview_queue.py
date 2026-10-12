"""Durable arrival-order interview input; provider work never holds the chat lock."""
import re
from threading import Event, Lock

from agent_runtime.execution import ExecutionClosed

from agent_runtime.provider_usage import UsageLedger, usage_scope
from .repository import now

END = {'end interview','end the interview','end this interview','finish interview',
    'finish the interview','end this practice and show my report','结束面试','结束这次面试','结束模拟面试'}


def input_kind(text):
    text=text.strip().rstrip('.!。！').casefold()
    if text in END:return 'end'
    if text in {'skip','skip question','skip this question','next question'}:return 'skip'
    if text in {'resume interview','retry interview feedback','retry saved interview feedback'}:return 'resume'
    # Coaching questions and explicit new tasks retain ordinary model routing.
    if text.endswith(('?','？')) or re.match(r'^(?:find|search|apply|submit|generate|write|prepare|resume|pause|stop)\b',text):return None
    return 'answer' if text else None


def pending_answers(harness,state,identifier,*,before_message_id=None):
    interview=harness.runtime.mock_interviewer.interviews.get(identifier)
    consumed=set((state.get('interview_answer_receipts') or {}).get(identifier,[]))
    start=interview.started_at.isoformat()
    messages={m['id']:m for m in state.get('messages',[]) if m['role']=='user'}
    for entry in state.get('interview_queue',[]):
        if entry['interview_id']==identifier:
            messages.setdefault(entry['message_id'],{'id':entry['message_id'],'role':'user',
                'text':entry['text'],'at':entry['at'],'context':{'interview_id':identifier}})
    ordered=sorted(messages.values(),key=lambda m:m.get('at',''))
    end=next((m.get('at') for m in ordered if input_kind(m['text'])=='end'
        and m.get('context',{}).get('interview_id') in {None,identifier} and m.get('at','')>=start),None)
    boundary=messages.get(before_message_id,{}).get('at')
    if boundary is not None:end=min(end,boundary) if end is not None else boundary
    return [m for m in ordered if m['id'] not in consumed and (end is None or m.get('at','')<end)
        and m.get('at','')>=start and input_kind(m['text'])=='answer'
        and (m.get('context',{}).get('interview_id') in {None,identifier})]


class InterviewQueue:
    def __init__(self,harness,execution=None):
        self.harness=harness
        self.lock=Lock();self.running={}
        self.feedback_running={}
        self.closed=False
        self.execution=None
        if execution is not None:self.bind(execution)

    def bind(self,execution):
        """Run inputs and feedback on the process ExecutionService (bounded pools).
        Per-task arrival order is kept by self.running: one runner per task."""
        execution.register_kind('interview_inputs',max_workers=4)
        execution.register_kind('interview_feedback',max_workers=3,recover=None)
        self.execution=execution

    def _execution(self):
        if self.execution is None:
            from agent_runtime.execution import ExecutionService
            self.bind(ExecutionService())
        return self.execution

    def start_feedback(self,task_id,identifier,*,retry_failed=False):
        controller=self.harness.runtime.mock_interviewer
        if controller.interviews.get(identifier).status.value in {'completed','cancelled'}:return
        for job in controller.interviews.feedback_jobs(identifier):
            if job['status']=='done' or job['status']=='failed' and not retry_failed:continue
            key=(task_id,identifier,job['answer_id'])
            with self.lock:
                if key in self.feedback_running:continue
                if job['status']=='failed':controller.interviews.retry_feedback(identifier,job['answer_id'])
                if self.closed:return
                self.feedback_running[key]=None
                try:self._execution().submit('interview_feedback',None,self._feedback,key,job)
                except ExecutionClosed:self.feedback_running.pop(key,None);return

    def retry(self,task_id,identifier):
        self.harness.repository.change(task_id,lambda s:{'interview_queue':[
            {**e,'status':'pending'} if e['interview_id']==identifier and e['status']=='failed' else e
            for e in s.get('interview_queue',[]) ]},error=None)
        self.start_feedback(task_id,identifier,retry_failed=True)
        self.start(task_id)

    def _feedback(self,key,job):
        task_id,identifier,_=key;h=self.harness
        try:
            with usage_scope(ledger=UsageLedger(h.repository.sessions),task_id=task_id,purpose='interview_feedback'):
                h.runtime.mock_interviewer.evaluate_deferred(identifier,job)
        finally:
            with self.lock:self.feedback_running.pop(key,None)

    def route(self,state,message):
        context=message.get('context') or {}
        ids=[context['interview_id']] if context.get('interview_id') else state.get('interviews',[])
        active=[i for i in ids if self.harness.runtime.mock_interviewer.interviews.get(i).status.value
            in {'awaiting_answer','evaluating','planning'}]
        kind=input_kind(message['text'])
        if len(active)!=1 or not kind:return None
        identifier=active[0]
        if kind=='resume':
            return {'text':'I will retry the saved interview feedback and continue the existing input queue.',
                'tool':'queue_interview_input','result':{'interview_id':identifier,'retry':True},
                'deferred':True,'start':lambda:self.retry(state['task_id'],identifier)}
        if any(e['interview_id']==identifier and e['kind']=='end' for e in state.get('interview_queue',[])):
            return {'text':'The interview end is already queued. Your new message is saved in chat and will not be treated as an earlier interview answer.',
                'tool':'queue_interview_input','result':{'interview_id':identifier,'message_id':message['id'],'queued':False},
                'deferred':True,'start':lambda:self.start(state['task_id'])}
        # Keep the queue independent of the bounded conversation/history window.
        entry={'message_id':message['id'],'text':message['text'],'interview_id':identifier,
            'kind':kind,'status':'pending','at':message['at']}
        def append(current):
            queue=current.get('interview_queue',[])
            return {} if any(e['message_id']==message['id'] for e in queue) else {'interview_queue':[*queue,entry]}
        self.harness.repository.change(state['task_id'],append)
        return {'text':'I will end the interview after the earlier queued answers are saved.' if kind=='end'
            else 'Your interview input is queued in arrival order.',
            'tool':'queue_interview_input','result':{'interview_id':identifier,'message_id':message['id'],'queued':True},
            'deferred':True,'start':lambda:self.start(state['task_id'])}

    def start(self,task_id):
        with self.lock:
            if self.closed or task_id in self.running:return
            self.running[task_id]=None
            try:self._execution().submit('interview_inputs',None,self._run,task_id)
            except ExecutionClosed:self.running.pop(task_id,None)

    def recover(self):
        for state in self.harness.repository.list():
            for identifier in state.get('interviews',[]):self.start_feedback(state['task_id'],identifier)
            if any(e['status'] in {'pending','running'} for e in state.get('interview_queue',[])):
                self.start(state['task_id'])

    def _update(self,task_id,message_id,**values):
        return self.harness.repository.change(task_id,lambda s:{'interview_queue':[
            {**entry,**values} if entry['message_id']==message_id else entry for entry in s['interview_queue']]})

    def _run(self,task_id):
        h=self.harness
        try:
            while True:
                state=h.repository.get(task_id)
                if state.get('pause_requested') or state['status']=='cancelled':return
                entry=next((e for e in state.get('interview_queue',[]) if e['status']!='done'),None)
                if not entry or entry['status']=='failed':return
                mid=entry['message_id'];identifier=entry['interview_id']
                try:
                    self._update(task_id,mid,status='running',started_at=now())
                    current=h.runtime.mock_interviewer.interviews.get(identifier)
                    if entry['kind']=='end':
                        # Acceptance order is already fixed. Ending must wait
                        # for all earlier durable answers' independent feedback.
                        while True:
                            jobs=h.runtime.mock_interviewer.interviews.feedback_jobs(identifier)
                            if any(j['status']=='failed' for j in jobs):
                                raise ValueError('Saved feedback failed; retry it before creating the final report.')
                            if all(j['status']=='done' for j in jobs):break
                            state=h.repository.get(task_id)
                            if state.get('pause_requested') or state['status']=='cancelled':return
                            Event().wait(.05)
                        current=h.runtime.mock_interviewer.interviews.get(identifier)
                    elif entry['kind']=='answer' and not entry.get('question_id'):
                        while current.current_question_id is None and current.status.value=='planning':
                            jobs=h.runtime.mock_interviewer.interviews.feedback_jobs(identifier)
                            if not jobs or any(j['status']=='failed' for j in jobs):break
                            state=h.repository.get(task_id)
                            if state.get('pause_requested') or state['status']=='cancelled':return
                            Event().wait(.05)
                            current=h.runtime.mock_interviewer.interviews.get(identifier)
                    args={'interview_id':identifier,'message_id':mid}
                    if entry['kind']=='answer':
                        # Bind only the head input to the actual next question.
                        question=entry.get('question_id') or current.current_question_id
                        self._update(task_id,mid,question_id=question)
                        args['question_id']=question
                    else:args['action']=entry['kind']
                    with usage_scope(ledger=UsageLedger(h.repository.sessions),task_id=task_id,purpose='interview_queue'):
                        result=h.execute(task_id,'answer_interview' if entry['kind']=='answer' else 'control_interview',
                            args,call_id='interview-queue:'+mid)
                    if result['status']=='failed':raise ValueError('Interview evaluation failed; saved answer and queued inputs retained.')
                    self._update(task_id,mid,status='done',finished_at=now())
                    if entry['kind']=='end':
                        h.repository.append(task_id,role='assistant',text='The interview has ended. Your saved answers and report are available below.')
                        h.repository.change(task_id,status='completed',error=None)
                except Exception as exc:
                    self._update(task_id,mid,status='failed',error_type=type(exc).__name__)
                    h.repository.change(task_id,status='needs_input',error={'code':'interview_queue_failed',
                        'message':'Interview processing stopped. Saved answers and queued inputs are preserved. Inspect the interview before retrying.',
                        'retryable':True})
                    return
        finally:
            with self.lock:
                self.running.pop(task_id,None)
            # An enqueue can race the final empty read; do not strand it.
            state=h.repository.get(task_id)
            if not state.get('pause_requested') and state['status']!='cancelled' and any(
                e['status'] in {'pending','running'} for e in state.get('interview_queue',[])) and not any(
                e['status']=='failed' for e in state.get('interview_queue',[])):
                self.start(task_id)

    def close(self):
        """Stop accepting inputs/feedback and drain in-flight work (bounded, as before)
        so the harness can close its resources afterwards. Idempotent."""
        with self.lock:
            self.closed=True
        if self.execution is not None:
            for kind in ('interview_inputs','interview_feedback'):
                self.execution.stop_kind(kind,timeout=30)
