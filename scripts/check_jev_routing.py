"""Offline fault-injection regression; no pytest, secrets, or network calls."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from agent_runtime.fast_decisions import FastDecisions, configured_decisions, capture_routing
from agent_runtime.semantics import SemanticDecisions, RelevantMemories, QuestionCategory
from agent_runtime.multi_agent.model_usage import model_usage_scope
from job_agent.fast_match import assess_skills
from job_agent.schemas import SkillAssessment, SkillEvidence
from benchmark_jev import prepared


def response(payload, choices=None, *, confidence=1):
    answers={}
    for key,q in payload['questions'].items():
        choice=(choices or {}).get(key,next(iter(q['criteria'])))
        keys=list(q['criteria']); rest=(1-confidence)/(len(keys)-1)
        answers[key]={'type':'choice','choice':choice,'confidence':confidence,
                      'probabilities':{k:confidence if k==choice else rest for k in keys}}
    return {'model':'fixture','answers':answers,'usage':{'input_tokens':20,'output_tokens':10}}


def service(handler):
    return FastDecisions(api_key='synthetic',enabled=True,transport=httpx.MockTransport(handler))


class Main(SemanticDecisions):
    def __init__(self,decisions):
        super().__init__(decisions=decisions);self.calls=[]
    def _invoke(self,schema,instruction,payload):
        self.calls.append((schema,payload))
        if schema is RelevantMemories:
            return schema(memory_ids=[m['memory_id'] for m in payload['memories']])
        return QuestionCategory(category='legal_or_identity')


def run():
    results=[]
    memories=[SimpleNamespace(memory_id=str(i),memory_key='key',display_text='synthetic',content={}) for i in range(3)]
    for kind in ['http_401','http_429','timeout','malformed','uncertain']:
        calls=[]
        def respond(request):
            calls.append(1)
            if kind.startswith('http_'):return httpx.Response(int(kind[5:]))
            if kind=='timeout':raise httpx.ReadTimeout('synthetic')
            if kind=='malformed':return httpx.Response(200,json={'answers':{}})
            return httpx.Response(200,json=response(json.loads(request.content),confidence=.5))
        evaluator=Main(service(respond))
        assert evaluator.relevant_memories('synthetic',memories)=={'0','1','2'}
        assert evaluator.question('synthetic')=='legal_or_identity'
        assert len(evaluator.calls)==2
        assert len(calls)==(2 if kind=='uncertain' else 1)
        results.append(kind+': fallback preserved')
    def partial(request):
        payload=json.loads(request.content)
        result=response(payload,{'m0':'relevant','m1':'irrelevant','m2':'unknown'})
        return httpx.Response(200,json=result)
    evaluator=Main(service(partial))
    assert evaluator.relevant_memories('query',memories)=={'0','1','2'}
    assert [m['memory_id'] for m in evaluator.calls[0][1]['memories']]==['0','1','2']
    results.append('Uncertain memory restores full context for main fallback')
    empty=Main(FastDecisions())
    assert empty.relevant_memories('query',[])==set() and not empty.calls
    secret_scoped=configured_decisions(environ={'TYPESAFE_API_KEY':'synthetic','TYPESAFE_ENABLED':'true',
        'TYPESAFE_CAREER_ENABLED':'false'},scope='career')
    assert not secret_scoped.enabled
    results.append('Career scope opt-in and empty input make no request')
    resume,jobs=prepared();job=jobs[0][1]
    fallback=[]
    def analyze(schema,instruction,text):
        subset=json.loads(text.split('Job analysis:\n')[1])
        fallback.append(subset)
        return SkillAssessment(matches=[SkillEvidence(requirement_id=r['requirement_id'],
            job_skill=r['canonical_name'],requirement_level=r['level'],match_status='missing',
            resume_evidence=[],confidence=0) for r in subset['requirements']],explanation='fixture',recommendations=[])
    choices={'r0':'e0','r1':'unknown','r2':'e2','r3':'e2','r4':'missing','r5':'missing'}
    decision=service(lambda request:httpx.Response(200,json=response(json.loads(request.content),choices)))
    with capture_routing() as trace:
        result=assess_skills(resume,job,analyze,decision)
    assert [r['requirement_id'] for r in fallback[0]['requirements']]==['r1']
    assert [m.requirement_id for m in result.matches]==[r.requirement_id for r in job.requirements]
    assert result.matches[0].resume_evidence==[resume.evidence[0].exact_text]
    assert trace[0]['main_model_calls']==1 and trace[0]['requests']==1
    results.append('Match selective fallback preserves IDs, order, original quotes')
    try:
        assess_skills(resume,job,lambda *args:SkillAssessment(matches=[],explanation='',recommendations=[]),decision)
    except ValueError:pass
    else:raise AssertionError('Incomplete main model result should fail')
    results.append('Malformed main fallback fails closed')
    class Meter:
        def __init__(self):self.starts=[];self.finishes=[]
        def reserve_model_call(self,*args,**kwargs):
            self.starts.append(kwargs);return {'input_tokens':100,'output_tokens':100}
        def finish_model_call(self,*args,**kwargs):self.finishes.append(kwargs)
    meter=Meter();decision.clear_cache()
    query={'x':{'type':'choice','instructions':'fixture','criteria':{'a':'A','unknown':'Unknown'}}}
    metered=service(lambda req:httpx.Response(200,json=response(json.loads(req.content))))
    with model_usage_scope(meter,'task','attempt'):
        metered.evaluate({},query,purpose='meter')
        cached=metered.evaluate({},query,purpose='meter')
    assert len(meter.starts)==1 and cached.cached and cached.requests==0
    assert meter.finishes==[{'input_tokens':20,'output_tokens':10}]
    results.append('Provider usage budget counted once; cache uses zero requests')
    print(json.dumps({'passed':results},indent=2))


if __name__=='__main__':run()
