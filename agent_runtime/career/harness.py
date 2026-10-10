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
    function('screen_jobs','Quickly rank a batch of actually observed job links against a short search query. Use after browser search to choose which descriptions to read and score. Advisory only; cannot replace score_job or establish eligibility. Unknowns remain available to you.',
        {'urls':{'type':'array','minItems':1,'maxItems':20,'items':TEXT},'query':TEXT}),
    function('read_job','Capture the current browser job description before importing it. On a split results/detail page supply the observed detail region_ref and observation_id to exclude other jobs. URL may be the current page or its matching canonical posting link. Uses HTTP only for pages not open in the browser.',
        {'url':TEXT,'region_ref':TEXT,'observation_id':TEXT},['url']),
    function('import_job','Save a retrieved job. Only for a pasted JD, supply message_id and its literal job_text excerpt (never the task instruction). Returns application_id.',
        {'url':TEXT,'message_id':TEXT,'job_text':TEXT,'title':TEXT,'company':TEXT,'location':TEXT},['url']),
    function('list_jobs','Inspect saved jobs from the old workspace as well as this task.',{'query':TEXT},[]),
    function('inspect_job','Read a saved job, score, gaps and linked artifacts.',APP),
    function('score_job','Run the existing resume/JD match analysis and persist the actual score and requirement gaps.',APP),
    function('generate_materials','Prepare verified drafts, reusing saved drafts for unchanged inputs. Only when the user explicitly requests a fresh/new set, use fresh=true with their message_id; preserves old documents. Use revise_material for feedback on an existing document.',
        {**APP,'artifacts':{'type':'array','minItems':1,'maxItems':2,'items':{'type':'string','enum':['tailored_resume','cover_letter']}},
            'fresh':{'type':'boolean'},'message_id':TEXT},['application_id','artifacts']),
    function('inspect_materials','Read the current revisions, contents, verification and approval state.',{'pack_id':TEXT}),
    function('revise_material','Revise an existing document using the user feedback in the cited message.',{**ITEM,'message_id':TEXT}),
    function('remember_profile','Extract contact/profile corrections from an actual user message into reusable candidate details.',{'message_id':TEXT}),
    function('remember_evidence','Save a career fact explicitly supplied by the user, quoting their exact words. Use it for grounded materials.',
        {'message_id':TEXT,'quote':TEXT,'application_id':TEXT},['message_id','quote']),
    function('start_application','Open/focus an application using this job\'s current approved documents. Omit pack_id to use explicit per-document choices across packs. Optional pack_id must not conflict with an explicit choice; missing document types use valid explicit choices. Original explicitly selects the saved PDF. Cannot submit.',
        {**APP,'pack_id':TEXT,'resume_source':{'type':'string','enum':['auto','original','tailored']}},['application_id']),
    function('open_application_url','Open a direct application URL with the saved original resume when the user wants to apply without analysis, including when the public job description is unreadable. Existing attempts retain their documents. Cannot submit.',{'url':TEXT}),
    function('inspect_application','Read the live browser progress, outstanding question and verified outcome. Observed answers are the actual review outcome. include_fields returns compact controls; request field_key only to investigate one original control. Do not reread the entire form to report its outcome. Wait while the worker is running.',{'run_id':TEXT,'include_fields':{'type':'boolean'},'field_key':TEXT},['run_id']),
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
    # These reads do not alter browser observation tokens or external state.
    batchable_tools = frozenset({'list_jobs', 'inspect_job', 'inspect_materials', 'inspect_interview'})

    def available_tools(self,state):
        from agent_runtime.fast_decisions import configured_decisions
        tools=[t for t in self.tools if state.get('visual_fallback') or t['function']['name'] not in VISUAL_NAMES]
        # Offer operations for resources that actually exist in this process.
        # browser_open remains available for independent research at any time.
        if not self._browsing or not self._browsing.inspect(state['task_id']):
            tools=[t for t in tools if t['function']['name'] not in BROWSER_NAMES or t['function']['name']=='browser_open']
        latest=next((m for m in reversed(state.get('messages',[])) if m.get('role')=='user'),None)
        children=[self.applications.repository.get(rid) for rid in state.get('application_runs',[])]
        if latest and children and all(any(m.get('id')==latest['id'] for m in child.get('messages',[])) for child in children):
            tools=[t for t in tools if t['function']['name']!='reply_application']
        if not configured_decisions().enabled:
            tools = [t for t in tools if t['function']['name'] != 'screen_jobs']
        if self.recommendation_run(state):
            allowed=BROWSER_NAMES|{'search_jobs','screen_jobs','read_job','import_job','inspect_job','score_job','recommend_job'}
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
        if fit_service is None and getattr(runtime, 'database', None):
            from agent_runtime.analysis_cache import AnalysisCache
            from agent_runtime.memory.policy import LocalOwnerResolver
            from api.services.fit_analysis_service import FitAnalysisService
            fit_service = FitAnalysisService(analysis_cache=AnalysisCache(runtime.database.session_factory,
                owner=(getattr(runtime, 'owner_resolver', None) or LocalOwnerResolver()).resolve().owner_id))
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
            'research_pages': [{k: (v[:400] if k == 'excerpt' else [{a:b for a,b in link.items() if a in {'url','label'}} for link in v[:6]] if k == 'links' else v) for k,v in page.items() if k in {'url','title','blocked','links','excerpt'}} for page in state.get('research_pages', [])],
            'visual_fallback':bool(state.get('visual_fallback')),
            'resume_issue':self._resume_issue if saved.get('resume_base64') else None,
            'has_original_pdf':bool(saved.get('resume_base64')),
            'jobs':[self.job_summary(a) for a in state['jobs']],
            'materials':[self.materials(p,detail=False) for p in state['packs']],
            'applications':[self.application(r) for r in state['application_runs']],
            'material_choices':{a:self.material_choices(a) for a in state['jobs']},
            'capability_versions':{'application':{r:self.wait_token({'id':r}) for r in state['application_runs']}},
            'interviews':[self.interview(i) for i in state['interviews']]}

    def job_summary(self,application_id,*,detail=False):
        rt = self.runtime
        app = rt.workspace.get_application(application_id)
        job = rt.workspace.application_job(application_id)
        artifacts = rt.workspace.list_artifacts(application_id)
        attached = [e.occurred_at for e in rt.workspace.list_events(application_id)
                    if e.event_type.value == 'snapshot_attached']
        boundary = max(attached) if attached else app.created_at
        match = next((a for a in reversed(artifacts) if a.artifact_type==ArtifactType.MATCH_REPORT
                      and a.created_at >= boundary),None)
        result = {'application_id':application_id,'title':job.title,'company':job.company,'url':job.canonical_url,
            'location':job.location,'status':app.status.value,'match_score':match.content.get('overall_score') if match else None,
            'result_at':(match.created_at if match else app.created_at).isoformat()}
        if match:
            result.update(self.requirement_summary(match.content))
            result['match_overview'] = self.match_overview(match.content)
        if detail:
            result.update(description=rt.workspace.current_snapshot(application_id).cleaned_job_description,
                match_report=match.content if match else None)
        return result

    @staticmethod
    def match_overview(report):
        matches = [m for m in report.get('matches', []) if isinstance(m, dict)]
        result = {'explanation': report.get('explanation', ''),
                  'detail_hint': 'This is the completed scoring result. Full citations remain in match_report; read a specific path only when a detail is needed.'}
        for status in ('matched', 'partial', 'missing', 'needs_confirmation'):
            rows = [m for m in matches if m.get('match_status') == status]
            result[status] = [{'requirement': m.get('job_skill'), 'level': m.get('requirement_level')}
                              for m in (rows[:8] if status == 'matched' else rows)]
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
                items.append({k:value[k] for k in ('pack_item_id','artifact_type','status','version','revision_count','verification') if k in value})
                continue
            content = self.runtime.packs.artifact(pack_id,item.pack_item_id) if item.status.value in {'awaiting_review', 'approved'} else None
            text = (render_tailored_resume_text(content) if item.artifact_type=='tailored_resume'
                else render_cover_letter(content) if item.artifact_type=='cover_letter' else json.dumps(content)) if content else ''
            items.append({**item.model_dump(mode='json'),'text':text})
        overview = [{**{k:item.get(k) for k in ('pack_item_id','artifact_type','status','version')},
            'verification':item.get('verification'),
            'document_text_path':['items', str(index), 'text'] if detail and item.get('text') else None}
            for index,item in enumerate(items)]
        result = {'pack_id':pack_id,'application_id':pack.application_id,'status':pack.status.value,'version':pack.version,'items':items,
            'material_overview':overview,
            'detail_hint':'Generation status and verification are in material_overview. To inspect wording, read document_text_path directly; do not page through all item metadata. Awaiting review means generation is finished and the user reviews next. Complete source/verification evidence remains in items.'}
        if not detail:result['content_available_via'] = 'inspect_materials'
        return result

    def material_choices(self, application_id):
        from agent_runtime.application_pack.selection import current_materials, latest_materials
        rt = self.runtime
        latest = {i.pack_item_id for p,i in latest_materials(rt.workspace,rt.packs,rt.pack_workflow,application_id)}
        return [{'pack_id':p.pack_id,'item_id':i.pack_item_id,'type':i.artifact_type,
            'status':i.status.value,'version':i.version,'verified':i.verification.passed if i.verification else None,
            'has_artifact':bool(i.artifact_id),'is_latest_attempt':i.pack_item_id in latest,
            'requires_explicit_selection':i.pack_item_id not in latest}
            for p,i in current_materials(rt.workspace,rt.packs,rt.pack_workflow,application_id)]

    def application(self,run_id,*,include_fields=False,field_key=None):
        state = self.applications.repository.get(run_id)
        delivered=[m['id'] for m in state.get('messages',[]) if m.get('role')=='user'][-8:]
        if state['status'] in {'queued','running','submitting'} and not include_fields and not field_key:
            return {k:state.get(k) for k in ('run_id','status','version','material_refs')} | {
                'working':True,'delivered_user_message_ids':delivered,
                'next':'The browser worker is still executing. Use wait_for_result(kind=application,id=run_id) or do independent work. Fields from earlier pages are not a final result. Use inspect_application(field_key=...) only to investigate a specific working control.'}
        result = {k:state.get(k) for k in ('run_id','url','status','message','input_request','pending_fields',
            'fields','messages','account_request','confirmation','pause_requested','material_refs','agent_reason') if k!='messages'}
        result['version'] = state.get('version')
        result['delivered_user_message_ids'] = delivered
        controls = state.get('review_fields',[]) if state['status']=='awaiting_review' else state.get('fields',[])
        # Review values are a result, not a navigation index into DOM metadata.
        # Preserve the complete original through a targeted read when it matters.
        compact = []
        for field in controls:
            if field.get('kind')=='password':continue
            answer = {k:field.get(k) for k in ('key','label','value')}
            if field.get('invalid') or field.get('error'):
                answer.update({k:field[k] for k in ('invalid','error') if k in field})
            if len(str(answer.get('value') or ''))>300:
                answer['value']={'filled':True,'characters':len(str(answer['value'])),
                    'detail':'Read this field_key for its complete value.'}
            compact.append(answer)
        if state['status']=='awaiting_review':
            result['observed_answers'] = compact
            result['documents']=[{'label':f.get('label'),'filename':f.get('value')}
                for f in state.get('fields',[]) if f.get('kind')=='file']
            result.pop('fields',None)
            result.pop('agent_reason',None)
            result.pop('account_request',None)
            result['detail_hint'] = ('observed_answers contains the actual reviewed controls and is sufficient to report the outcome. '
                'User facts and intended answers are not proof of what the website contains. '
                'If a specific value is unclear, inspect field_key for that original control, not the whole archive. '
                'awaiting_review means prepared for the user to review; it does not mean submitted.')
        elif include_fields:
            result['fields']=compact
        if field_key:
            field = next((f for f in controls if f.get('key')==field_key),None)
            if field is None:raise ValueError('Unknown field_key. Use a key from the current application observation.')
            if field.get('kind')=='password' or state.get('account_request'):
                raise ValueError('Account controls are available only through the secure interface.')
            result={'run_id':run_id,'status':state['status'],'version':state.get('version'),
                'control':field,'detail_hint':'This is the requested original control, with its complete value and constraints.'}
        if state.get('account_request'):
            account = state['account_request']
            result['account_request'] = {k:account.get(k) for k in ('origin','mode','stage')}
            result['account_request']['consent_count'] = len(account.get('consents',[]))
            result['fields'] = [] # Account fields/page prose belong to the secure UI.
        if state['status']=='needs_input' and not include_fields and state.get('input_request'):
            result.pop('fields',None)
            result['detail_hint']='Forward this outstanding question to the user. If an actual user message already answers it, forward that message once. Detailed controls remain available with include_fields=true.'
        return result

    def interview(self,identifier):
        view = self.runtime.mock_interviewer.view(identifier)
        if view.get('report_available'):view['report'] = self.runtime.mock_interviewer.interviews.report(identifier)
        if view['interview']['status'] == 'failed':
            failure = view.get('failure') or {}
            view.update(error='Interview processing failed; the answer remains saved.',
                error_code=failure.get('error_code', 'interview_failed'),
                next=failure.get('next', 'Inspect the failure and retry only the failed stage.'))
        return view

    def require_link(self,state,collection,identifier):
        if identifier not in state.get(collection,[]):raise ValueError('This result does not belong to this task. Inspect or import it first.')

    def link_job_pack(self, state, pack_id):
        if pack_id in state.get('packs', []): return
        pack = self.runtime.packs.get(pack_id)
        self.require_link(state, 'jobs', pack.application_id)
        self.repository.link(state['task_id'], 'packs', pack_id)

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
            from agent_runtime.browser.evidence import research_page
            page = research_page(result)
            def remember(current):
                pages = list(current.get('research_pages', []))
                prior = next((p for p in pages if p.get('url') == page['url']), None)
                if not page['links'] and prior:
                    page['links'] = prior.get('links', [])
                pages = [p for p in pages if p.get('url') != page['url']]
                return {'browser': summary, 'active_browser': 'research', 'research_pages': [*pages, page][-8:]}
            self.repository.change(task_id, remember)
            return result
        if name=='search_jobs':
            result = self.discovery.search(**args)
            jobs = result.get('jobs', [])
            self.repository.change(task_id, lambda s: {'search_candidates': dict(list({
                **s.get('search_candidates', {}), **{j['url']: j for j in jobs}}.items())[-60:])})
            from agent_runtime.fast_decisions import configured_decisions
            if jobs and configured_decisions().enabled:
                screened = self.screen(task_id, state, jobs, args['query'] + ' ' + args.get('location', ''))
                result.update(screened)
            return result
        if name=='screen_jobs':
            candidates = {**state.get('search_candidates', {}), **state.get('retrieved_jobs', {})}
            observed = self._browsing.inspect(task_id) if self._browsing else None
            if observed and not observed.get('blocked'):
                for control in observed.get('controls', []):
                    url = control.get('href')
                    if url and url.startswith('https://'):
                        candidates.setdefault(url, {'url':url,'title':control.get('label',''),
                                                   'context':control.get('context','')})
            urls = list(dict.fromkeys(args['urls']))
            if not 1 <= len(urls) <= 20 or any(url not in candidates for url in urls):
                raise ValueError('Screen only links from observed browser/search results or retrieved jobs.')
            return self.screen(task_id, state, [candidates[url] for url in urls], args['query'])
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
            retrieved = next((job for job in state.get('retrieved_jobs', {}).values()
                              if job.get('url') and job_key(job['url']) == job_key(args['url'])), None)
            quote = None
            if args.get('job_text'):
                message = self.user_message(state, args.get('message_id'))
                quote = args['job_text'].strip()
                if not quote or quote not in message['text']:
                    raise ValueError('job_text must be a literal job-description excerpt from the cited user message.')
            if retrieved:
                # Captured same-posting evidence has precedence, even if a tool
                # mistakenly quotes the user's task instruction as job_text.
                job = retrieved
            elif quote:
                source_key = hashlib.sha256((message['id'] + ':' + quote).encode()).hexdigest()
                checked = state.get('job_source_checks', {}).get(source_key)
                if checked is None:
                    from agent_runtime.semantics import SemanticDecisions
                    from job_agent.model import shared_model
                    checked = SemanticDecisions(model=shared_model(purpose='fast')).pasted_job_text(
                        message['text'], quote)
                    self.repository.change(task_id, lambda current: {'job_source_checks': dict(list({
                        **current.get('job_source_checks', {}), source_key: checked}.items())[-16:])})
                if not checked:
                    raise ValueError('The quote is not identifiable as a pasted job description. Read the posting URL or ask the user for the actual JD; task instructions and search preferences are not job evidence.')
                job = {'url':args['url'] or None, 'description':quote, 'source':'user_job_quote',
                       **{k:args.get(k,'') for k in ('title','company','location')}}
            elif args.get('message_id'):
                raise ValueError('A message ID alone does not identify job text. Use read_job for the posting URL, or provide job_text quoting the pasted JD; never import the task instruction.')
            else:
                job = self.discovery.job(args['url'])
            if job.get('source')=='rendered_browser':
                # Metadata must be present in the captured panel as well.
                normalize=lambda value:re.sub(r'\s+',' ',str(value)).strip().casefold()
                evidence=normalize(job['description'])
                job={**job,**{key:args[key] for key in ('title','company','location')
                    if args.get(key) and normalize(args[key]) in evidence}}
            if not job.get('description'):raise ValueError('Read or supply the job description first.')
            resolved = rt.workspace.save_workspace(cleaned_job_description=job['description'],source_url=job['url'],
                title=job.get('title'),company=job.get('company'),location=job.get('location'),
                extraction_metadata={'source':job.get('source','career_retrieval')})
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
        if 'pack_id' in args and args['pack_id']:self.link_job_pack(state,args['pack_id'])
        if 'run_id' in args:self.require_link(state,'application_runs',args['run_id'])
        if 'interview_id' in args:self.require_link(state,'interviews',args['interview_id'])
        if name=='inspect_job':
            # A new conversation can discover a saved job's existing materials.
            # Linking them here keeps subsequent inspect/revise calls scoped to
            # this verified job instead of forcing another generation.
            packs = rt.packs.list_for_application(args['application_id'])
            for pack in packs:self.repository.link(task_id,'packs',pack.pack_id)
            return {'material_choices':self.material_choices(args['application_id']),
                    'materials':[self.materials(pack.pack_id,detail=False) for pack in packs],
                    **self.job_summary(args['application_id'],detail=True)}
        if name=='score_job':
            saved,text = self.candidate()
            if not text:raise ValueError('Attach a resume in this chat before comparing fit.')
            app = rt.workspace.get_application(args['application_id'])
            fingerprint = self.analysis_fingerprint(text,app.current_snapshot_id)
            if (state.get('analyses',{}).get(app.application_id)!=fingerprint
                    or self.job_summary(app.application_id)['match_score'] is None):
                asyncio.run(self.analysis.analyze(app.application_id,snapshot_id=app.current_snapshot_id,
                    resume_text=text,expected_version=app.version))
                self.repository.change(task_id,lambda s:{'analyses':{**s.get('analyses',{}),app.application_id:fingerprint}})
            return self.job_summary(app.application_id,detail=True)
        if name=='generate_materials':
            artifacts = args['artifacts']
            if not artifacts or len(artifacts)>2 or set(artifacts)-{'tailored_resume','cover_letter'}:raise ValueError('Choose resume and/or cover letter.')
            app = rt.workspace.get_application(args['application_id'])
            fresh = args.get('fresh', False)
            if fresh:
                message = self.user_message(state, args.get('message_id'))
                latest = next(m for m in reversed(state['messages']) if m['role']=='user')
                if message['id'] != latest['id']: raise ValueError('A fresh set requires the current user request, not an older instruction.')
            # One generation request per job/user turn, independent of tool
            # argument ordering or splitting resume and letter into two calls.
            request_key = self.key(state, name, {'application_id':app.application_id,'fresh':fresh})
            previous = {p.pack_id for p in rt.packs.list_for_application(app.application_id)}
            pack = rt.pack_workflow.create(app.application_id,expected_version=app.version,
                idempotency_key=request_key,scope_to_inputs=not fresh)
            self.repository.link(task_id,'packs',pack.pack_id)
            rt.pack_workflow.generate_many(pack.pack_id, artifacts, idempotency_key=request_key)
            result = self.materials(pack.pack_id)
            if not fresh and pack.pack_id in previous:
                result['progress_feedback'] = ('Reused saved drafts for identical source inputs; no fresh set was generated. '
                    'If the latest user explicitly requested a new set, call generate_materials with fresh=true and their message_id. '
                    'Otherwise inspect these drafts or return their observed status. Repeating this call will reuse them again.')
            return result
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
            saved = self.applications.repository.saved_candidate()
            fingerprint = hashlib.sha256((message['id'] + ':' + message['text']).encode()).hexdigest()
            if fingerprint in state.get('profile_updates', {}):
                return {'profile':saved['profile'],'already_processed':True,
                    'progress_feedback':'This user message has already been applied to the reusable profile. Use current details; do not parse or apply the same message again.'}
            parsed = extract_chat_profile(message['text'], current_profile=saved['profile'])
            self.applications.repository.save_candidate({**saved['profile'],**parsed.get('profile',{})})
            if not parsed.get('retryable'):
                self.repository.change(task_id, lambda latest: {'profile_updates':dict(list({
                    **latest.get('profile_updates',{}),fingerprint:{'message_id':message['id'],'changed_fields':list(parsed.get('profile',{}))}}.items())[-40:])})
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
            return self.application(args['run_id'],include_fields=args.get('include_fields',False),field_key=args.get('field_key'))
        if name=='reply_application':
            message = self.user_message(state,args['message_id'])
            previous = self.applications.repository.get(args['run_id'])
            duplicate = any(m.get('id') == message['id'] for m in previous.get('messages', []))
            if duplicate:
                return {k:previous[k] for k in ('run_id','status','version')} | {
                    'reply_delivered':True,'already_delivered':True,'message_id':message['id'],'no_new_evidence':True,
                    'next':'This exact message was already delivered; no action or verification was repeated. Use the live application outcome. Wait if it is working; if it is awaiting_review, report the verified review result.'}
            self.applications.chat(args['run_id'],ChatRequest(text=message['text'],message_id=message['id'],
                visual_fallback=state['visual_fallback']))
            current = self.application(args['run_id'])
            if current['status'] in {'queued','running','submitting'}:
                return {k:current[k] for k in ('run_id','status','version')} | {
                    'reply_delivered':True,'message_id':message['id'],'no_new_evidence':duplicate,
                    'next':'The exact answer is delivered and the browser worker is processing it. Wait with wait_for_result(kind=application,id=run_id), or do independent work. Do not forward it again or page through its working form.'}
            return current
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

    def screen(self, task_id, state, jobs, query):
        from agent_runtime.career.screening import screen_jobs
        from agent_runtime.fast_decisions import FastDecisions, configured_decisions
        if not isinstance(query, str) or not 0 < len(query) <= 3000:
            raise ValueError('Use a concise search preference query.')
        revision = state.get('chat_revision', 0)
        service = configured_decisions()
        # An auxiliary budget per user turn prevents a cheap tool becoming an
        # unlimited provider loop. It does not consume the main reasoning budget.
        allowed = [False]
        def reserve(current):
            count = current.get('fast_screen_calls', 0) if current.get('fast_screen_revision') == revision else 0
            if (current.get('chat_revision', 0) != revision or current.get('pause_requested')
                    or current.get('status') in {'completed','cancelled'} or count >= 20):
                return {}
            allowed[0] = True
            return {'fast_screen_revision': revision, 'fast_screen_calls': count + 1}
        if service.enabled:
            self.repository.change(task_id, reserve)
            if not allowed[0]:
                service = FastDecisions()
        result = screen_jobs(jobs, query, decisions=service)
        latest = self.repository.get(task_id)
        if latest.get('chat_revision', 0) != revision or latest.get('pause_requested'):
            return {'stale': True, 'next': 'Read the latest user request before screening again.'}
        self.repository.change(task_id, lambda s: {'fast_decisions': [
            *s.get('fast_decisions', []), {'purpose':'job_screening', **result['fast_decision']}][-30:]})
        return result

    @staticmethod
    def application_instruction(state):
        latest = next((m['text'] for m in reversed(state.get('messages', [])) if m.get('role') == 'user'), '')
        # Preserve the entire 4,000-character user message. Appending boilerplate
        # would exceed the worker contract, while slicing could sever a negation.
        return latest or APPLICATION_INSTRUCTION

    def open_application_url(self,state,args,key):
        from agent_runtime.auto_apply.contracts import posting
        saved,_ = self.candidate()
        if not saved.get('resume_base64'):raise ValueError('Upload a resume PDF before opening this application.')
        request = StartApplication(url=args['url'],profile=saved['profile'],resume_base64=saved['resume_base64'],
            idempotency_key=key,save_as_default=False,auto_submit=False,automation_mode='hybrid',
            consent_policy='ask',visual_fallback=state['visual_fallback'],initial_message=self.application_instruction(state))
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

    def material_selections_for(self, state, application_id):
        scoped = state.get('material_selections_by_application', {})
        if application_id in scoped:
            return {kind:choice for kind,choice in scoped[application_id].items()
                    if kind in {'tailored_resume','cover_letter'}}
        result = {}
        # Migrate old conversations by the immutable pack->application relationship.
        for kind, choice in state.get('material_selections', {}).items():
            if kind not in {'tailored_resume','cover_letter'} or not choice: continue
            try:pack = self.runtime.packs.get(choice['pack_id'])
            except (KeyError, LookupError):
                raise ValueError('The explicitly selected document is unavailable. Review/select the intended current version before upload.') from None
            if pack.application_id == application_id: result[kind] = choice
        return result

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
        from agent_runtime.application_pack.selection import latest_materials
        latest = latest_materials(rt.workspace, rt.packs, rt.pack_workflow, app.application_id)
        selected = []
        choices = self.material_selections_for(state, app.application_id)
        if args.get('pack_id'):
            pack = rt.pack_workflow.refresh_staleness(args['pack_id'])
            if pack.application_id!=app.application_id or pack.snapshot_id!=app.current_snapshot_id or pack.status.value=='stale':
                raise ValueError('Use current materials for this exact job.')
            selected = [(pack, item) for item in rt.packs.items(pack.pack_id)]
            if choices:
                from agent_runtime.application_pack.selection import current_materials, reviewed_selections
                pinned = reviewed_selections(latest,
                    current_materials(rt.workspace, rt.packs, rt.pack_workflow, app.application_id),
                    choices)
                for kind, choice in choices.items():
                    if not choice: continue
                    expected = next(((p.pack_id, i.pack_item_id, i.version) for p, i in pinned if i.artifact_type == kind), None)
                    actual = next(((p.pack_id, i.pack_item_id, i.version) for p, i in selected if i.artifact_type == kind), None)
                    if actual is None and expected is not None:
                        # A resume-only pack is compatible with a cover explicitly
                        # selected from another pack. Never infer an older choice.
                        selected.append(next((p,i) for p,i in pinned if i.artifact_type == kind))
                    elif actual != expected:
                        raise ValueError('This pack conflicts with the explicitly selected document version. Omit pack_id to use the reviewed per-document choices, or review a different version before upload.')
        elif source != 'original':
            from agent_runtime.application_pack.selection import current_materials, reviewed_selections
            selected = reviewed_selections(latest,
                current_materials(rt.workspace, rt.packs, rt.pack_workflow, app.application_id),
                choices)
        if source == 'tailored' and not any(i.artifact_type == 'tailored_resume' for p, i in selected):
            raise ValueError('Generate and review this job\'s tailored resume first.')
        if selected:
            for pack, item in selected:
                self.repository.link(state['task_id'], 'packs', pack.pack_id)
                if item.artifact_type not in {'tailored_resume','cover_letter'}:continue
                if item.status.value!='approved' or not item.artifact_id:
                    raise ValueError('The generated documents need review in this chat before being used for an application.')
                newest = next((i for p, i in latest if (i.artifact_type, i.source_question) == (item.artifact_type, item.source_question)), item)
                approval = choices.get(item.artifact_type, {})
                if newest.pack_item_id != item.pack_item_id and approval != {
                        'pack_id': pack.pack_id, 'item_id': item.pack_item_id, 'version': item.version,
                        'superseding_item_id': newest.pack_item_id, 'superseding_version': newest.version}:
                    raise ValueError('A newer material attempt exists. The older successful revision remains available; explicitly review/select it in this conversation before upload.')
                content = rt.packs.artifact(pack.pack_id,item.pack_item_id)
                if item.artifact_type=='tailored_resume':encoded = base64.b64encode(render_tailored_resume_pdf(content)).decode()
                else:cover = render_cover_letter(content)
                material_refs[item.artifact_type] = {'pack_id':pack.pack_id,'item_id':item.pack_item_id,'version':item.version}
        if not encoded:raise ValueError('Upload the original resume PDF, or approve a tailored resume first.')
        request = StartApplication(url=job.canonical_url,profile=saved['profile'],resume_base64=encoded,
            idempotency_key=key,automation_mode='hybrid',auto_submit=False,consent_policy='ask',
            save_as_default=False,cover_letter=cover,visual_fallback=state['visual_fallback'],
            initial_message=self.application_instruction(state))
        try:run = self.applications.start(request,material_refs=material_refs)
        except DuplicateApplication as exc:
            run = self.applications.repository.get(exc.run_id)
            if run['status'] in {'submitted','submitting','submission_unknown'}:
                # Never relabel an earlier submission as having used the new pack.
                self.repository.link(state['task_id'],'application_runs',run['run_id'],active_application_run=run['run_id'],active_browser='application')
                self.repository.change(state['task_id'],lambda s:{'application_links':{**s.get('application_links',{}),
                    run['run_id']:{'application_id':app.application_id,'materials':run.get('material_refs',{})}}})
                return {**self.application(run['run_id']),'note':'This job already has a submission. No new materials were uploaded.'}
            latest_user = next((m for m in reversed(state.get('messages', [])) if m.get('role') == 'user'), {})
            message_id = 'handoff:' + hashlib.sha256((state['task_id'] + ':' + latest_user.get('id', '')).encode()).hexdigest()[:48]
            instruction = self.application_instruction(state)
            previous = run.get('material_refs',{})
            # Pinned versions preserve identity across older non-deterministic PDF exports.
            same_resume = (previous.get('tailored_resume')==material_refs.get('tailored_resume')
                if material_refs.get('tailored_resume') else self.applications.repository.resume(run['run_id'])==base64.b64decode(encoded))
            if not same_resume or previous!=material_refs or run.get('cover_letter')!=cover or run['profile']!=request.profile.model_dump():
                run = self.applications.replace_materials(run['run_id'],base64.b64decode(encoded),cover,
                    profile=request.profile.model_dump(),material_refs=material_refs,
                    initial_message=instruction,message_id=message_id)
            elif run['status'] in {'cancelled','failed'}:
                run = self.applications.resume(run['run_id'],run['version'],initial_message=instruction,message_id=message_id)
            elif not any(m.get('id') == message_id for m in run.get('messages', [])):
                last_user = next((m for m in reversed(run.get('messages', [])) if m.get('role') == 'user'), {})
                if last_user.get('text') != instruction:
                    run = self.applications.chat(run['run_id'], ChatRequest(text=instruction,message_id=message_id))
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

    def wait_after_repeated_read(self, state, tool):
        # Preserve autonomous independent work. Park only after a repeated,
        # unchanged inspection while a linked capability is actually working.
        if tool not in self.batchable_tools | {'read_context', 'inspect_application', 'reply_application'}:
            return None
        for run_id in reversed(state.get('application_runs', [])):
            if self.applications.repository.get(run_id)['status'] in {'queued','running','submitting'}:
                return {'kind': 'application', 'id': run_id}
        return None

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
