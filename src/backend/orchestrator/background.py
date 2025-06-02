import time
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from orchestrator import logger
from orchestrator.utils import cleanup_session, log_memory_usage
from orchestrator.engine.observer import RoomUserObserver, LoggingObserver

room_user_observer = None  # Will be set in lifespan


async def resource_cleanup_task():
    """Background task to clean up inactive call connections and free resources.

    Runs every 10 minutes and removes call connections that have been inactive for over 5 minutes.
    Logs memory usage for Azure monitoring.
    """
    global room_user_observer
    while True:
        try:
            current_time = time.time()
            inactive_connections = []
            if room_user_observer is not None:
                # Use invokers as the source of truth
                for call_connection_id, invoker in list(room_user_observer._invokers.items()):
                    ws = getattr(invoker.command, 'ws', None)
                    last_activity = getattr(ws, "last_activity", 0) if ws else 0
                    if current_time - last_activity > 300:  # 5 minutes
                        inactive_connections.append(call_connection_id)
                for call_connection_id in inactive_connections:
                    logger.info(f"Cleaning up inactive ACS call_connection_id={call_connection_id}")
                    await room_user_observer.cleanup_invoker(call_connection_id)
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
