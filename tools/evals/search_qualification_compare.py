"""Explicit paid model-quality check plus replay of already captured public postings."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import time
from uuid import uuid4


class Repository:
    def __init__(self,state):self.state=deepcopy(state)
    def get(self,_):return deepcopy(self.state)
    def change(self,_,update=None,**kwargs):
        self.state.update(update(self.get(_)) if update else kwargs)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--levels',action='store_true',help='Also check a senior request; skip the saved replay.')
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    os.environ.update(JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS='16',JOB_AGENT_TASK_MAX_INPUT_TOKENS='400000')
    from eregion.api.db import create_database
    from eregion.runtime.provider_usage import UsageLedger,usage_scope
    from eregion.runtime.career.qualification import record_many
    db=create_database('sqlite:///'+(args.output/'usage.sqlite3').as_posix(),create_schema_for_tests=True)
    ledger=UsageLedger(db.session_factory);task=str(uuid4());started=time.monotonic()
    request='Find 15 current junior data analyst positions in New York for my saved resume. Keep the role, seniority and location conditions.'
    state={'task_id':task,'status':'running','goal':request,'chat_revision':0,'messages':[]}
    fixtures=[
        ('graduate_paraphrase','Data Analyst','New York, NY','This position is designed for upcoming or recent graduates with zero to two years of post-graduation work experience. You will prepare supervised SQL reports.',True),
        ('senior_contradiction','Junior Data Analyst','New York, NY','Despite the title, this opening requires eight years of professional analytics experience and ownership of company analytics strategy. You will lead six analysts.',False),
        ('colleagues_not_candidate','Data Analyst','New York, NY','You must have seven years of professional experience and will mentor junior analysts with 0-2 years of experience.',False),
        ('remote_not_city','Junior Data Analyst','United States (Remote)','A junior analyst opening. Our company has offices in New York and Boston. The posting does not specify in which states this remote opening may be worked.',False),
        ('adjacent_occupation','Junior Investment Analyst','New York, NY','Evaluate investment opportunities, perform company valuation and execute equity trades. This is an entry-level financial investment role, not a data analyst opening.',False),
        ('borough','Junior Data Analyst','Brooklyn, NY','This is a junior data analyst position in our Brooklyn office. Develop supervised SQL reports and simple dashboards; new graduates are welcome.',True),
        ('negative_entry','Data Analyst','New York, NY','This is not an entry-level role. We require at least seven years leading production analytics platforms.',False),
        ('not_fixed_english_phrase','Data Analyst','New York, NY','Poste pour jeune diplômé sans expérience professionnelle requise. Vous travaillerez sous la supervision de notre analyste confirmé pour préparer des rapports SQL.',True),
        ('talent_pool','Junior Data Analyst','New York, NY','Register for our junior data analyst talent network. We are collecting interest for possible future opportunities; no specific vacancy is open.',False),
        ('optional_pool_link','Junior Data Analyst','New York, NY','We are hiring a junior data analyst now. Apply for this full-time role, requisition DA-123. New graduates will prepare supervised SQL reports. Separately, you may join our talent network for future roles.',True),
    ]
    jobs=[{'url':f'https://example.com/jobs/{label}','title':title,'location':place,'description':body}
          for label,title,place,body,_ in fixtures]
    try:
        with usage_scope(task_id=task,ledger=ledger):
            outputs=record_many(Repository(state),task,jobs)
            checked=[{'case':f[0],'expected':f[-1],'actual':r['qualified'],'assessment':r} for f,r in zip(fixtures,outputs)]
            (args.output/'gold-cases.json').write_text(json.dumps(checked,indent=2,ensure_ascii=False),encoding='utf-8')
            if args.levels:
                # The level is the user's, not a fixed junior rule: positive senior evidence
                # qualifies a senior request; a junior posting or no level evidence does not.
                senior_request='Find 5 current senior backend engineer positions in Chicago for my saved resume. Keep the role, seniority and location conditions.'
                senior=[('senior_explicit','Senior Backend Engineer','We seek a senior backend engineer with 6+ years building distributed services who will lead design reviews and mentor engineers.',True),
                    ('senior_by_duties','Backend Engineer','You will own the architecture of our payments platform, lead a team of four engineers and set technical direction. 7+ years of backend experience required.',True),
                    ('junior_for_senior_request','Backend Engineer I','Entry-level backend engineer role for recent graduates; you will learn under close mentorship from senior staff.',False),
                    ('no_level_evidence','Backend Engineer','Build APIs in Go and maintain our services.',False)]
                senior_state={'task_id':task,'status':'running','goal':senior_request,'chat_revision':0,'messages':[]}
                outs=record_many(Repository(senior_state),task,[{'url':f'https://example.com/senior/{c[0]}','title':c[1],
                    'location':'Chicago, IL','description':c[2]} for c in senior])
                checked+=[{'case':c[0],'expected':c[3],'actual':r['qualified'],'assessment':r} for c,r in zip(senior,outs)]
                (args.output/'gold-cases.json').write_text(json.dumps(checked,indent=2,ensure_ascii=False),encoding='utf-8')
                if any(c['actual']!=c['expected'] for c in checked):raise AssertionError('Model failed the hand-labelled semantic cases.')
                return
            if any(c['actual']!=c['expected'] for c in checked):raise AssertionError('Model failed the hand-labelled semantic cases; replay not run.')
            captured=json.loads((args.source/'transcript.json').read_text(encoding='utf-8'))
            state['goal']=captured['goal']
            jobs=list(captured.get('retrieved_jobs',{}).values())
            assessed=record_many(Repository(state),task,jobs)
            (args.output/'replay.json').write_text(json.dumps([{'title':j.get('title'),'location':j.get('location'),
                'assessment':a} for j,a in zip(jobs,assessed)],indent=2,ensure_ascii=False),encoding='utf-8')
    finally:
        usage=ledger.summary(task_id=task)
        (args.output/'summary.json').write_text(json.dumps({'usage':usage,'seconds':round(time.monotonic()-started,2),
            'source':str(args.source),'new_source_requests':0,'cost_usd':None,
            'kind':'paid semantic model check on synthetic cases and replayed public sources; not a new live job search'},indent=2),encoding='utf-8')
        db.close()


if __name__=='__main__':main()
