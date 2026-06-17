"""TUI Gateway - WebSocket server for Ink UI to communicate with Python backend."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

try:
    import websockets
    from websockets.asyncio.server import ServerConnection
except ImportError:
    websockets = None  # type: ignore

logger = logging.getLogger(__name__)


class TUIGateway:
    """WebSocket server for terminal UI communication."""

    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self.clients: set[ServerConnection] = set()
        self.request_handlers: dict[str, Callable] = {}
        self.server = None

    def register_handler(self, method: str, handler: Callable) -> None:
        """Register a JSON-RPC method handler."""
        self.request_handlers[method] = handler

    async def handle_client(self, websocket: ServerConnection, path: str) -> None:
        """Handle incoming WebSocket connection."""
        self.clients.add(websocket)
        logger.info(f"Client connected: {websocket.remote_address}")

        try:
            async for message in websocket:
                await self._handle_message(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client disconnected: {websocket.remote_address}")
        finally:
            self.clients.discard(websocket)

    async def _handle_message(self, websocket: ServerConnection, message: str) -> None:
        """Handle incoming JSON-RPC message."""
        try:
            data = json.loads(message)
            method = data.get("method")
            params = data.get("params", {})
            msg_id = data.get("id")

            if method not in self.request_handlers:
                await self._send_response(
                    websocket,
                    msg_id,
                    error={"code": -32601, "message": f"Method not found: {method}"},
                )
                return

            # Call the handler
            handler = self.request_handlers[method]
            try:
                result = await handler(**params) if asyncio.iscoroutinefunction(handler) else handler(**params)
                await self._send_response(websocket, msg_id, result=result)
            except Exception as e:
                logger.exception(f"Error handling {method}")
                await self._send_response(
                    websocket,
                    msg_id,
                    error={"code": -32603, "message": str(e)},
                )
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON: {message}")
            await self._send_response(
                websocket,
                None,
                error={"code": -32700, "message": "Parse error"},
            )

    async def _send_response(
        self,
        websocket: ServerConnection,
        msg_id: str | int | None,
        result: Any = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        """Send JSON-RPC response."""
        response = {
            "jsonrpc": "2.0",
            "id": msg_id,
        }
        if error:
            response["error"] = error
        else:
            response["result"] = result

        try:
            await websocket.send(json.dumps(response))
        except Exception as e:
            logger.error(f"Failed to send response: {e}")

    async def start(self) -> None:
        """Start the WebSocket server."""
        if not websockets:
            raise ImportError("websockets library required for TUI Gateway. Install with: pip install websockets")

        self.server = await websockets.serve(self.handle_client, self.host, self.port)
        logger.info(f"TUI Gateway started on ws://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("TUI Gateway stopped")

    async def run(self) -> None:
        """Run the gateway indefinitely."""
        await self.start()
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            await self.stop()
