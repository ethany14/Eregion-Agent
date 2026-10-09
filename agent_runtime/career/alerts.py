"""Durable daily discovery schedules and verified recommendation digests."""
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Boolean, Column, Integer, String, Text, select, update
from api.db import Base
from agent_runtime.auto_apply.contracts import posting, public_https_url


def utcnow():return datetime.now(UTC)
def stamp(value):return value.astimezone(UTC).isoformat()


class AlertConfig(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    name: str=Field(min_length=1,max_length=100)
    preferences: str=Field(min_length=3,max_length=3000)
    sites: list[str]=Field(default_factory=list,max_length=10)
    local_time: str=Field(default='09:00',pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    timezone: str=Field(min_length=1,max_length=100)
    max_results: int=Field(default=5,ge=1,le=10)
    min_score: int=Field(default=70,ge=0,le=100)
    enabled: bool=True
    visual_fallback: bool=False

    @field_validator('timezone')
    @classmethod
    def zone(cls,value):
        try:ZoneInfo(value)
        except (ZoneInfoNotFoundError,ValueError):raise ValueError('Use an IANA timezone such as America/New_York.') from None
        return value

    @field_validator('sites')
    @classmethod
    def sources(cls,values):return list(dict.fromkeys(public_https_url(v) for v in values))


def occurrence(day,config):
    """One firing per local date; spring gaps shift forward, folds fire once."""
    zone=ZoneInfo(config['timezone']);hour,minute=map(int,config['local_time'].split(':'))
    local=datetime.combine(day,datetime.min.time()).replace(hour=hour,minute=minute,tzinfo=zone)
    valid=[]
    for fold in (0,1):
        candidate=local.replace(fold=fold).astimezone(UTC)
        if candidate.astimezone(zone).replace(tzinfo=None)==local.replace(tzinfo=None):valid.append(candidate)
    return min(valid) if valid else local.replace(fold=0).astimezone(UTC)


def next_due(config,after):
    day=after.astimezone(ZoneInfo(config['timezone'])).date()
    value=occurrence(day,config)
    return value if value>after else occurrence(day+timedelta(days=1),config)


def latest_due(config,at):
    day=at.astimezone(ZoneInfo(config['timezone'])).date()
    value=occurrence(day,config)
    return value if value<=at else occurrence(day-timedelta(days=1),config)


def job_key(url):
    # ATS identities ignore locale, application steps and tracking parameters.
    try:platform,key,_=posting(url)
    except ValueError:platform,key='generic',''
    if platform in {'greenhouse','lever','workday'}:return key
    p=urlsplit(public_https_url(url));query=dict(parse_qsl(p.query))
    if p.hostname=='linkedin.com' or (p.hostname or '').endswith('.linkedin.com'):
        match=re.search(r'/jobs/view/(?:[^/]*-)?(\d+)/?$',p.path)
        if query.get('currentJobId') or match:return 'linkedin:'+(query.get('currentJobId') or match[1])
    clean=urlencode(sorted((k,v) for k,v in query.items() if not k.lower().startswith(('utm_','tracking'))
        and k.lower() not in {'source','ref','refid','referrer','gh_src','lever-source','ebp','origin'}))
    return hashlib.sha256(urlunsplit((p.scheme,p.netloc,p.path.rstrip('/'),clean,'')).encode()).hexdigest()


class JobAlertRow(Base):
    __tablename__='career_job_alerts'
    alert_id=Column(String(40),primary_key=True)
    request_key=Column(String(160),unique=True,nullable=False)
    version=Column(Integer,nullable=False)
    config_json=Column(Text,nullable=False)
    enabled=Column(Boolean,nullable=False)
    next_run_at=Column(String(40),nullable=False,index=True)
    created_at=Column(String(40),nullable=False)
    updated_at=Column(String(40),nullable=False)


class AlertRunRow(Base):
    __tablename__='career_alert_runs'
    run_id=Column(String(40),primary_key=True)
    alert_id=Column(String(40),nullable=False,index=True)
    slot_key=Column(String(180),unique=True,nullable=False)
    config_json=Column(Text,nullable=False)
    task_id=Column(String(40))
    status=Column(String(24),nullable=False)
    scheduled_for=Column(String(40),nullable=False)
    created_at=Column(String(40),nullable=False)
    finished_at=Column(String(40))
    read_at=Column(String(40))
    summary=Column(Text)


class RecommendationRow(Base):
    __tablename__='career_recommendations'
    recommendation_id=Column(String(40),primary_key=True)
    run_id=Column(String(40),nullable=False,index=True)
    job_key=Column(String(250),unique=True,nullable=False)
    payload_json=Column(Text,nullable=False)
    created_at=Column(String(40),nullable=False)


class AlertRepository:
    def __init__(self,sessions,*,clock=utcnow):self.sessions,self.clock,self.lock=sessions,clock,RLock()

    @staticmethod
    def alert(row):
        return {**json.loads(row.config_json),'alert_id':row.alert_id,'version':row.version,
            'enabled':row.enabled,'next_run_at':row.next_run_at,'created_at':row.created_at,'updated_at':row.updated_at}

    @staticmethod
    def run(row):
        return {key:getattr(row,key) for key in ('run_id','alert_id','task_id','status','scheduled_for','created_at','finished_at','read_at','summary')}|{'config':json.loads(row.config_json)}

    def list(self):
        with self.sessions() as db:return [self.alert(r) for r in db.scalars(select(JobAlertRow).order_by(JobAlertRow.created_at))]

    def get(self,alert_id):
        with self.sessions() as db:
            row=db.get(JobAlertRow,alert_id)
            if row is None:raise LookupError('Job search schedule not found.')
            return self.alert(row)

    def save(self,config,*,request_key=None,alert_id=None,expected_version=None):
        config=AlertConfig.model_validate(config).model_dump();now=self.clock()
        with self.lock,self.sessions.begin() as db:
            if alert_id:
                row=db.get(JobAlertRow,alert_id)
                if row is None:raise LookupError('Job search schedule not found.')
                if row.version!=expected_version:raise ValueError('This schedule changed. Refresh and try again.')
                row.version+=1
            else:
                if not request_key:raise ValueError('Provide a request key.')
                row=db.scalar(select(JobAlertRow).where(JobAlertRow.request_key==request_key))
                if row:
                    if json.loads(row.config_json)!=config:raise ValueError('This request key belongs to another schedule.')
                    return self.alert(row)
                row=JobAlertRow(alert_id=str(uuid4()),request_key=request_key,version=1,created_at=stamp(now));db.add(row)
            row.config_json=json.dumps(config);row.enabled=config['enabled'];row.updated_at=stamp(now)
            row.next_run_at=stamp(next_due(config,now))
            return self.alert(row)

    def claim(self,alert_id,*,request_key=None):
        """Claim once atomically; overdue schedules coalesce to the latest local day."""
        now=self.clock()
        with self.lock,self.sessions.begin() as db:
            row=db.get(JobAlertRow,alert_id)
            if row is None:raise LookupError('Job search schedule not found.')
            config=json.loads(row.config_json)
            if request_key:
                slot=f'{alert_id}:manual:{request_key}';due=now
                existing=db.scalar(select(AlertRunRow).where(AlertRunRow.slot_key==slot))
                if existing:return self.run(existing)
            else:
                if not row.enabled or row.next_run_at>stamp(now):return None
                due=latest_due(config,now)
                slot=f'{alert_id}:daily:{due.astimezone(ZoneInfo(config["timezone"])).date()}'
                result=db.execute(update(JobAlertRow).where(JobAlertRow.alert_id==alert_id,
                    JobAlertRow.next_run_at==row.next_run_at,JobAlertRow.enabled.is_(True)).values(next_run_at=stamp(next_due(config,now))))
                if result.rowcount!=1:return None
                existing=db.scalar(select(AlertRunRow).where(AlertRunRow.slot_key==slot))
                if existing:return self.run(existing)
            active=db.scalar(select(AlertRunRow).where(AlertRunRow.alert_id==alert_id,AlertRunRow.status.in_(['pending','running'])))
            if active:return self.run(active)
            run=AlertRunRow(run_id=str(uuid4()),alert_id=alert_id,slot_key=slot,config_json=json.dumps(config),
                status='pending',scheduled_for=stamp(due),created_at=stamp(now));db.add(run)
            return self.run(run)

    def active(self):
        with self.sessions() as db:return [self.run(r) for r in db.scalars(select(AlertRunRow).where(AlertRunRow.status.in_(['pending','running'])))]

    def get_run(self,run_id):
        with self.sessions() as db:
            row=db.get(AlertRunRow,run_id)
            if row is None:raise LookupError('Recommendation run not found.')
            return self.run(row)

    def attach(self,run_id,task_id):
        with self.lock,self.sessions.begin() as db:
            row=db.get(AlertRunRow,run_id)
            if row.task_id and row.task_id!=task_id:raise ValueError('This run already owns another conversation.')
            row.task_id=task_id;row.status='running'

    def finish(self,run_id,status,summary):
        with self.lock,self.sessions.begin() as db:
            row=db.get(AlertRunRow,run_id)
            if row.status not in {'pending','running'}:return
            row.status=status;row.summary=summary[:4000];row.finished_at=stamp(self.clock())

    def recommended(self):
        with self.sessions() as db:return [json.loads(r.payload_json) for r in db.scalars(select(RecommendationRow).order_by(RecommendationRow.created_at.desc()).limit(100))]

    def add(self,run_id,payload):
        with self.lock,self.sessions.begin() as db:
            run=db.get(AlertRunRow,run_id)
            if run is None or run.status not in {'pending','running'}:raise ValueError('This recommendation run has ended.')
            config=json.loads(run.config_json)
            key=job_key(payload['url'])
            old=db.scalar(select(RecommendationRow).where(RecommendationRow.job_key==key))
            if old:return {'added':False,'reason':'Already recommended','recommendation':json.loads(old.payload_json)}
            count=len(list(db.scalars(select(RecommendationRow.recommendation_id).where(RecommendationRow.run_id==run_id))))
            if count>=config['max_results']:raise ValueError('This digest already has its requested number of jobs.')
            if payload['match_score']<config['min_score']:raise ValueError('This job is below the configured match threshold.')
            payload={**payload,'recommendation_id':str(uuid4()),'checked_at':stamp(self.clock())}
            db.add(RecommendationRow(recommendation_id=payload['recommendation_id'],run_id=run_id,job_key=key,
                payload_json=json.dumps(payload),created_at=stamp(self.clock())))
            return {'added':True,'recommendation':payload}

    def feed(self,limit=30):
        with self.sessions() as db:
            rows=list(db.scalars(select(AlertRunRow).order_by(AlertRunRow.created_at.desc()).limit(limit)))
            return [{**self.run(r),'recommendations':[json.loads(j.payload_json) for j in db.scalars(
                select(RecommendationRow).where(RecommendationRow.run_id==r.run_id).order_by(RecommendationRow.created_at))]} for r in rows]

    def items(self,run_id):
        with self.sessions() as db:return [json.loads(r.payload_json) for r in db.scalars(select(RecommendationRow).where(RecommendationRow.run_id==run_id))]

    def mark_read(self,run_id):
        with self.sessions.begin() as db:
            row=db.get(AlertRunRow,run_id)
            if row is None:raise LookupError('Recommendation run not found.')
            row.read_at=stamp(self.clock())
