import asyncio
import json

from lnbits.settings import settings
from loguru import logger
from websockets.client import connect

ws_receive_queue: asyncio.Queue[dict] = asyncio.Queue()
ws_send_queue: asyncio.Queue[dict] = asyncio.Queue()


async def consumer_handler(websocket):
    async for message in websocket:
        logger.debug(f"Received message: {message[:69]}...")
        ws_receive_queue.put_nowait(json.loads(message))


async def producer_handler(websocket):
    while settings.lnbits_running:
        message = json.dumps(await ws_send_queue.get())
        logger.debug(f"Send message: {message[:69]}...")
        await websocket.send(message)


async def websocket_handler():
    uri = "wss://mempool.space/testnet/api/v1/ws"
    logger.info(f"websocket_handler: Connecting to {uri}...")
    async with connect(uri) as websocket:
        logger.info(f"websocket_handler: Connected to {uri}")
        consumer_task = asyncio.create_task(consumer_handler(websocket))
        producer_task = asyncio.create_task(producer_handler(websocket))
        _, pending = await asyncio.wait(
            [consumer_task, producer_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()

    raise Exception("websocket_handler unexpectedly finished")
