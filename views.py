from http import HTTPStatus

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from lnbits.core.views.generic import index, index_public
from lnbits.decorators import check_user_exists
from lnbits.settings import settings

from .crud import get_charge, get_theme
from .tasks import public_ws_listeners

MAX_PUBLIC_WS = 1024
MAX_PUBLIC_WS_PER_CHARGE = 64
MAX_PUBLIC_WS_PER_IP = 32

satspay_generic_router = APIRouter()

satspay_generic_router.add_api_route(
    "/", methods=["GET"], endpoint=index, dependencies=[Depends(check_user_exists)]
)

satspay_generic_router.add_api_route(
    "/{charge_id}", methods=["GET"], endpoint=index_public
)


@satspay_generic_router.websocket("/{charge_id}/ws")
async def websocket_charge(websocket: WebSocket, charge_id: str):
    charge = await get_charge(charge_id)
    if not charge:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Charge link does not exist."
        )
    await websocket.accept()
    connections = [ws for group in public_ws_listeners.values() for ws in group]
    host = websocket.client.host if websocket.client else None
    source_count = sum(
        (ws.client.host if ws.client else None) == host for ws in connections
    )
    if (
        len(connections) >= MAX_PUBLIC_WS
        or len(public_ws_listeners.get(charge_id, [])) >= MAX_PUBLIC_WS_PER_CHARGE
        or source_count >= MAX_PUBLIC_WS_PER_IP
    ):
        await websocket.close(code=1013)
        return
    listeners = public_ws_listeners.setdefault(charge_id, [])
    listeners.append(websocket)
    try:
        while settings.lnbits_running:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in listeners:
            listeners.remove(websocket)
        if not listeners and public_ws_listeners.get(charge_id) is listeners:
            public_ws_listeners.pop(charge_id, None)


@satspay_generic_router.get("/css/{css_id}")
async def display_css(css_id: str):
    theme = await get_theme(css_id)
    if theme:
        return Response(content=theme.custom_css, media_type="text/css")
    return None
