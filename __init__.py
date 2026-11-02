from fastapi import APIRouter
from lnbits.task_manager import (  # pyright: ignore[reportMissingImports]
    Task,
    task_manager,
)

from .crud import db
from .tasks import (
    TASK_NAME,
    on_address_event,
    on_invoice_paid,
    restart_address_tracking,
    satspay_untrack_all_addresses,
)
from .views import satspay_generic_router
from .views_api import satspay_api_router
from .views_api_themes import satspay_theme_router

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

_listener_tasks: list[Task] = []


def satspay_stop():
    satspay_untrack_all_addresses()
    for task in _listener_tasks:
        task_manager.cancel_task(task)
    _listener_tasks.clear()


def satspay_start():
    _listener_tasks.append(
        task_manager.register_invoice_listener(on_invoice_paid, TASK_NAME)
    )
    _listener_tasks.append(
        task_manager.register_onchain_listener(on_address_event, TASK_NAME)
    )
    task_manager.create_task(
        restart_address_tracking(), f"{TASK_NAME}_restart_address_tracking"
    )


__all__ = ["db", "satspay_ext", "satspay_start", "satspay_static_files", "satspay_stop"]
