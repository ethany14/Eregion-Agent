"""Local-user schedules, digests and acknowledgement endpoints."""
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from api.career_routes import service, invoke
from agent_runtime.career.alerts import AlertConfig

router=APIRouter(prefix='/api/career/alerts',tags=['job recommendations'])


class CreateAlert(BaseModel):
    model_config=ConfigDict(extra='forbid')
    config: AlertConfig
    idempotency_key: str=Field(min_length=8,max_length=100)


class UpdateAlert(BaseModel):
    model_config=ConfigDict(extra='forbid')
    config: AlertConfig
    expected_version: int=Field(ge=1)


class RunAlert(BaseModel):
    model_config=ConfigDict(extra='forbid')
    idempotency_key: str=Field(min_length=8,max_length=100)


@router.get('')
def list_alerts(agent=Depends(service)):
    return {'schedules':agent.alerts.list(),'digests':agent.alerts.feed()}


@router.post('',status_code=201)
def create_alert(body: CreateAlert,agent=Depends(service)):
    return invoke(lambda:agent.alerts.save(body.config.model_dump(),request_key=body.idempotency_key))


@router.put('/{alert_id}')
def update_alert(alert_id: str,body: UpdateAlert,agent=Depends(service)):
    return invoke(lambda:agent.alerts.save(body.config.model_dump(),alert_id=alert_id,expected_version=body.expected_version))


@router.post('/{alert_id}/run',status_code=202)
def run_now(alert_id: str,body: RunAlert,agent=Depends(service)):
    return invoke(lambda:agent.alert_scheduler.run_now(alert_id,body.idempotency_key))


@router.post('/digests/{run_id}/read',status_code=204)
def mark_read(run_id: str,agent=Depends(service)):
    invoke(lambda:agent.alerts.mark_read(run_id))
    return Response(status_code=204)
