from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException
from lnbits.core.models import Account
from lnbits.decorators import check_admin

from .crud import create_theme, delete_theme, get_theme, get_themes, update_theme
from .models import CreateSatsPayTheme, SatsPayTheme

satspay_theme_router = APIRouter()


@satspay_theme_router.post("/api/v1/themes")
async def api_themes_create(
    data: CreateSatsPayTheme,
    user: Account = Depends(check_admin),
) -> SatsPayTheme:
    return await create_theme(data=data, user_id=user.id)


@satspay_theme_router.post("/api/v1/themes/{css_id}")
async def api_themes_save(
    css_id: str,
    data: CreateSatsPayTheme,
    user: Account = Depends(check_admin),
) -> SatsPayTheme:

    theme = await get_theme(css_id)
    if not theme or theme.user != user.id:
        raise HTTPException(HTTPStatus.NOT_FOUND, "Theme does not exist.")
    theme.title = data.title
    theme.custom_css = data.custom_css
    return await update_theme(theme)


@satspay_theme_router.get("/api/v1/themes")
async def api_get_themes(user: Account = Depends(check_admin)) -> list[SatsPayTheme]:
    return await get_themes(user.id)


@satspay_theme_router.delete("/api/v1/themes/{theme_id}")
async def api_theme_delete(theme_id: str, user: Account = Depends(check_admin)):
    theme = await get_theme(theme_id)
    if not theme or theme.user != user.id:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Theme does not exist."
        )
    await delete_theme(theme_id)
