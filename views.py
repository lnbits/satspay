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
    if charge_id not in public_ws_listeners:
        public_ws_listeners[charge_id] = []
    public_ws_listeners[charge_id].append(websocket)
    try:
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
