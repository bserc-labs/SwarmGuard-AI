import os
import json
import asyncio
from fastapi import WebSocket
from typing import List
from broadcaster import Broadcast

# Default to memory:// for local dev if Redis is unavailable
REDIS_URL = os.environ.get("REDIS_URL", "memory://")
broadcast_client = Broadcast(REDIS_URL)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._listener_task = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        
        if not self._listener_task:
            await broadcast_client.connect()
            self._listener_task = asyncio.create_task(self._listen_to_redis())

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def _listen_to_redis(self):
        async with broadcast_client.subscribe("swarmguard_alerts") as subscriber:
            async for event in subscriber:
                try:
                    message = json.loads(event.message)
                    for connection in list(self.active_connections):
                        try:
                            await connection.send_json(message)
                        except Exception:
                            self.disconnect(connection)
                except Exception as e:
                    print(f"Error processing pubsub message: {e}")

    async def broadcast(self, message: dict):
        await broadcast_client.publish("swarmguard_alerts", json.dumps(message))

ws_manager = ConnectionManager()
