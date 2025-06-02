"""
Utility functions for the Orchestrator backend.

Provides helpers for logging, user/session management, and session cleanup.
"""

import os
import time
import uuid
import psutil

from fastapi import status, HTTPException, WebSocket
from orchestrator import __app__, __author__, __version__, logger
from orchestrator.engine.client import TranslateCommand

# Global session management dictionaries
sessions: dict[str, TranslateCommand] = {}
user_sessions: dict[str, str] = {}
session_users: dict[str, str] = {}
track_ids: dict[str, str] = {}


def log_memory_usage():
    """Log current process memory usage for Azure monitoring.

    Returns:
        None
    """
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()
    logger.info(f"Memory usage: {memory_info.rss / 1024 / 1024:.2f} MB")


def generate_user_id(username: str) -> str:
    """Generate a unique user ID with random suffix for anonymous users.

    Args:
        username (str): The username.

    Returns:
        str: A unique user ID.
    """
    if username.startswith("anonymous-"):
        session_id = str(uuid.uuid4())[:8]
        return f"{username}_{session_id}"
    return username


async def cleanup_session(call_connection_id: str) -> None:
    """Clean up and remove a call connection and its resources.

    Args:
        call_connection_id (str): The call connection ID to clean up.
    """
    client = sessions.pop(call_connection_id, None)
    track_ids.pop(call_connection_id, None)
    # If the client has a disconnect method, call it
    if client and hasattr(client, "_raw_ws"):
        await client._raw_ws.__aexit__(None, None, None)
        logger.info(f"Disconnected client for call_connection_id {call_connection_id}")


def get_client_or_404(session_id: str) -> TranslateCommand:
    """Get a client by session ID or raise a 404 error.

    Args:
        session_id (str): The session ID.

    Returns:
        TranslateCommand: The client for this session.

    Raises:
        HTTPException: If session not found.
    """
    client = sessions.get(session_id)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid session_id"
        )
    return client


async def setup_realtime_client(session_id: str, user_id: str, ws: WebSocket, entry_language: str, exit_language: str) -> None:
    """Set up a new TranslateCommand instance and track the session.

    Args:
        session_id (str): Unique session identifier.
        user_id (str): User identifier.
        ws (WebSocket): The websocket connection for this session.
        entry_language (str): Source language code.
        exit_language (str): Target language code.
    """
    realtime_client = TranslateCommand(ws)
    realtime_client.configure(entry_language, exit_language)
    setattr(realtime_client, "last_activity", time.time())
    # Track session
    sessions[session_id] = realtime_client
    user_sessions[user_id] = session_id
    session_users[session_id] = user_id
    track_ids[session_id] = str(uuid.uuid4())
    # Event handling is now done via observer or explicit orchestration, not .on()