from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.templating import Jinja2Templates
from lnbits.core.models import User
from lnbits.decorators import check_user_exists
from lnbits.helpers import template_renderer
from starlette.responses import HTMLResponse

from .crud import get_charge, get_theme

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
            "charge_data": charge.public,
            "mempool_endpoint": charge.config.mempool_endpoint,
            "network": charge.config.network,
        },
    )


@satspay_generic_router.get("/css/{css_id}")
async def display_css(css_id: str):
    theme = await get_theme(css_id)
    if theme:
        return Response(content=theme.custom_css, media_type="text/css")
    return None
