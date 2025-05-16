"""
Main entry point for the Orchestrator real-time translation backend.

This FastAPI app provides endpoints for real-time audio and text translation using Azure OpenAI, Azure Communication Services, and Event Grid. It manages user sessions, WebSocket audio streaming, and ACS call automation events, and coordinates translation using the Command and Observer patterns.

Attributes:
    app (FastAPI): The FastAPI application instance.
    room_user_observer (RoomUserObserver): The main observer for user/room/call state.

"""

import os
import time
import base64
import asyncio
import psutil
import json
from fastapi import FastAPI, Request, WebSocket, APIRouter
from fastapi.security import OAuth2PasswordBearer
from fastapi_mcp import FastApiMCP
from starlette.middleware.cors import CORSMiddleware

from orchestrator import __app__, __author__, __version__, logger
from orchestrator.schemas import SuccessMessage
from orchestrator.schemas.endpoints import UserRoomLanguageRequest, UserRoomLanguageResponse
from orchestrator.background import lifespan
from orchestrator.engine import TranslateCommand, Invoker
from orchestrator.engine.observer import RoomUserObserver, LoggingObserver
from orchestrator.utils import session_users


tags_metadata: list[dict] = [
    {
        "name": "Real-Time Translation",
        "description": "Endpoints for real-time audio and text translation using Azure OpenAI, Azure Communication Services (ACS), and Event Grid. Includes WebSocket streaming, session management, and translation orchestration.",
    },
    {
        "name": "Sessions",
        "description": "Session and user management for translation and communication rooms.",
    },
    {
        "name": "Health",
        "description": "Health check and monitoring endpoints for the orchestrator backend.",
    },
    {
        "name": "Admin",
        "description": "Administrative and utility endpoints for orchestration and diagnostics.",
    },
]

description: str = """
Azure Real-Time Translation Orchestrator

A robust FastAPI backend for real-time, low-latency audio and text translation using Azure OpenAI (gpt-4o-realtime), Azure Communication Services (ACS), and Event Grid. Features include:
- Real-time WebSocket endpoints for streaming audio and translation events
- Session and user management for multi-user rooms
- Integration with ACS for call automation and media streaming
- Event-driven architecture with clear separation of concerns
- Extensible, type-safe, and production-ready codebase

Follows Azure best practices for security, scalability, and maintainability.
"""

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
app = FastAPI(lifespan=lifespan, title=__app__, version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

mcp = FastApiMCP(app)

# Initialize the observer and attach a logging observer (or your custom event observer)
room_user_observer = RoomUserObserver()
room_user_observer.attach(LoggingObserver())


@app.get("/")
async def health_check(request: Request):
    """Health check endpoint with Azure-recommended metrics.

    Args:
        request (Request): The incoming HTTP request.

    Returns:
        SuccessMessage: Health and status metrics for the app.
    """
    # Fix: request.client may be None
    client_host = request.client.host if request.client else "unknown"
    logger.info("Health check endpoint called from %s", client_host)
    memory_usage = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    
    return SuccessMessage(
        title="App Running",
        message="App up and running. Check content for details",
        content={
            "timestamp": time.time(),
            "memory_mb": round(memory_usage, 2),
            "user_count": len(set(session_users.values())),
            "version": __version__
        }
    )

@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    logger.info("Client connected to WebSocket")

    command = TranslateCommand(websocket)
    command.configure(entry_language="en", exit_language="zh")  # TODO: Make dynamic if needed
    invoker = Invoker(command, create_response=True)

    async with invoker as cmd:
        async def from_acs_to_model():
            while True:
                try:
                    data = await websocket.receive_text()
                    msg = json.loads(data)
                    if msg.get("kind") == "AudioData":
                        audio_b64 = msg["audioData"]["data"]
                        await command.send_audio_from_acs(audio_b64, msg["audioData"])
                except Exception as e:
                    logger.info(f"WebSocket receive closed: {e}")
                    break

        async def from_model_to_acs():
            async for event in command.receive_events():
                # Robustly handle audio events (send as binary)
                try:
                    # Support both dict and object attribute access
                    kind = getattr(event, 'kind', None) if not isinstance(event, dict) else event.get('kind')
                    audio_data = None
                    if kind == "AudioData":
                        audio_data_obj = getattr(event, 'audioData', None) if not isinstance(event, dict) else event.get('audioData')
                        if audio_data_obj:
                            audio_b64 = getattr(audio_data_obj, 'data', None) if not isinstance(audio_data_obj, dict) else audio_data_obj.get('data')
                            if audio_b64:
                                audio_bytes = base64.b64decode(audio_b64)
                                await websocket.send_bytes(audio_bytes)
                                continue
                    try:
                        await websocket.send_text(json.dumps(event))
                    except TypeError:
                        await websocket.send_text(str(event))
                except Exception as e:
                    logger.warning(f"Error processing model event for websocket: {e}")

        task_recv = asyncio.create_task(from_acs_to_model())
        task_send = asyncio.create_task(from_model_to_acs())
        done, pending = await asyncio.wait([task_recv, task_send], return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    await websocket.close()


@app.post("/incoming-call")
async def incoming_call_handler(request: Request):
    """Handle incoming ACS call events from Event Grid.

    Args:
        request (Request): The incoming HTTP request with Event Grid payload.

    Returns:
        SuccessMessage: Result of call handling or subscription validation.
    """
    data = await request.json()
    for event_dict in data:
        result = await room_user_observer.handle_incoming_call(event_dict)
        if result and "call_connection_id" in result:
            session_id = result.get("guid") or result.get("session_id")
            call_connection_id = result["call_connection_id"]
            if session_id:
                room_user_observer.map_connection_to_session(call_connection_id, session_id)
        if result and "validationResponse" in result:
            return SuccessMessage(title="", message="", content={"validationResponse": result["validationResponse"]})
    return SuccessMessage(
        title="Incoming call handler",
        message="Incoming call event processed successfully"
    )

@app.post("/api/callbacks/{contextId}")
async def callbacks(request: Request):
    """Handle ACS callback events (CallConnected, MediaStreamingStarted, etc).

    Args:
        request (Request): The incoming HTTP request with callback events.

    Returns:
        SuccessMessage: Result of callback event handling.
    """
    data = await request.json()
    for event in data:
        await room_user_observer.handle_callback_event(event)
    return SuccessMessage(
        title="Incoming call handler",
        message="Incoming call event processed successfully"
    )

router = APIRouter()

@router.post("/api/room/user-language", response_model=UserRoomLanguageResponse)
async def user_room_language_endpoint(request: UserRoomLanguageRequest):
    """Endpoint to inform the backend of the user, room, and preferred language when joining a room."""
    bot_id = "interpreter-bot"  # This should be a unique, known ID for the bot
    bot_info = {
        "acs_id": bot_id,
        "display_name": "Interpreter",
        "role": "Bot",
        "language": request.language  # Use the user's language as the bot's source language
    }
    room_user_observer.join_room(bot_id, request.room_id, bot_info)
    if hasattr(room_user_observer, "join_bot_to_acs_call"):
        room_user_observer.join_bot_to_acs_call(request.room_id, bot_info)
    else:
        # Fallback: If not implemented, log or pass
        logger.info(f"Bot join to ACS call for room {request.room_id} would be triggered here.")
    return UserRoomLanguageResponse(
        user_id=request.user_id,
        room_id=request.room_id,
        language=request.language,
        bot_display_name="Interpreter"
    )

app.include_router(router)

mcp.mount()
