import os
import time
import uuid
import psutil

from fastapi import status, HTTPException
from orchestrator import __app__, __author__, __version__, logger


def log_memory_usage():
    """Log current process memory usage for Azure monitoring"""
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()
    logger.info(f"Memory usage: {memory_info.rss / 1024 / 1024:.2f} MB")


def generate_user_id(username: str) -> str:
    """
    Generate a unique user ID with random suffix for anonymous users.

    Args:
        username: The username

    Returns:
        A unique user ID
    """
    if username.startswith("anonymous-"):
        session_id = str(uuid.uuid4())[:8]
        return f"{username}_{session_id}"
    return username


async def cleanup_session(session_id: str) -> None:
    """
    Clean up a session and free all associated resources.
    
    Args:
        session_id: The session ID to clean up
    """
    client = sessions.pop(session_id, None)
    track_ids.pop(session_id, None)

    user_id = session_users.pop(session_id, None)
    if user_id:
        user_sessions.pop(user_id, None)

    if client and client.is_connected():
        await client.disconnect()
        logger.info(f"Disconnected client for session {session_id}")


def get_client_or_404(session_id: str) -> RealtimeClient:
    """
    Get a client by session ID or raise a 404 error.
    
    Args:
        session_id: The session ID
        
    Returns:
        The RealtimeClient for this session
        
    Raises:
        HTTPException: If session not found
    """
    client = sessions.get(session_id)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid session_id"
        )
    return client


async def setup_realtime_client(session_id: str, user_id: str, system_prompt: str) -> None:
    """
    Set up a new RealtimeClient instance with event handlers.
    
    Args:
        session_id: Unique session identifier
        user_id: User identifier
        system_prompt: System instructions for the AI
    """

    realtime_client = RealtimeClient(system_prompt=system_prompt)
    setattr(realtime_client, "last_activity", time.time())
    
    # Track session
    sessions[session_id] = realtime_client
    user_sessions[user_id] = session_id
    session_users[session_id] = user_id
    track_ids[session_id] = str(uuid.uuid4())
    
    # Set up event handlers
    async def handle_conversation_updated(event):
        # Update last activity timestamp
        setattr(realtime_client, "last_activity", time.time())
    
    async def handle_item_completed(event):
        """Log transcript when the assistant finishes a message."""
        try:
            item = event.get("item", {})
            transcript = item.get("formatted", {}).get("transcript", "")
            if transcript:
                logger.info(f"Session {session_id} Assistant: {transcript}")
        except Exception as e:
            logger.error(f"Error processing completed item: {e}")
    
    async def handle_conversation_interrupt(event):
        track_ids[session_id] = str(uuid.uuid4())
    
    async def handle_error(event):
        logger.error(f"Realtime error in session {session_id}: {event}")

    realtime_client.on("conversation.updated", handle_conversation_updated)
    realtime_client.on("conversation.item.completed", handle_item_completed)
    realtime_client.on("conversation.interrupted", handle_conversation_interrupt)
    realtime_client.on("error", handle_error)