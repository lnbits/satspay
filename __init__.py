import asyncio

from fastapi import APIRouter
from loguru import logger

from .crud import db
from .tasks import restart_address_tracking, wait_for_onchain, wait_for_paid_invoices
from .views import satspay_generic_router
from .views_api import satspay_api_router
from .views_api_themes import satspay_theme_router
from .websocket_handler import restart_websocket_task, websocket_task

satspay_ext: APIRouter = APIRouter(prefix="/satspay", tags=["satspay"])
satspay_ext.include_router(satspay_generic_router)
satspay_ext.include_router(satspay_api_router)
satspay_ext.include_router(satspay_theme_router)

satspay_static_files = [
    {
        "path": "/satspay/static",
        "name": "satspay_static",
    }
]

scheduled_tasks: list[asyncio.Task] = []


def satspay_stop():
    for task in scheduled_tasks:
        try:
            task.cancel()
        except Exception as ex:
            logger.warning(ex)
    if websocket_task:
        websocket_task.cancel()


def satspay_start():
    from lnbits.tasks import create_permanent_unique_task, create_unique_task

    paid_invoices_task = create_permanent_unique_task(
        "ext_satspay_paid_invoices", wait_for_paid_invoices
    )
    onchain_task = create_permanent_unique_task("ext_satspay_onchain", wait_for_onchain)
    scheduled_tasks.extend([paid_invoices_task, onchain_task])
    restart_websocket_task()
    create_unique_task("ext_satspay_restart_address_tracking", restart_address_tracking())


__all__ = ["db", "satspay_ext", "satspay_static_files", "satspay_start", "satspay_stop"]
