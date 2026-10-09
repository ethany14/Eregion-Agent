"""Unified chat entry point. Credentials still go directly to the existing account API."""
from threading import Lock
from urllib.parse import urlsplit

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from agent_runtime.career.service import CareerService
from agent_runtime.auto_apply.repository import ApplyConflict

router = APIRouter(prefix='/api/career/tasks',tags=['career agent'])
groups_router = APIRouter(prefix='/api/career/groups',tags=['career agent'])
_lock = Lock()


class StartTask(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1,max_length=4000)
    idempotency_key: str = Field(min_length=8,max_length=100)
    visual_fallback: bool = False
    application_id: str | None = Field(default=None,min_length=1,max_length=100)


class MessageContext(BaseModel):
    model_config = ConfigDict(extra='forbid')
    application_id: str | None = Field(default=None,max_length=100)
    pack_id: str | None = Field(default=None,max_length=100)
    item_id: str | None = Field(default=None,max_length=100)
    interview_id: str | None = Field(default=None,max_length=100)


class Chat(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1,max_length=4000)
    message_id: str = Field(min_length=8,max_length=100)
    field_key: str | None = None
    visual_fallback: bool | None = None
    context: MessageContext | None = None


class Organise(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str | None = Field(default=None,max_length=120)
    group_id: str | None = Field(default=None,max_length=40)
    pinned: bool | None = None
    archived: bool | None = None
    trashed: bool | None = None


class Group(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1,max_length=80,pattern=r'\S')


class Review(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1)
    approve: bool


class BrowserWindow(BaseModel):
    model_config=ConfigDict(extra='forbid')
    visible: bool
    expected_version: int=Field(ge=1)


def restore_tasks(application):
    runtime = application.state.session_runtime
    # Minimal runtimes used by other feature tests do not provide career services.
    if runtime is None or not all(getattr(runtime,n,None) is not None for n in ('workspace','packs','mock_interviewer')):return
    with _lock:
        if getattr(application.state,'career_agent',None) is None:
            application.state.career_agent = CareerService(runtime,application.state.auto_apply)


def service(request: Request):
    origin = request.headers.get('origin')
    if origin and urlsplit(origin).netloc!=request.url.netloc:raise HTTPException(403,'Open this chat from the local workspace.')
    restore_tasks(request.app)
    existing = getattr(request.app.state,'career_agent',None)
    if existing is None:raise HTTPException(503,'The career runtime is not ready.')
    return existing


def invoke(action):
    try:return action()
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc
    except (ValueError,ApplyConflict) as exc:raise HTTPException(409,str(exc)) from exc


@router.get('')
def list_tasks(view: Literal['active','archived','trash']=Query('active'),agent=Depends(service)):
    return invoke(lambda:agent.list(view))


@router.delete('/trash')
def empty_trash(agent=Depends(service)):return invoke(agent.empty_trash)


@router.post('',status_code=202)
def start(body: StartTask,agent=Depends(service)):
    return invoke(lambda:agent.start(body.text,body.idempotency_key,body.visual_fallback,body.application_id))


@router.get('/{task_id}')
def get(task_id: str,agent=Depends(service)):return invoke(lambda:agent.view(task_id))


@router.patch('/{task_id}')
def organise(task_id: str,body: Organise,agent=Depends(service)):
    return invoke(lambda:agent.organise(task_id,body.model_dump(exclude_unset=True)))


@router.delete('/{task_id}')
def delete(task_id: str,agent=Depends(service)):return invoke(lambda:agent.delete(task_id))


@router.get('/{task_id}/browser/preview')
def browser_preview(task_id: str,agent=Depends(service)):
    invoke(lambda:agent.repository.get(task_id))
    manager=getattr(agent.harness,'_browsing',None)
    image=manager.preview(task_id) if manager else None
    return Response(content=image or b'',status_code=200 if image else 204,media_type='image/jpeg',headers={'Cache-Control':'no-store'})


@router.post('/{task_id}/chat',status_code=202)
def chat(task_id: str,body: Chat,agent=Depends(service)):
    return invoke(lambda:agent.chat(task_id,body.text,body.message_id,body.visual_fallback,
        body.context.model_dump(exclude_none=True) if body.context else None))


@router.post('/{task_id}/browser-control')
async def browser_control(task_id: str, request: Request, agent=Depends(service)):
    from .browser_control import read_control_request
    from fastapi.responses import JSONResponse
    body = await read_control_request(request)
    # Keep browser-worker waits off the event loop so the chat stays responsive.
    from starlette.concurrency import run_in_threadpool
    result = await run_in_threadpool(lambda: invoke(lambda: agent.browser_control(task_id, body)))
    return JSONResponse(result, headers={'Cache-Control': 'no-store'})


@router.post('/{task_id}/browser-window')
def browser_window(task_id: str,body: BrowserWindow,agent=Depends(service)):
    return invoke(lambda:agent.set_browser_visible(task_id,body.visible,body.expected_version))


@router.post('/{task_id}/reply',status_code=202)
def reply(task_id: str,body: dict,agent=Depends(service)):
    return invoke(lambda:agent.application_action(task_id,'reply',body))


@router.post('/{task_id}/continue',status_code=202)
def continue_task(task_id: str,body: dict,agent=Depends(service)):
    return invoke(lambda:agent.application_action(task_id,'continue',body))


@router.post('/{task_id}/cancel')
def cancel(task_id: str,agent=Depends(service)):return invoke(lambda:agent.cancel(task_id))


@router.post('/{task_id}/materials/{pack_id}/{item_id}/review')
def review(task_id: str,pack_id: str,item_id: str,body: Review,agent=Depends(service)):
    return invoke(lambda:agent.review_material(task_id,pack_id,item_id,body.expected_version,body.approve))


@groups_router.get('')
def list_groups(agent=Depends(service)):return {'groups':invoke(agent.repository.groups)}


@groups_router.post('',status_code=201)
def create_group(body: Group,agent=Depends(service)):return invoke(lambda:agent.repository.create_group(body.name.strip()))


@groups_router.patch('/{group_id}')
def rename_group(group_id: str,body: Group,agent=Depends(service)):
    return invoke(lambda:agent.repository.rename_group(group_id,body.name.strip()))


@groups_router.delete('/{group_id}',status_code=204)
def delete_group(group_id: str,agent=Depends(service)):
    invoke(lambda:agent.repository.delete_group(group_id))
    return Response(status_code=204)
