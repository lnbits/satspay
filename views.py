import json
from http import HTTPStatus

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse
from lnbits.core.models import User
from lnbits.decorators import check_user_exists
from lnbits.helpers import template_renderer
from lnbits.settings import settings

from .crud import get_charge, get_or_create_satspay_settings, get_theme
from .tasks import public_ws_listeners

satspay_generic_router = APIRouter()


def satspay_renderer():
    return template_renderer(["satspay/templates"])


@satspay_generic_router.get("/", response_class=HTMLResponse)
async def index(request: Request, user: User = Depends(check_user_exists)):
    settings = await get_or_create_satspay_settings()
    return satspay_renderer().TemplateResponse(
        "satspay/index.html",
        {
            "request": request,
            "user": user.dict(),
            "admin": user.admin,
            "network": settings.network,
        },
    )


@satspay_generic_router.get("/{charge_id}", response_class=HTMLResponse)
async def display_charge(request: Request, charge_id: str):
    charge = await get_charge(charge_id)
    if not charge:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Charge link does not exist."
        )
    settings = await get_or_create_satspay_settings()
    return satspay_renderer().TemplateResponse(
        "satspay/display.html",
        {
            "request": request,
            "charge_data": json.dumps(charge.public),
            "custom_css": charge.custom_css,
            "mempool_url": settings.mempool_url,
        },
    )


@satspay_generic_router.websocket("/{charge_id}/ws")
async def websocket_charge(websocket: WebSocket, charge_id: str):
    charge = await get_charge(charge_id)
    if not charge:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Charge link does not exist."
        )
    await websocket.accept()
    if charge_id not in public_ws_listeners:
        public_ws_listeners[charge_id] = []
    public_ws_listeners[charge_id].append(websocket)
    try:
        # Keep the connection alive
        while settings.lnbits_running:
            await websocket.receive_text()
    except WebSocketDisconnect:
        for ws in public_ws_listeners.get(charge_id, []):
            if ws == websocket:
                public_ws_listeners[charge_id].remove(ws)


@satspay_generic_router.get("/css/{css_id}")
async def display_css(css_id: str):
    theme = await get_theme(css_id)
    if theme:
        return Response(content=theme.custom_css, media_type="text/css")
    return None
