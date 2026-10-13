"""Wake persisted searches in the ordinary autonomous task loop."""
import logging
from datetime import datetime, timedelta
from threading import Event, RLock, Thread
from zoneinfo import ZoneInfo

from .alerts import utcnow

logger=logging.getLogger(__name__)


class AlertScheduler:
    def __init__(self,service,*,clock=utcnow,start=True):
        self.service,self.alerts,self.clock=service,service.alerts,clock
        self.stop,self.lock=Event(),RLock()
        self.thread=None
        if start:
            self.thread=Thread(target=self._poll,daemon=True,name='career-job-alerts');self.thread.start()

    def _poll(self):
        while not self.stop.is_set():
            try:self.tick()
            except Exception as exc:logger.warning('Job alert scheduler retry: %s',type(exc).__name__)
            self.stop.wait(5)

    def run_now(self,alert_id,request_key):
        with self.lock:
            run=self.alerts.claim(alert_id,request_key=request_key)
            self._start(run)
            return self.alerts.get_run(run['run_id'])

    def _start(self,run):
        if run['status'] not in {'pending','running'}:return
        if run['task_id']:return
        config=run['config']
        goal=(f'Scheduled search: {config["name"]}. Find up to {config["max_results"]} new jobs for my saved resume.\n'
            f'Preferences: {config["preferences"]}\n'
            'Search with the browser on relevant job sites and their search/filter controls; read actual descriptions, score promising jobs, '
            'and use recommend_job for the best new matches. Finish with a brief digest, including source access limitations. '
            'Do not apply, create accounts or change my search schedule. Do not wait for my reply when one site is blocked; '
            'try another source. If essential candidate information is missing, explain it clearly.')
        task,_=self.service.repository.create(goal,f'job-alert:{run["run_id"]}',visual_fallback=config['visual_fallback'],
            context={'recommendation_run_id':run['run_id']})
        self.alerts.attach(run['run_id'],task['task_id'])
        local_day=datetime.fromisoformat(run['scheduled_for']).astimezone(ZoneInfo(config['timezone'])).date()
        self.service.repository.update_meta(task['task_id'],title=f'{config["name"]} · {local_day}')
        self.service.repository.change(task['task_id'],model_budget=60)
        self.service.loop.schedule(task['task_id'])

    def tick(self):
        with self.lock:
            for alert in self.alerts.list():
                if self.stop.is_set():return
                if alert['enabled'] and alert['next_run_at']<=self.clock().isoformat():
                    run=self.alerts.claim(alert['alert_id'])
                    if run:self._start(run)
            for run in self.alerts.active():
                if self.stop.is_set():return
                if not run['task_id']:
                    self._start(run);continue
                try:state=self.service.repository.get(run['task_id'])
                except LookupError:
                    self.alerts.finish(run['run_id'],'failed','This search conversation was removed.');continue
                if state['status']=='queued':self.service.loop.schedule(state['task_id'])
                timed_out=self.clock()-datetime.fromisoformat(run['created_at'])>timedelta(minutes=20)
                if timed_out and state['status'] in {'queued','running','waiting'}:
                    # Fence a pending model/browser result without replaying effects.
                    with self.service.loop.lock:
                        state=self.service.repository.change(run['task_id'],status='cancelled',pause_requested=True,
                            chat_revision=state['chat_revision']+1)
                if state['status'] in {'completed','needs_input','cancelled'} or state['chat_revision']>0:
                    count=len(self.alerts.items(run['run_id']))
                    status='completed' if state['status']=='completed' else 'partial' if count else 'needs_attention'
                    message=f'{count} verified new match'+('es' if count!=1 else '')+' saved.'
                    if status!='completed':
                        reason='The search reached its time limit.' if timed_out else (
                            'The search stopped after repeated steps produced no new evidence.' if (state.get('error') or {}).get('code')=='no_progress'
                            else 'The search could not finish automatically.')
                        message+=' '+reason+' Open the conversation for saved results and details.'
                    elif not count:message='The search finished with no verified new matches meeting your preferences and threshold.'
                    self.alerts.finish(run['run_id'],status,message)
                    manager=getattr(self.service.harness,'_browsing',None)
                    if manager and state['chat_revision']==0:manager.close_task(state['task_id'])

    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=3)
