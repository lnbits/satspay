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
from fastapi.templating import Jinja2Templates
from lnbits.core.models import User
from lnbits.decorators import check_user_exists
from lnbits.helpers import template_renderer
from lnbits.settings import settings
from starlette.responses import HTMLResponse

from .crud import get_charge, get_theme
from .tasks import public_ws_listeners

templates = Jinja2Templates(directory="templates")
satspay_generic_router = APIRouter()


def satspay_renderer():
    return template_renderer(["satspay/templates"])


@satspay_generic_router.get("/", response_class=HTMLResponse)
async def index(request: Request, user: User = Depends(check_user_exists)):
    return satspay_renderer().TemplateResponse(
        "satspay/index.html",
        {"request": request, "user": user.dict(), "admin": user.admin},
    )


@satspay_generic_router.get("/{charge_id}", response_class=HTMLResponse)
async def display_charge(request: Request, charge_id: str):
    charge = await get_charge(charge_id)
    if not charge:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Charge link does not exist."
        )

    return satspay_renderer().TemplateResponse(
        "satspay/display.html",
        {
            "request": request,
            "charge_data": json.dumps(charge.public),
            "custom_css": charge.custom_css,
            "mempool_endpoint": charge.config.mempool_endpoint,
            "network": charge.config.network,
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
    public_ws_listeners[charge_id] = websocket
    try:
        # Keep the connection alive
        while settings.lnbits_running:
            await websocket.receive_text()
    except WebSocketDisconnect:
        del public_ws_listeners[charge_id]


@satspay_generic_router.get("/css/{css_id}")
async def display_css(css_id: str):
    theme = await get_theme(css_id)
    if theme:
        return Response(content=theme.custom_css, media_type="text/css")
    return None
