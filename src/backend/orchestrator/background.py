
import time
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from orchestrator import __app__, __author__, __version__, logger


async def resource_cleanup_task():
    """Azure-recommended background task to maintain resource efficiency"""
    while True:
        try:
            current_time = time.time()
            inactive_sessions = []

            for session_id, client in sessions.items():
                last_activity = getattr(client, "last_activity", 0)
                if current_time - last_activity > 300:  # 5 minutes
                    inactive_sessions.append(session_id)
            for session_id in inactive_sessions:
                logger.info(f"Cleaning up inactive session {session_id}")
                await cleanup_session(session_id)
                
        except Exception as e:
            logger.error(f"Error in resource cleanup task: {e}", exc_info=True)

        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the ML model
    ml_models["answer_to_everything"] = fake_answer_to_everything_ml_model
    yield
    # Clean up the ML models and release the resources
    ml_models.clear()
