from fastapi import WebSocket
import json
import os


class ConnectionManager:
    """Manages WebSocket connections and broadcasts events to all clients."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.max_total_connections = int(os.getenv("MAX_WS_CONNECTIONS", "500"))

    async def connect(self, websocket: WebSocket, client_ip: str | None = None):
        if len(self.active_connections) >= self.max_total_connections:
            await websocket.close(code=1013, reason="Server at capacity")
            return

        await websocket.accept()
        self.active_connections.append(websocket)
        ip_info = f" ip={client_ip}" if client_ip else ""
        print(f"[WS] Client connected.{ip_info} Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"[WS] Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, event_type: str, data: dict):
        """Broadcast an event to all connected WebSocket clients (parallel)."""
        import asyncio
        message = json.dumps({"type": event_type, "data": data})
        disconnected = []

        async def _send(conn):
            try:
                await conn.send_text(message)
            except Exception:
                disconnected.append(conn)

        await asyncio.gather(*[_send(c) for c in self.active_connections])

        for conn in disconnected:
            self.disconnect(conn)


# Singleton
manager = ConnectionManager()
