"""
Azure OpenAI Realtime API client implementation.

Provides a WebSocket-based client for the Azure OpenAI Realtime preview API,
following Azure best practices for secure, resilient connections.
"""

import os
import json
import logging
import asyncio
from datetime import datetime
from typing import Any, Optional

import websockets

from .event_system import RealtimeEventHandler

logger = logging.getLogger(__name__)


class RealtimeAPI(RealtimeEventHandler):
    """
    Low-level client for the Azure OpenAI Realtime API.

    Manages WebSocket connection lifecycle and message handling, implementing
    the Azure best practice of event-based communication for real-time services.
    """

    def __init__(self) -> None:
        """Initialize the API client with Azure configuration."""
        super().__init__()
        self.url = os.environ["AZURE_OPENAI_ENDPOINT"]
        self.api_key = os.environ["AZURE_OPENAI_API_KEY"]
        self.api_version = "2024-10-01-preview"
        self.azure_deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]
        self.ws: Optional[websockets.ClientConnection] = None

    def is_connected(self) -> bool:
        """Check if the WebSocket connection is established."""
        return self.ws is not None

    def log(self, *args) -> None:
        """Log WebSocket activity with timestamps."""
        logger.info("[WebSocket/%s] %s", datetime.now().isoformat(), " ".join(str(arg) for arg in args))

    async def connect(self) -> None:
        """
        Establish WebSocket connection to Azure OpenAI Realtime API.

        Raises:
            Exception: If already connected
        """

        if self.is_connected():
            raise Exception("Already connected")

        url = f"{self.url}/openai/realtime?api-version={self.api_version}&deployment={self.azure_deployment}&api-key={self.api_key}"
        self.ws = await websockets.connect(url)
        self.log(f"Connected to {self.url}")
        asyncio.create_task(self._receive_messages())

    async def _receive_messages(self) -> None:
        """Background task that processes incoming WebSocket messages."""
        if self.ws is None:
            return

        async for message in self.ws:
            event = json.loads(message)
            if event['type'] == "error":
                logger.error("ERROR", message)
            self.log("received:", event)
            self.dispatch(f"server.{event['type']}", event)
            self.dispatch("server.*", event)

    async def send(self, event_name: str, data: Optional[dict[str, Any]] = None) -> None:
        """
        Send an event to the Azure OpenAI Realtime API.

        Args:
            event_name: The type of event to send
            data: Additional payload data

        Raises:
            Exception: If not connected or data is invalid
        """

        if not self.is_connected():
            raise Exception("RealtimeAPI is not connected")

        data = data or {}
        if not isinstance(data, dict):
            raise Exception("data must be a dictionary")

        event = {
            "event_id": self._generate_id("evt_"),
            "type": event_name,
            **data
        }

        self.dispatch(f"client.{event_name}", event)
        self.dispatch("client.*", event)
        self.log("sent:", event)

        ws = self.ws
        if ws is None:
            raise Exception("RealtimeAPI WebSocket connection lost")

        await ws.send(json.dumps(event))

    def _generate_id(self, prefix: str) -> str:
        """Generate a unique ID with the given prefix."""
        return f"{prefix}{int(datetime.now().timestamp() * 1000)}"

    async def disconnect(self) -> None:
        """Close the WebSocket connection gracefully."""
        if self.ws:
            await self.ws.close()
            self.ws = None
            self.log(f"Disconnected from {self.url}")
