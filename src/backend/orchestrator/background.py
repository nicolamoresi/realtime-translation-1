import time
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from orchestrator import logger
from orchestrator.utils import cleanup_session, log_memory_usage
from orchestrator.engine.observer import RoomUserObserver, LoggingObserver

room_user_observer = None  # Will be set in lifespan


async def resource_cleanup_task():
    """Background task to clean up inactive sessions and free resources.

    Runs every 60 seconds and removes sessions that have been inactive for over 5 minutes.
    Logs memory usage for Azure monitoring.
    """
    global room_user_observer
    while True:
        try:
            current_time = time.time()
            inactive_sessions = []
            # Use ACS connection sessions as the source of truth
            if room_user_observer is not None:
                connection_sessions = getattr(room_user_observer, '_connection_session', {})
                for call_connection_id, session_id in list(connection_sessions.items()):
                    # Try to get the websocket and check last activity
                    ws = room_user_observer.get_invoker_for_connection(call_connection_id)
                    last_activity = getattr(ws, "last_activity", 0) if ws else 0
                    if current_time - last_activity > 300:  # 5 minutes
                        inactive_sessions.append((call_connection_id, session_id))
                for call_connection_id, session_id in inactive_sessions:
                    logger.info(f"Cleaning up inactive ACS session {session_id} (call_connection_id={call_connection_id})")
                    # Remove from observer's connection/session maps
                    room_user_observer.unregister_invoker(session_id)
                    room_user_observer._connection_session.pop(call_connection_id, None)
                    # Optionally, end the ACS call if needed
                    try:
                        if hasattr(room_user_observer, 'acs_client') and room_user_observer.acs_client:
                            call_conn = room_user_observer.acs_client.get_call_connection(call_connection_id)
                            call_conn.hang_up(is_for_everyone=True)
                    except Exception as e:
                        logger.error(f"Error hanging up ACS call {call_connection_id}: {e}")
            log_memory_usage()
        except Exception as e:
            logger.error(f"Error in resource cleanup task: {e}", exc_info=True)
        await asyncio.sleep(600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global room_user_observer
    room_user_observer = RoomUserObserver()
    app.state.room_user_observer = room_user_observer  # Make observer available via app.state
    room_user_observer.attach(LoggingObserver())
    cleanup = asyncio.create_task(resource_cleanup_task())
    try:
        yield
    finally:
        cleanup.cancel()
        await asyncio.gather(cleanup, return_exceptions=True)
