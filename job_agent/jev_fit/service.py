"""Production Jev-only analysis boundary; no writer or main-model dependency."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import time
from .cache import DecisionCache
from .core import JevFit
from .projection import project
from .settings import Settings, digest, canonical
from .transport import Broker, Client


class JevFitError(RuntimeError):
    pass


class JevFitService:
    def __init__(self, config: Settings, *, owner='local', transport=None, max_requests=160):
        self.config,self.owner,self.transport,self.max_requests=config,owner,transport,max_requests

    def analyze_many(self, *, resume_text, jobs, candidate_facts=None):
        if not resume_text.strip() or not jobs or len(jobs)>8 or len({j['id']for j in jobs})!=len(jobs):
            raise ValueError('Provide a resume and one to eight unique jobs.')
        if any(not j['job_description'].strip()for j in jobs):
            raise ValueError('A job description must not be empty.')
        cache=DecisionCache(self.config.cache_path,ttl=self.config.ttl,unknown_ttl=self.config.unknown_ttl)if self.config.cache_path else None
        broker=Broker(self.config,cache,transport=self.transport,max_requests=self.max_requests)
        started=time.perf_counter()
        evidence=resume_text+('\nUSER PROVIDED FACTS\n'+canonical(candidate_facts)if candidate_facts else '')
        def work(job):
            client=Client(broker,{'owner':self.owner,'resume':digest(resume_text),
                'facts':digest(candidate_facts or {}),'job':digest(job['job_description'])})
            raw=JevFit(client).analyze(evidence,jd=job['job_description'])
            if raw.get('provider_errors')or 'matches'not in raw:
                raise JevFitError('Jev fit analysis could not complete: '+','.join(raw.get('provider_errors')or[raw['status']]))
            return job,client,raw
        try:
            with ThreadPoolExecutor(max_workers=min(len(jobs),4),thread_name_prefix='jev-fit')as pool:
                futures=[pool.submit(copy_context().run,work,job)for job in jobs]
                completed=[f.result()for f in futures]
        finally:
            broker.close()
        # Assign each paid batch to exactly one consumer so aggregates never multiply
        # shared tokens. All consumers still retain cache/call provenance.
        assigned=set()
        results={}
        for job,client,raw in completed:
            events=[e for e in broker.events if e['task_id']==client.task_id]
            paid_ids={e.get('provenance',{}).get('call_id')for e in events if not e['hit']}
            records=[r for r in broker.records if r['call_id']in paid_ids and r['call_id']not in assigned]
            assigned.update(r['call_id']for r in records)
            expires=min((e['expires_at']for e in events if 'expires_at'in e),default=time.time())
            resume,parsed_job,match=project(raw,resume_text,job['job_description'],model=self.config.model,expires_at=expires)
            results[job['id']]={'analysis_id':'analysis-'+client.task_id,'status':raw['status'],
                'resume_analysis':resume,'job_analysis':parsed_job,'skill_match':match,
                'model_calls':len(records),'main_model_calls':0,'fast_model_calls':len(records),
                'latency_seconds':max(0,time.perf_counter()-started),
                'stage_seconds':{'jev_fit':raw['seconds']},
                'cache_hits':sorted({e['purpose']for e in events if e['hit']}),
                'decision_routing':[{'purpose':'jev_fit','model':self.config.model,'run_id':broker.run_id,
                    'requests':len(records),'cache_hits':sum(e['hit']for e in events),
                    'cache_misses':sum(not e['hit']for e in events),
                    'input_tokens':sum(r['input_tokens']or 0 for r in records),
                    'output_tokens':sum(r['output_tokens']or 0 for r in records),
                    'unknown_usage_calls':sum(r['input_tokens']is None or r['output_tokens']is None for r in records),
                    'calls':records}]}
        return results
