"""
Module for managing video streaming over WebSocket connections.

This module defines the VideoStreamFacade class, which provides methods to
start and stop video streams in chat rooms and broadcast video frames to
registered WebSocket connections.
"""

from fastapi import WebSocket


class VideoStreamFacade:
    """
    Facade for handling video streams over WebSocket connections.
    
    Attributes:
        _streams (dict[str, set[WebSocket]]): Maps room IDs to sets of WebSocket connections.
    """

    def __init__(self) -> None:
        """
        Initialize the VideoStreamFacade with an empty streams dictionary.
        """
        self._streams: dict[str, set[WebSocket]] = {}

    async def start_stream(self, room_id: str, ws: WebSocket) -> None:
        """
        Start a video stream for a specific room by registering the WebSocket connection.

        Args:
            room_id (str): The identifier for the room.
            ws (WebSocket): The WebSocket connection to register.
        """
        await ws.accept()
        self._streams.setdefault(room_id, set()).add(ws)

    def stop_stream(self, room_id: str, ws: WebSocket) -> None:
        """
        Stop a video stream for a specific room by unregistering the WebSocket connection.

        Args:
            room_id (str): The identifier for the room.
            ws (WebSocket): The WebSocket connection to unregister.
        """
        if room_id in self._streams:
            self._streams[room_id].discard(ws)

    async def broadcast_video(self, room_id: str, frame: bytes) -> None:
        """
        Broadcast a video frame to all WebSocket connections in a specific room.

        Args:
            room_id (str): The identifier for the room.
            frame (bytes): The video frame data to broadcast.
        """
        for connection in self._streams.get(room_id, []):
            await connection.send_bytes(frame)
