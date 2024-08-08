import asyncio

from fastapi import APIRouter
from loguru import logger

from .crud import db
from .tasks import wait_for_paid_invoices
from .views import satspay_generic_router
from .views_api import satspay_api_router

satspay_ext: APIRouter = APIRouter(prefix="/satspay", tags=["satspay"])
satspay_ext.include_router(satspay_generic_router)
satspay_ext.include_router(satspay_api_router)

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


def satspay_start():
    from lnbits.tasks import create_permanent_unique_task

    task = create_permanent_unique_task("ext_satspay", wait_for_paid_invoices)
    scheduled_tasks.append(task)


__all__ = ["db", "satspay_ext", "satspay_static_files", "satspay_start", "satspay_stop"]
