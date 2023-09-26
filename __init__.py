import asyncio
from typing import List

from fastapi import APIRouter

from lnbits.db import Database
from lnbits.helpers import template_renderer
from lnbits.tasks import catch_everything_and_restart

db = Database("ext_satspay")

scheduled_tasks: List[asyncio.Task] = []

satspay_ext: APIRouter = APIRouter(prefix="/satspay", tags=["satspay"])

satspay_static_files = [
    {
        "path": "/satspay/static",
        "name": "satspay_static",
    }
]


def satspay_renderer():
    return template_renderer(["satspay/templates"])


from .tasks import wait_for_paid_invoices
from .views import *  # noqa: F401,F403
from .views_api import *  # noqa: F401,F403


def satspay_start():
    loop = asyncio.get_event_loop()
    task = loop.create_task(catch_everything_and_restart(wait_for_paid_invoices))
    scheduled_tasks.append(task)
