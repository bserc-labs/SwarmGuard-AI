import asyncio
import json
import os
from collections import defaultdict

from broadcaster import Broadcast
from fastapi import WebSocket

from utils.logger import logger

# memory:// keeps the pub/sub working for a single-process dev run. In a
# multi-worker deployment REDIS_URL must be set, otherwise each worker only
# reaches the clients that happen to be connected to it.
REDIS_URL = os.environ.get("REDIS_URL", "memory://")
broadcast_client = Broadcast(REDIS_URL)

# One channel per organization. Subscribing per-org rather than filtering a
# shared channel means a worker never even receives another tenant's payloads.
CHANNEL_PREFIX = "swarmguard.org."


def channel_for(organization_id: int) -> str:
    return f"{CHANNEL_PREFIX}{organization_id}"


class ConnectionManager:
    """
    Tenant-scoped WebSocket fan-out.

    Connections are keyed by organization_id. Previously this held a single flat
    list and every message went to every socket, so one organization's operators
    received another's telemetry and alerts in real time — the one hole that
    undid the tenancy model enforced on every HTTP route.
    """

    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._listeners: dict[int, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._connected = False

    # -- lifecycle ---------------------------------------------------------

    async def _ensure_broadcaster(self) -> None:
        if self._connected:
            return
        try:
            await broadcast_client.connect()
            self._connected = True
        except Exception as exc:
            # Direct delivery to locally-held sockets still works without the
            # broker; only cross-worker fan-out is lost.
            logger.error(f"Broadcast backend unavailable, using local delivery only: {exc}")

    async def connect(self, websocket: WebSocket, organization_id: int) -> None:
        await websocket.accept()

        async with self._lock:
            self._connections[organization_id].add(websocket)
            first_for_org = organization_id not in self._listeners

        await self._ensure_broadcaster()

        if first_for_org and self._connected:
            self._listeners[organization_id] = asyncio.create_task(
                self._subscribe(organization_id)
            )

        logger.info(
            f"WebSocket connected (org={organization_id}, "
            f"clients={len(self._connections[organization_id])})"
        )

    async def disconnect(self, websocket: WebSocket, organization_id: int) -> None:
        async with self._lock:
            self._connections[organization_id].discard(websocket)
            empty = not self._connections[organization_id]
            if empty:
                self._connections.pop(organization_id, None)
                task = self._listeners.pop(organization_id, None)
            else:
                task = None

        if task is not None:
            task.cancel()

    # -- delivery ----------------------------------------------------------

    async def _subscribe(self, organization_id: int) -> None:
        """Relay messages published by other workers to this worker's sockets."""
        try:
            async with broadcast_client.subscribe(channel_for(organization_id)) as subscriber:
                async for event in subscriber:
                    try:
                        payload = json.loads(event.message)
                    except json.JSONDecodeError:
                        logger.warning("Discarded malformed pub/sub payload")
                        continue
                    await self._send_local(organization_id, payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"Subscription for org {organization_id} ended: {exc}")

    async def _send_local(self, organization_id: int, message: dict) -> None:
        """Write to sockets held by this process only."""
        async with self._lock:
            targets = list(self._connections.get(organization_id, ()))

        dead: list[WebSocket] = []
        for connection in targets:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)

        for connection in dead:
            await self.disconnect(connection, organization_id)

    async def broadcast(self, message: dict, organization_id: int) -> None:
        """
        Deliver to one organization.

        organization_id is required: there is no all-tenant broadcast, so a
        caller cannot leak across tenants by forgetting an argument.
        """
        if organization_id is None:
            raise ValueError("organization_id is required to broadcast")

        if self._connected:
            # Publish only. Every worker, including this one, delivers from its
            # own subscription — publishing *and* sending locally would deliver
            # twice to clients on this worker.
            try:
                await broadcast_client.publish(
                    channel_for(organization_id), json.dumps(message, default=str)
                )
                return
            except Exception as exc:
                logger.error(f"Publish failed, falling back to local delivery: {exc}")

        await self._send_local(organization_id, message)

    def client_count(self, organization_id: int) -> int:
        return len(self._connections.get(organization_id, ()))

    async def shutdown(self) -> None:
        for task in list(self._listeners.values()):
            task.cancel()
        self._listeners.clear()
        self._connections.clear()
        if self._connected:
            try:
                await broadcast_client.disconnect()
            except Exception:
                pass
            self._connected = False


ws_manager = ConnectionManager()
