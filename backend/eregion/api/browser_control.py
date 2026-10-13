"""Validate user-only input without echoing typed credentials in error bodies."""
from fastapi import HTTPException
from eregion.runtime.browser.handoff import BrowserControlRequest


async def read_control_request(request):
    if request.headers.get('origin') != str(request.base_url).rstrip('/'):
        raise HTTPException(403, 'Open browser control from this local workspace.')
    if request.headers.get('content-type', '').split(';')[0] != 'application/json':
        raise HTTPException(415, 'Browser control requires JSON.')
    try:
        raw = await request.body()
        if len(raw) > 20000:
            raise ValueError()
        return BrowserControlRequest.model_validate_json(raw)
    except (ValueError, TypeError):
        raise HTTPException(422, 'Check the browser control input and try again.') from None
