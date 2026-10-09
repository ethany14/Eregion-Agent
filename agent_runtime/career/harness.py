"""Career tools reuse existing workspace, evidence, writing, browser and interview services."""
import asyncio
import base64
import hashlib
import json
import re
from uuid import uuid4

from agent_runtime.task_loop import TEXT, function
from agent_runtime.auto_apply.contracts import ChatRequest, StartApplication
from agent_runtime.auto_apply.repository import DuplicateApplication
from agent_runtime.application_pack.rendering import render_cover_letter
from agent_runtime.workspace.types import ArtifactType
from job_agent.rendering import render_tailored_resume_text
from job_agent.pdf_rendering import render_tailored_resume_pdf
from .discovery import JobDiscovery
from .prompt import SYSTEM, APPLICATION_INSTRUCTION
from agent_runtime.browser.tools import BROWSER_TOOLS, BROWSER_NAMES, VISUAL_NAMES
from .alerts import AlertConfig, job_key


APP = {'application_id':TEXT}
ITEM = {'pack_id':TEXT,'item_id':TEXT}
TOOLS = [
    function('configure_job_alert','Create or update a daily autonomous job recommendation schedule explicitly requested in the cited user message. Timezone is required; never guess it. This schedules research only, not applications.',
        {'message_id':TEXT,'alert_id':TEXT,'config':AlertConfig.model_json_schema()},['message_id','config']),
    function('set_job_alert_enabled','Pause or resume a daily search at the user\'s explicit request.',
        {'message_id':TEXT,'alert_id':TEXT,'enabled':{'type':'boolean'}}),
    function('recommend_job','Recommend an actually read and scored job in this conversation, with fit reasons and uncertainties. Also adds it to the digest when this task was started by a schedule. No schedule is needed for a normal search.',
        {**APP,'reason':TEXT,'caveats':TEXT}),
    function('search_jobs','Supplementary HTTP/API search when browser search is unavailable or broader coverage helps. Prefer browser tools for normal job discovery, especially requested LinkedIn searches. Optional boards contain platform and company board token.',
        {'query':TEXT,'location':TEXT,'boards':{'type':'array','maxItems':5,'items':{'type':'object',
            'properties':{'platform':{'type':'string','enum':['greenhouse','lever']},'company':TEXT},
            'required':['platform','company'],'additionalProperties':False}},'limit':{'type':'integer','minimum':1,'maximum':20}},['query']),
    function('read_job','Capture the current browser job description before importing it. On a split results/detail page supply the observed detail region_ref and observation_id to exclude other jobs. URL may be the current page or its matching canonical posting link. Uses HTTP only for pages not open in the browser.',
        {'url':TEXT,'region_ref':TEXT,'observation_id':TEXT},['url']),
    function('import_job','Save a retrieved job or job text explicitly supplied in a user message. Returns application_id.',
        {'url':TEXT,'message_id':TEXT,'title':TEXT,'company':TEXT,'location':TEXT},['url']),
    function('list_jobs','Inspect saved jobs from the old workspace as well as this task.',{'query':TEXT},[]),
    function('inspect_job','Read a saved job, score, gaps and linked artifacts.',APP),
    function('score_job','Run the existing resume/JD match analysis and persist the actual score and requirement gaps.',APP),
    function('generate_materials','Create evidence-verified resume and/or cover-letter drafts for a saved job.',
        {**APP,'artifacts':{'type':'array','minItems':1,'maxItems':2,'items':{'type':'string','enum':['tailored_resume','cover_letter']}}}),
    function('inspect_materials','Read the current revisions, contents, verification and approval state.',{'pack_id':TEXT}),
    function('revise_material','Revise an existing document using the user feedback in the cited message.',{**ITEM,'message_id':TEXT}),
    function('remember_profile','Extract contact/profile corrections from an actual user message into reusable candidate details.',{'message_id':TEXT}),
    function('remember_evidence','Save a career fact explicitly supplied by the user, quoting their exact words. Use it for grounded materials.',
        {'message_id':TEXT,'quote':TEXT,'application_id':TEXT},['message_id','quote']),
    function('start_application','Open/focus an application. Auto uses this job\'s approved pack when available; original explicitly selects the saved PDF. Cannot submit.',
        {**APP,'pack_id':TEXT,'resume_source':{'type':'string','enum':['auto','original','tailored']}},['application_id']),
    function('open_application_url','Open a direct application URL with the saved original resume when the user wants to apply without analysis, including when the public job description is unreadable. Existing attempts retain their documents. Cannot submit.',{'url':TEXT}),
    function('inspect_application','Read the live browser state, outstanding question and outcome.',{'run_id':TEXT}),
    function('reply_application','Forward a user message verbatim to the linked application agent. Never invent an answer.',
        {'run_id':TEXT,'message_id':TEXT}),
    function('start_interview','Start job-specific practice using the existing mock interviewer; show its questions in this chat.',
        {**APP,'mode':{'type':'string','enum':['mixed','recruiter_screen','behavioral','project_deep_dive','role_specific']},
            'question_count':{'type':'integer','minimum':3,'maximum':12}},['application_id']),
    function('inspect_interview','Read the interview question, feedback and report.',{'interview_id':TEXT}),
    function('answer_interview','Send the user\'s original answer to the exact observed interview question.',
        {'interview_id':TEXT,'question_id':TEXT,'message_id':TEXT}),
    function('control_interview','Skip, end or resume an interview at the user\'s request. Cite the request message.',
        {'interview_id':TEXT,'action':{'type':'string','enum':['skip','end','resume']},'message_id':TEXT}),
]


