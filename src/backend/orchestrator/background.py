import time
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from orchestrator import logger
from orchestrator.utils import cleanup_session, log_memory_usage

# Import sessions from main, where it is defined as a global
try:
    from orchestrator.main import sessions
except ImportError:
    sessions = {}  # Fallback for type checking; should not happen in production


async def resource_cleanup_task():
    """Background task to clean up inactive sessions and free resources.

    Runs every 60 seconds and removes sessions that have been inactive for over 5 minutes.
    Logs memory usage for Azure monitoring.
    """
    while True:
        try:
            current_time = time.time()
            inactive_sessions = []
            for session_id, client in list(sessions.items()):
                last_activity = getattr(client, "last_activity", 0)
                if current_time - last_activity > 300:  # 5 minutes
                    inactive_sessions.append(session_id)
            for session_id in inactive_sessions:
                logger.info(f"Cleaning up inactive session {session_id}")
                await cleanup_session(session_id)
            log_memory_usage()
        except Exception as e:
            logger.error(f"Error in resource cleanup task: {e}", exc_info=True)
        await asyncio.sleep(60)

async def translation_orchestration_task():
    """Placeholder for translation orchestration background task.

    Extend this to manage translation jobs, polling, or orchestration as needed.
    """
    while True:
        try:
            # Example: could poll for translation jobs, manage queues, etc.
            await asyncio.sleep(10)
        except Exception as e:
            logger.error(f"Error in translation orchestration task: {e}", exc_info=True)
            await asyncio.sleep(10)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context to start background tasks on startup and ensure cleanup on shutdown."""
    cleanup = asyncio.create_task(resource_cleanup_task())
    translation = asyncio.create_task(translation_orchestration_task())
    try:
        yield
    finally:
        cleanup.cancel()
        translation.cancel()
        await asyncio.gather(cleanup, translation, return_exceptions=True)
