import asyncio
import websockets
import json

async def test():
    async with websockets.connect("ws://localhost:8765/ws/dashboard") as websocket:
        msg = await websocket.recv()
        print(msg)

asyncio.run(test())