class CareerHarness:
    tools, prompt = [*TOOLS,*BROWSER_TOOLS],SYSTEM

    def available_tools(self,state):
        tools=[t for t in self.tools if state.get('visual_fallback') or t['function']['name'] not in VISUAL_NAMES]
        if self.recommendation_run(state):
            allowed=BROWSER_NAMES|{'search_jobs','read_job','import_job','inspect_job','score_job','recommend_job'}
            return [t for t in tools if t['function']['name'] in allowed]
        return tools

    def recommendation_run(self,state):
        run_id=(state.get('initial_context') or {}).get('recommendation_run_id')
        if run_id and not state.get('chat_revision') and getattr(self,'alerts',None):
            run=self.alerts.get_run(run_id)
            if run['status'] in {'pending','running'}:return run
        return None

    def __init__(self, runtime, applications, repository, *, discovery=None, fit_service=None):
        self.runtime,self.applications,self.repository = runtime,applications,repository
        self.discovery = discovery or JobDiscovery()
        from api.services.workspace_service import WorkspaceAnalysisService
        self.analysis = WorkspaceAnalysisService(runtime.workspace,fit_service,evidence=runtime.evidence)
        self._resume_cache = (None,'')
        self._resume_issue = None
        self._browsing = None

    @property
    def browsing(self):
        if self._browsing is None:
            from agent_runtime.browser.manager import BrowsingManager
            self._browsing = BrowsingManager()
        return self._browsing

    def close(self):
        if self._browsing:self._browsing.close()

    def candidate(self):
        saved = self.applications.repository.saved_candidate()
        if saved.get('resume_base64'):
            from api.resume_routes import extract_pdf_text
            digest = hashlib.sha256(saved['resume_base64'].encode()).hexdigest()
            if self._resume_cache[0] != digest:
                from fastapi import HTTPException
                try:
                    text,_ = extract_pdf_text(base64.b64decode(saved['resume_base64']))
                    self._resume_issue = None
                except (HTTPException,ValueError):
                    text = ''
                    self._resume_issue = 'The saved PDF could not be read. Ask for a selectable-text PDF before scoring or writing.'
                self._resume_cache = (digest,text)
            text = self._resume_cache[1]
        else:
            try:text = self.runtime.resumes.default(self.runtime.owner_resolver.resolve().owner_id).extracted_text
            except (LookupError,AttributeError):text = ''
        return saved,text

    def observe(self,state):
        self.sync_submissions(state)
        saved,text = self.candidate()
        recommendation=self.recommendation_run(state)
        return {'candidate':saved.get('profile',{}),'resume_text':text[:40000],
            'scheduled_search':recommendation,
            'recommended_jobs':state.get('recommendations',[]),
            'previous_recommendations':self.alerts.recommended() if recommendation else [],
            'job_alerts':self.alerts.list() if getattr(self,'alerts',None) and not recommendation else [],
            'browser':state.get('browser'),
            'visual_fallback':bool(state.get('visual_fallback')),
            'resume_issue':self._resume_issue if saved.get('resume_base64') else None,
            'has_original_pdf':bool(saved.get('resume_base64')),
            'jobs':[self.job_summary(a) for a in state['jobs']],
            'materials':[self.materials(p,detail=False) for p in state['packs']],
            'applications':[self.application(r) for r in state['application_runs']],
            'capability_versions':{'application':{r:self.wait_token({'id':r}) for r in state['application_runs']}},
            'interviews':[self.interview(i) for i in state['interviews']]}

    def job_summary(self,application_id,*,detail=False):
        rt = self.runtime
        app = rt.workspace.get_application(application_id)
        job = rt.workspace.application_job(application_id)
        artifacts = rt.workspace.list_artifacts(application_id)
        match = next((a for a in reversed(artifacts) if a.artifact_type==ArtifactType.MATCH_REPORT),None)
        result = {'application_id':application_id,'title':job.title,'company':job.company,'url':job.canonical_url,
            'location':job.location,'status':app.status.value,'match_score':match.content.get('overall_score') if match else None}
        if match:result.update(self.requirement_summary(match.content))
        if detail:
            result.update(description=rt.workspace.current_snapshot(application_id).cleaned_job_description,
                match_report=match.content if match else None)
        return result

    @staticmethod
    def requirement_summary(report):
        """Counts by match status and the first few gaps, for the job card in chat."""
        matches = [m for m in report.get('matches') or [] if isinstance(m,dict)]
        counts = {status:sum(m.get('match_status')==status for m in matches)
            for status in ('matched','partial','missing','needs_confirmation')}
        missing = [*(report.get('missing_required_requirements') or []),*(report.get('missing_preferred_requirements') or [])]
        gaps = list(dict.fromkeys(str(m.get('canonical_name')).strip() for m in missing
            if isinstance(m,dict) and str(m.get('canonical_name') or '').strip()))[:3]
        return {'requirement_counts':counts if matches else None,'gaps':gaps}

    def materials(self,pack_id,*,detail=True):
        pack = self.runtime.pack_workflow.refresh_staleness(pack_id)
        items = []
        for item in self.runtime.packs.items(pack_id):
            if not detail:
                value = item.model_dump(mode='json')
                items.append({k:value[k] for k in ('pack_item_id','artifact_type','status','version','revision_count') if k in value})
                continue
            content = self.runtime.packs.artifact(pack_id,item.pack_item_id)
            text = (render_tailored_resume_text(content) if item.artifact_type=='tailored_resume'
                else render_cover_letter(content) if item.artifact_type=='cover_letter' else json.dumps(content)) if content else ''
            items.append({**item.model_dump(mode='json'),'text':text[:30000]})
        result = {'pack_id':pack_id,'application_id':pack.application_id,'status':pack.status.value,'items':items}
        if not detail:result['content_available_via'] = 'inspect_materials'
        return result

    def application(self,run_id):
        state = self.applications.repository.get(run_id)
        result = {k:state.get(k) for k in ('run_id','url','status','message','input_request','pending_fields',
            'fields','messages','account_request','confirmation','pause_requested') if k!='messages'}
        if state.get('account_request'):
            account = state['account_request']
            result['account_request'] = {k:account.get(k) for k in ('origin','mode','stage')}
            result['account_request']['consent_count'] = len(account.get('consents',[]))
            result['fields'] = [] # Account fields/page prose belong to the secure UI.
        return result

    def interview(self,identifier):
        view = self.runtime.mock_interviewer.view(identifier)
        if view.get('report_available'):view['report'] = self.runtime.mock_interviewer.interviews.report(identifier)
        return view

    def require_link(self,state,collection,identifier):
        if identifier not in state.get(collection,[]):raise ValueError('This result does not belong to this task. Inspect or import it first.')

    @staticmethod
    def user_message(state,identifier):
        message = next((m for m in state['messages'] if m['id']==identifier and m['role']=='user'),None)
        if not message:raise ValueError('Cite an actual user message from this conversation.')
        return message

    @staticmethod
    def key(state,action,args):
        message = next((m['id'] for m in reversed(state['messages']) if m['role']=='user'),'')
        return hashlib.sha256(json.dumps([state['task_id'],message,action,args],sort_keys=True).encode()).hexdigest()

    def analysis_fingerprint(self,resume_text,snapshot_id):
        inputs = [resume_text,snapshot_id,self.analysis.cache_signature()]
        return hashlib.sha256(json.dumps(inputs).encode()).hexdigest()

    def execute(self,task_id,name,args,*,call_id):
        state = self.repository.get(task_id)
        rt = self.runtime
        key = self.key(state,name,args)
        recommendation=self.recommendation_run(state)
        if recommendation and name not in {t['function']['name'] for t in self.available_tools(state)}:
            raise ValueError('This unattended task is authorized for job research and recommendations only.')
        if name in {'configure_job_alert','set_job_alert_enabled'}:
            self.user_message(state,args['message_id'])
            if not getattr(self,'alerts',None):raise ValueError('Scheduled searches are unavailable in this runtime.')
            identifier=args.get('alert_id')
            old=self.alerts.get(identifier) if identifier else None
            if name=='set_job_alert_enabled':
                if type(args['enabled']) is not bool:raise ValueError('Use a boolean enabled setting.')
                config={k:old[k] for k in AlertConfig.model_fields}|{'enabled':args['enabled']}
            else:config=args['config']
            return self.alerts.save(config,request_key=key,alert_id=identifier,expected_version=old['version'] if old else None)
        if name=='recommend_job':
            identifier=args['application_id'];self.require_link(state,'jobs',identifier)
            _,resume_text=self.candidate()
            application=rt.workspace.get_application(identifier)
            fingerprint=self.analysis_fingerprint(resume_text,application.current_snapshot_id)
            if not resume_text or state.get('analyses',{}).get(identifier)!=fingerprint:
                raise ValueError('Score this job against the current resume first.')
            job=self.job_summary(identifier,detail=True)
            if job['status'] in {'applied','interviewing','offer','rejected','withdrawn','archived'}:
                raise ValueError('This job is already applied to or closed; look for a new opportunity.')
            if job['match_score'] is None:raise ValueError('This job has no verified match score.')
            retrieved=next((j for j in state.get('retrieved_jobs',{}).values() if j.get('url') and job_key(j['url'])==job_key(job['url'])),None)
            if not retrieved:raise ValueError('Read the current posting before recommending it.')
            if not isinstance(args['reason'],str) or not 1<=len(args['reason'])<=2000 or not isinstance(args['caveats'],str) or len(args['caveats'])>2000:
                raise ValueError('Keep the recommendation reason and caveats concise.')
            payload={k:job[k] for k in ('application_id','title','company','location','url','match_score')}|{'reason':args['reason'],'caveats':args['caveats']}
            if recommendation:
                result=self.alerts.add(recommendation['run_id'],payload)
                if not result['added']:return result
                payload=result['recommendation']
            self.repository.change(task_id,lambda s:{'recommendations':[
                *[j for j in s.get('recommendations',[]) if job_key(j['url'])!=job_key(payload['url'])],payload][-30:]})
            return {'recommended':True,'recommendation':payload}
        if name in BROWSER_NAMES:
            if name in VISUAL_NAMES and not state.get('visual_fallback'):
                raise ValueError('Enable Visual browser backup in Your details before sending screenshots to the configured model.')
            revision=state['chat_revision']
            def active():
                current=self.repository.get(task_id)
                return current['chat_revision']==revision and not current.get('pause_requested') and current['status'] not in {'cancelled','completed'}
            result=self.browsing.call(task_id,name,args,visual=bool(state.get('visual_fallback')),active=active)
            summary={k:result.get(k) for k in ('url','heading','title','blocked','tabs','observation_id')}
            self.repository.change(task_id,browser=summary,active_browser='research')
            return result
        if name=='search_jobs':return self.discovery.search(**args)
        if name=='read_job':
            observed = self._browsing.inspect(task_id) if self._browsing else None
            from agent_runtime.auto_apply.contracts import public_https_url
            url=public_https_url(args['url'])
            same_job=bool(observed and job_key(url)==job_key(observed['url']))
            if args.get('region_ref') or same_job:
                # Capture the live, rendered description when a site requires JS.
                # The model cannot supply or invent this source text.
                read_args={k:args[k] for k in ('region_ref','observation_id') if k in args}
                read_args['job_only']=True
                first=self.browsing.call(task_id,'browser_read',read_args)
                if first.get('blocked'):raise ValueError('Finish the account/verification step before reading a public job description.')
                linked=any(c.get('href') and c['href'].startswith('https://') and job_key(c['href'])==job_key(url)
                    for c in first.get('controls',[]))
                if job_key(url)!=job_key(first['url']) and not (args.get('region_ref') and linked):
                    raise ValueError('The selected panel does not identify this job URL. Open that posting or select its actual detail panel.')
                pieces=[first.get('text','')]
                latest=first
                for offset in range(7000,min(first.get('text_length',0),35000),7000):
                    page_args={'text_offset':offset,'job_only':True}
                    if args.get('region_ref'):page_args.update(region_ref=args['region_ref'],observation_id=latest['observation_id'])
                    part=self.browsing.call(task_id,'browser_read',page_args)
                    if part.get('blocked') or part['url']!=first['url'] or part.get('primary_heading')!=first.get('primary_heading'):
                        raise ValueError('The page changed while reading. Inspect it again.')
                    pieces.append(part.get('text',''))
                    latest=part
                # These are character slices of one string, sometimes inside a word.
                description=''.join(pieces).strip()
                if len(description)<100:raise ValueError('This panel has too little job detail. Open the posting or expand its description before reading it.')
                job={'url':url,'title':first.get('primary_heading') or first.get('title'),'company':'','location':'',
                    'description':description,'source':'rendered_browser','page_url':first['url']}
            else:job = self.discovery.job(args['url'])
            self.repository.change(task_id,lambda s:{'retrieved_jobs':dict(list({**s.get('retrieved_jobs',{}),job['url']:job,args['url']:job}.items())[-20:])})
            return job
        if name=='import_job':
            if args.get('message_id'):
                message = self.user_message(state,args['message_id'])
                job = {'url':args['url'] or None,'description':message['text'],
                    **{k:args.get(k,'') for k in ('title','company','location')}}
            else:
                job = state.get('retrieved_jobs',{}).get(args['url']) or self.discovery.job(args['url'])
                if job.get('source')=='rendered_browser':
                    # Let the agent identify metadata in the captured panel, while
                    # keeping the actual source text as the evidence for each value.
                    normalize=lambda value:re.sub(r'\s+',' ',str(value)).strip().casefold()
                    evidence=normalize(job['description'])
                    job={**job,**{key:args[key] for key in ('title','company','location')
                        if args.get(key) and normalize(args[key]) in evidence}}
            if not job.get('description'):raise ValueError('Read or supply the job description first.')
            resolved = rt.workspace.save_workspace(cleaned_job_description=job['description'],source_url=job['url'],
                title=job.get('title'),company=job.get('company'),location=job.get('location'),
                extraction_metadata={'source':'career_chat'})
            self.repository.link(task_id,'jobs',resolved.application.application_id)
            # A direct browser flow can acquire its real description later.
            if job['url']:
                from agent_runtime.auto_apply.contracts import posting
                for run_id in state['application_runs']:
                    child=self.applications.repository.get(run_id)
                    if posting(child['url'])[1]==posting(job['url'])[1]:
                        self.repository.change(task_id,lambda s:{'application_links':{**s.get('application_links',{}),
                            run_id:{'application_id':resolved.application.application_id,'materials':child.get('material_refs',{})}}})
            return self.job_summary(resolved.application.application_id,detail=True)
        if name=='list_jobs':
            jobs = rt.workspace.list_applications(search=args.get('query'),limit=30)
            for app in jobs:self.repository.link(task_id,'jobs',app.application_id)
            return {'jobs':[self.job_summary(a.application_id) for a in jobs]}
        if 'application_id' in args:self.require_link(state,'jobs',args['application_id'])
        if 'pack_id' in args and args['pack_id']:self.require_link(state,'packs',args['pack_id'])
        if 'run_id' in args:self.require_link(state,'application_runs',args['run_id'])
        if 'interview_id' in args:self.require_link(state,'interviews',args['interview_id'])
        if name=='inspect_job':
            # A new conversation can discover a saved job's existing materials.
            # Linking them here keeps subsequent inspect/revise calls scoped to
            # this verified job instead of forcing another generation.
            packs = rt.packs.list_for_application(args['application_id'])
            for pack in packs:self.repository.link(task_id,'packs',pack.pack_id)
            return {'materials':[self.materials(pack.pack_id,detail=False) for pack in packs],
                    **self.job_summary(args['application_id'],detail=True)}
        if name=='score_job':
            saved,text = self.candidate()
            if not text:raise ValueError('Attach a resume in this chat before comparing fit.')
            app = rt.workspace.get_application(args['application_id'])
            fingerprint = self.analysis_fingerprint(text,app.current_snapshot_id)
            if state.get('analyses',{}).get(app.application_id)!=fingerprint:
                asyncio.run(self.analysis.analyze(app.application_id,snapshot_id=app.current_snapshot_id,
                    resume_text=text,expected_version=app.version))
                self.repository.change(task_id,lambda s:{'analyses':{**s.get('analyses',{}),app.application_id:fingerprint}})
            return self.job_summary(app.application_id,detail=True)
        if name=='generate_materials':
            artifacts = args['artifacts']
            if not artifacts or len(artifacts)>2 or set(artifacts)-{'tailored_resume','cover_letter'}:raise ValueError('Choose resume and/or cover letter.')
            app = rt.workspace.get_application(args['application_id'])
            pack = rt.pack_workflow.create(app.application_id,expected_version=app.version,
                idempotency_key=key,scope_to_inputs=True)
            self.repository.link(task_id,'packs',pack.pack_id)
            for artifact in dict.fromkeys(artifacts):
                existing = next((i for i in rt.packs.items(pack.pack_id) if i.artifact_type==artifact),None)
                if existing:continue
                rt.pack_workflow.generate(pack.pack_id,artifact_type=artifact,
                    expected_version=rt.packs.get(pack.pack_id).version,idempotency_key=f'{key}:{artifact}')
            return self.materials(pack.pack_id)
        if name=='inspect_materials':return self.materials(args['pack_id'])
        if name=='revise_material':
            message = self.user_message(state,args['message_id'])
            item = rt.packs.item(args['pack_id'],args['item_id'])
            rt.pack_workflow.regenerate(args['pack_id'],item.pack_item_id,expected_version=item.version,
                idempotency_key=key,feedback=message['text'])
            return self.materials(args['pack_id'])
        if name=='remember_profile':
            from agent_runtime.auto_apply.resume_profile import extract_chat_profile
            message = self.user_message(state,args['message_id'])
            parsed = extract_chat_profile(message['text'])
            saved = self.applications.repository.saved_candidate()
            self.applications.repository.save_candidate({**saved['profile'],**parsed.get('profile',{})})
            return {'profile':self.applications.repository.saved_candidate()['profile'], 'message':parsed.get('message')}
        if name=='start_application':return self.start_application(state,args,key)
        if name=='open_application_url':return self.open_application_url(state,args,key)
        if name=='remember_evidence':
            message = self.user_message(state,args['message_id'])
            quote = args['quote'].strip()
            if not quote or len(quote)>4000 or quote not in message['text']:
                raise ValueError('Quote the user\'s exact career fact. Do not add or infer facts.')
            previous = state.get('saved_evidence',{}).get(key)
            if previous:return {'evidence_id':previous,'saved':True}
            evidence = rt.evidence.create_candidate(category='experience',claim_text=quote,
                source_type='user_attested',exact_quote=quote)
            confirmed = rt.evidence.confirm(evidence.evidence_id,evidence.version)
            if args.get('application_id'):
                rt.evidence.link_to_application(confirmed.evidence_id,args['application_id'],expected_version=confirmed.version)
            self.repository.change(task_id,lambda s:{'saved_evidence':{**s.get('saved_evidence',{}),key:confirmed.evidence_id}})
            return {'evidence_id':confirmed.evidence_id,'saved':True,'quote':quote}
        if name=='inspect_application':
            self.repository.change(task_id,active_application_run=args['run_id'],active_browser='application')
            return self.application(args['run_id'])
        if name=='reply_application':
            message = self.user_message(state,args['message_id'])
            self.applications.chat(args['run_id'],ChatRequest(text=message['text'],message_id=message['id'],
                visual_fallback=state['visual_fallback']))
            return self.application(args['run_id'])
        if name=='start_interview':
            interview = rt.mock_interviewer.start(args['application_id'],mode=args.get('mode','mixed'),
                target_question_count=args.get('question_count',5),idempotency_key=key)
            self.repository.link(task_id,'interviews',interview.mock_interview_id)
            return self.interview(interview.mock_interview_id)
        if name=='inspect_interview':return self.interview(args['interview_id'])
        if name in {'answer_interview','control_interview'}:
            message = self.user_message(state,args['message_id'])
            current = rt.mock_interviewer.interviews.get(args['interview_id'])
            if name=='answer_interview':
                if current.current_question_id!=args['question_id']:raise ValueError('The interview question changed. Inspect it before sending this answer.')
                rt.mock_interviewer.answer(current.mock_interview_id,message['text'],expected_version=current.version,
                    idempotency_key=f'career:{message["id"]}:{args["question_id"]}')
            else:
                if args['action'] not in {'skip','end','resume'}:raise ValueError('Unsupported interview control.')
                getattr(rt.mock_interviewer,args['action'])(current.mock_interview_id,expected_version=current.version,idempotency_key=key)
            return self.interview(current.mock_interview_id)
        raise ValueError('Unknown career capability.')

    def open_application_url(self,state,args,key):
        from agent_runtime.auto_apply.contracts import posting
        saved,_ = self.candidate()
        if not saved.get('resume_base64'):raise ValueError('Upload a resume PDF before opening this application.')
        request = StartApplication(url=args['url'],profile=saved['profile'],resume_base64=saved['resume_base64'],
            idempotency_key=key,save_as_default=False,auto_submit=False,automation_mode='hybrid',
            consent_policy='ask',visual_fallback=state['visual_fallback'],initial_message=APPLICATION_INSTRUCTION)
        try:run=self.applications.start(request,material_refs={})
        except DuplicateApplication as exc:
            run=self.applications.repository.get(exc.run_id)
            if run['status'] in {'cancelled','failed'}:run=self.applications.resume(run['run_id'],run['version'])
        self.repository.link(state['task_id'],'application_runs',run['run_id'],active_application_run=run['run_id'],active_browser='application')
        refs=run.get('material_refs',{})
        application_id=next((a for a in state['jobs'] if self.runtime.workspace.application_job(a).canonical_url
            and posting(self.runtime.workspace.application_job(a).canonical_url)[1]==posting(run['url'])[1]),None)
        if refs:
            application_id=self.runtime.packs.get(next(iter(refs.values()))['pack_id']).application_id
            self.repository.link(state['task_id'],'jobs',application_id)
            for ref in refs.values():self.repository.link(state['task_id'],'packs',ref['pack_id'])
        self.repository.change(state['task_id'],lambda s:{'application_links':{**s.get('application_links',{}),
            run['run_id']:{'application_id':application_id,'materials':refs}}})
        latest=self.repository.get(state['task_id'])
        if latest['status']=='cancelled' and run['status'] not in {'submitted','submitting','submission_unknown','cancelled','failed'}:
            self.applications.cancel(run['run_id'],self.applications.repository.get(run['run_id'])['version'])
        elif latest.get('pause_requested'):self.control(latest,'pause')
        return {**self.application(run['run_id']),'note':'No fit score or job description was invented. This starts only the browser application.'}

    def start_application(self,state,args,key):
        rt = self.runtime
        app = rt.workspace.get_application(args['application_id'])
        job = rt.workspace.application_job(app.application_id)
        if not job.canonical_url:raise ValueError('This saved job needs a public application URL.')
        saved,_ = self.candidate()
        encoded, cover = saved.get('resume_base64'),None
        material_refs = {}
        source = args.get('resume_source','auto')
        if source not in {'auto','original','tailored'}:raise ValueError('Choose auto, original or tailored materials.')
        if source=='original' and args.get('pack_id'):raise ValueError('Choose a pack or the original resume, not both.')
        if not args.get('pack_id') and source!='original':
            candidates = rt.packs.list_for_application(app.application_id)
            current = candidates[0] if candidates else None
            if current:
                self.repository.link(state['task_id'],'packs',current.pack_id)
                args={**args,'pack_id':current.pack_id}
            elif source=='tailored':raise ValueError('Generate and review this job\'s materials first.')
        if args.get('pack_id'):
            pack = rt.pack_workflow.refresh_staleness(args['pack_id'])
            if pack.application_id!=app.application_id or pack.snapshot_id!=app.current_snapshot_id or pack.status.value=='stale':
                raise ValueError('Use current materials for this exact job.')
            for item in rt.packs.items(pack.pack_id):
                if item.artifact_type not in {'tailored_resume','cover_letter'}:continue
                if item.status.value!='approved':raise ValueError('The generated documents need review in this chat before being used for an application.')
                content = rt.packs.artifact(pack.pack_id,item.pack_item_id)
                if item.artifact_type=='tailored_resume':encoded = base64.b64encode(render_tailored_resume_pdf(content)).decode()
                else:cover = render_cover_letter(content)
                material_refs[item.artifact_type] = {'pack_id':pack.pack_id,'item_id':item.pack_item_id,'version':item.version}
        if not encoded:raise ValueError('Upload the original resume PDF, or approve a tailored resume first.')
        request = StartApplication(url=job.canonical_url,profile=saved['profile'],resume_base64=encoded,
            idempotency_key=key,automation_mode='hybrid',auto_submit=False,consent_policy='ask',
            save_as_default=False,cover_letter=cover,visual_fallback=state['visual_fallback'],
            initial_message=APPLICATION_INSTRUCTION)
        try:run = self.applications.start(request,material_refs=material_refs)
        except DuplicateApplication as exc:
            run = self.applications.repository.get(exc.run_id)
            if run['status'] in {'submitted','submitting','submission_unknown'}:
                # Never relabel an earlier submission as having used the new pack.
                self.repository.link(state['task_id'],'application_runs',run['run_id'],active_application_run=run['run_id'],active_browser='application')
                self.repository.change(state['task_id'],lambda s:{'application_links':{**s.get('application_links',{}),
                    run['run_id']:{'application_id':app.application_id,'materials':run.get('material_refs',{})}}})
                return {**self.application(run['run_id']),'note':'This job already has a submission. No new materials were uploaded.'}
            previous = run.get('material_refs',{})
            # Generated PDFs include timestamps, so compare pinned versions for tailored resumes.
            same_resume = (previous.get('tailored_resume')==material_refs.get('tailored_resume')
                if material_refs.get('tailored_resume') else self.applications.repository.resume(run['run_id'])==base64.b64decode(encoded))
            if not same_resume or previous!=material_refs or run.get('cover_letter')!=cover or run['profile']!=request.profile.model_dump():
                run = self.applications.replace_materials(run['run_id'],base64.b64decode(encoded),cover,
                    profile=request.profile.model_dump(),material_refs=material_refs)
            elif run['status'] in {'cancelled','failed'}:
                run = self.applications.resume(run['run_id'],run['version'])
        self.repository.link(state['task_id'],'application_runs',run['run_id'],active_application_run=run['run_id'],active_browser='application')
        self.repository.change(state['task_id'],lambda s:{'application_links':{**s.get('application_links',{}),
            run['run_id']:{'application_id':app.application_id,'materials':material_refs}}})
        latest = self.repository.get(state['task_id'])
        if latest['status']=='cancelled' and run['status'] not in {'submitted','submitting','submission_unknown','cancelled','failed'}:
            self.applications.cancel(run['run_id'],self.applications.repository.get(run['run_id'])['version'])
        elif latest.get('pause_requested'):
            self.control(latest,'pause')
        return self.application(run['run_id'])

    def sync_submissions(self,state):
        for run_id,link in state.get('application_links',{}).items():
            if not link.get('application_id'):continue
            child = self.applications.repository.get(run_id)
            if child['status']=='submitted' and child.get('confirmation'):
                from agent_runtime.workspace.errors import StaleApplicationError
                try:
                    self.runtime.workspace.record_browser_submission(link['application_id'],run_id=run_id,
                        confirmation=child['confirmation'])
                except StaleApplicationError:
                    if not self.runtime.workspace.get_application(link['application_id']).applied_at:raise

    def validate_wait(self,state,args):
        if args['kind']!='application':raise ValueError('Only browser applications currently run in the background; other tools return their result directly.')
        self.require_link(state,'application_runs',args['id'])

    def wake(self,state):
        wait = state.get('wait') or {}
        if wait.get('kind')=='application':
            child = self.applications.repository.get(wait['id'])
            return child['status'] not in {'queued','running','submitting'} and self.wait_token(wait)!=wait.get('token')
        return False

    def wait_token(self,args):
        child = self.applications.repository.get(args['id'])
        account = child.get('account_request') or {}
        return [child['status'],child.get('chat_revision'),(child.get('input_request') or {}).get('id'),child.get('review_digest'),
            [account.get(k) for k in ('origin','mode','stage')],
            [c['key'] for c in account.get('consents',[])],
            child.get('message') if child['status']=='needs_input' else None]

    def validate_finish(self,state):
        for run_id in state['application_runs']:
            child = self.applications.repository.get(run_id)
            if child['status'] in {'queued','running','submitting'}:raise ValueError('A linked application is still working. Wait for its result or continue independent work.')

    def control(self,state,action):
        if action not in {'pause','resume'}:return
        for run_id in state['application_runs']:
            child = self.applications.repository.get(run_id)
            if child['status'] in {'submitted','submission_unknown','cancelled','failed','submitting'}:continue
            if action=='resume' and not child.get('pause_requested'):continue
            self.applications.chat(run_id,ChatRequest(text='pause' if action=='pause' else 'continue',
                message_id=str(uuid4()),visual_fallback=state['visual_fallback']))
