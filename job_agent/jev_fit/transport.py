"""Bounded exact-state batching. Paid usage is recorded once per HTTP request."""
from concurrent.futures import Future
from contextvars import copy_context
from dataclasses import dataclass
import copy
import json
import queue
import threading
import time
import uuid

import httpx
from agent_runtime.multi_agent.model_usage import invoke_model, current_model_call
from agent_runtime.provider_usage import provider_call, usage_scope, token_counts
from .core import MAX_PAYLOAD_BYTES, MAX_QUESTIONS, boolean, validate_answers
from .settings import canonical, digest


@dataclass
class Pending:
    state: dict
    questions: dict
    purpose: str
    scope: dict
    task_id: str
    context: object
    future: Future


class Broker:
    def __init__(self, config, cache, *, transport=None, max_requests=160, batch=True):
        if not config.key:
            raise ValueError('TYPESAFE_ENABLED is true but TYPESAFE_API_KEY is missing.')
        self.config, self.cache, self.batch = config, cache, batch
        self.signature, self.max_requests = config.signature(), max_requests
        self.run_id = str(uuid.uuid4())
        self.records, self.events = [], []
        # A warm cache needs no HTTP client or TLS initialization.
        self.http, self.transport = None, transport
        self.queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, name='jev-fit-broker', daemon=True)
        self.thread.start()

    def close(self):
        self.queue.put(None)
        self.thread.join()
        if self.http is not None:
            self.http.close()

    def submit(self, *, state, questions, purpose, scope, task_id):
        future = Future()
        self.queue.put(Pending(copy.deepcopy(state), copy.deepcopy(questions), purpose,
                               copy.deepcopy(scope), task_id, copy_context(), future))
        return future.result()

    def _run(self):
        stop = False
        while not stop:
            item = self.queue.get()
            if item is None:
                return
            pending = [item]
            if self.batch:
                deadline = time.monotonic() + .008
                while True:
                    try:
                        item = self.queue.get(timeout=max(0, deadline-time.monotonic()))
                    except queue.Empty:
                        break
                    if item is None:
                        stop = True
                        break
                    pending.append(item)
            groups = {}
            for p in pending:
                key = digest([p.state, p.purpose, p.scope['owner'], p.scope['resume'], p.scope['facts']])
                if not self.batch:
                    key += p.task_id
                groups.setdefault(key, []).append(p)
            for group in groups.values():
                try:
                    self._dispatch(group)
                except BaseException as exc:
                    for p in group:
                        if not p.future.done():
                            p.future.set_exception(exc)

    def _key(self, p, q):
        return digest([self.signature, p.scope, p.purpose, p.state, q])

    def _request(self, state, questions, purpose, context):
        if len(self.records) >= self.max_requests:
            return {}, 'request_budget', None
        payload = {'model': self.config.model, 'state': state, 'questions': questions}
        if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_PAYLOAD_BYTES:
            return {}, 'payload_limit', None
        rec = {'call_id': str(uuid.uuid4()), 'model': self.config.model, 'purpose': purpose,
               'status': 'started', 'input_tokens': None, 'output_tokens': None,
               'question_count': len(questions)}
        self.records.append(rec)
        started = time.monotonic()

        def call():
            with usage_scope(purpose='jev:fit:' + purpose):
                def paid_request(request_payload):
                    with provider_call(self.config.model, context_chars=len(canonical(request_payload))) as usage:
                        if self.http is None:
                            self.http = httpx.Client(timeout=self.config.timeout, transport=self.transport,
                                follow_redirects=False, headers={'Authorization': 'Bearer ' + self.config.key})
                        response = self.http.post(self.config.base_url + '/v1/systemone', json=request_payload)
                        if response.status_code != 200:
                            usage.update(status='failed', http_status=response.status_code)
                            rec['status'] = 'http_' + str(response.status_code)
                            return {}
                        data = response.json()
                        counts = token_counts(data.get('usage'))
                        usage.update(counts)
                        rec.update(counts)
                        reservation = current_model_call()
                        if reservation is not None and all(k in counts for k in ('input_tokens','output_tokens')):
                            reservation['usage'] = {k: counts[k] for k in ('input_tokens','output_tokens')}
                        if data.get('model') != self.config.model:
                            raise ValueError('Unexpected Jev release')
                        result = validate_answers(data, questions)
                        rec['status'] = 'ok'
                        return result
                return invoke_model(paid_request, payload)
        try:
            answers = context.run(call)
        except httpx.TimeoutException:
            answers, rec['status'] = {}, 'timeout'
        except httpx.HTTPError:
            answers, rec['status'] = {}, 'connection_error'
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            answers, rec['status'] = {}, 'invalid_response'
        finally:
            rec['seconds'] = round(time.monotonic() - started, 4)
        return answers, rec['status'], rec

    def _dispatch(self, pending):
        answers = {id(p): {} for p in pending}
        errors = {id(p): [] for p in pending}
        keys = {(id(p), k): self._key(p, q) for p in pending for k,q in p.questions.items()}
        cached = self.cache.get_many(keys.values(), self.config.model) if self.cache else {}
        unique, targets, identifiers = {}, {}, {}
        for p in pending:
            for k,q in p.questions.items():
                if q.get('type') != 'noul':
                    raise ValueError('Only yes/no fit decisions are supported')
                key = keys[(id(p),k)]
                hit = cached.get(key)
                event = {'task_id':p.task_id, 'purpose':p.purpose, 'question':k,
                         'cache_key':key, 'hit':bool(hit)}
                self.events.append(event)
                if hit:
                    answers[id(p)][k] = hit['answer']
                    event.update(expires_at=hit['expires_at'], provenance=hit['provenance'])
                    continue
                qhash = digest(q)
                wire = identifiers.setdefault(qhash, 'q'+str(len(identifiers)))
                if wire in unique and unique[wire] != q:
                    raise ValueError('Question hash collision')
                unique[wire] = q
                targets.setdefault(wire, []).append((p,k,key,event))
        batches, current = [], {}
        state, purpose = pending[0].state, pending[0].purpose
        for k,q in unique.items():
            trial = {**current, k:q}
            payload = {'model':self.config.model,'state':state,'questions':trial}
            if current and (len(trial)>MAX_QUESTIONS or len(json.dumps(payload,ensure_ascii=False).encode())>MAX_PAYLOAD_BYTES):
                batches.append(current)
                current={}
            current[k]=q
        if current:
            batches.append(current)
        for batch in batches:
            result,status,record = self._request(state,batch,purpose,pending[0].context)
            writes=[]
            for wire in batch:
                for p,k,key,event in targets[wire]:
                    event['status']=status
                    if status=='ok':
                        answer=result[wire]
                        expires=time.time()+(self.config.unknown_ttl if boolean(answer)is None else self.config.ttl)
                        provenance={'call_id':record['call_id'],'run_id':self.run_id,'model':self.config.model}
                        event.update(expires_at=expires,provenance=provenance)
                        answers[id(p)][k]=answer
                        writes.append((key,answer,provenance))
            if self.cache and writes:
                self.cache.put_many(writes,self.config.model)
            if status!='ok':
                for p in pending:
                    if set(answers[id(p)]) != set(p.questions):
                        errors[id(p)].append(status)
                break
        for p in pending:
            p.future.set_result((answers[id(p)],errors[id(p)]))


class Client:
    def __init__(self, broker, scope):
        self.broker,self.scope=broker,scope
        self.task_id=str(uuid.uuid4())
        self.categories={}
        self.requests=0

    def evaluate(self,state,questions,purpose):
        if not questions:
            return {},[]
        self.requests+=1
        if self.requests>24:
            return {},['logical_request_budget']
        if purpose=='support_yes_no':
            kept={}
            for k,q in questions.items():
                category=boolean(self.categories.get('c'+k[1:]))
                if (k.startswith('k')and category is not True)or(k.startswith('r')and category is True):
                    continue
                kept[k]=q
            questions=kept
        answers,errors=self.broker.submit(state=state,questions=questions,purpose=purpose,
                                          scope=self.scope,task_id=self.task_id)
        if purpose=='condition_category_yes_no':
            self.categories=answers
        return answers,errors
