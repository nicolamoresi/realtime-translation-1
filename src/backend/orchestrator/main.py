"""
Main entry point for the Orchestrator real-time translation backend.

This FastAPI app provides endpoints for real-time audio and text translation using Azure OpenAI, Azure Communication Services, and Event Grid. It manages user sessions, WebSocket audio streaming, and ACS call automation events, and coordinates translation using the Command and Observer patterns.

Attributes:
    app (FastAPI): The FastAPI application instance.
    room_user_observer (RoomUserObserver): The main observer for user/room/call state.

"""

import os
import time
import json
import psutil
from fastapi import FastAPI, Request, WebSocket
from fastapi.security import OAuth2PasswordBearer
from fastapi_mcp import FastApiMCP
from starlette.middleware.cors import CORSMiddleware

from orchestrator import __app__, __author__, __version__, logger
from orchestrator.schemas import SuccessMessage
from orchestrator.background import lifespan
from orchestrator.engine import TranslateCommand, Invoker
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
    """WebSocket endpoint for real-time audio translation.

    Args:
        websocket (WebSocket): The WebSocket connection for the client.

    This endpoint manages the WebSocket connection for a client, registering the connection with the
    RoomUserObserver, and finding or creating the appropriate Invoker for translation. It also
    handles the real-time translation loop, receiving audio data from the client, sending it to
    Azure OpenAI for translation, and streaming the translation events back to the client.

    The endpoint expects the following query parameters in the WebSocket URL:
    - room_id: The ID of the room the client is joining.
    - call_connection_id: The ID of the call connection (ACS) for this session.
    - session_id: The ID of the session for this translation instance.

    The translation loop will continue until the WebSocket is disconnected.
    """
    # Accept the connection
    await websocket.accept()

    call_connection_id = websocket.headers.get("x-ms-call-connection-id")
    room_user_observer = app.state.room_user_observer

    translate_command = TranslateCommand(ws=websocket)
    translate_command.configure(entry_language="en", exit_language="zh")  # Adjust languages as needed
    invoker = Invoker(command=translate_command)
    room_user_observer.register_invoker(call_connection_id, invoker)

    async with invoker:
        try:
            while True:
                # Receive audio data from the websocket (from ACS or client)
                data = await websocket.receive()
                if data["type"] == "websocket.disconnect":
                    break
                data_dict = json.loads(data.get('text', ''))
                if data_dict.get('kind') == 'AudioData':
                    audio_bytes = data_dict.get('audioData', {}).get('data', b'')
                    # Send audio to AOAI for translation
                    await invoker.command.send_audio_from_acs(audio_bytes, meta={
                        "call_connection_id": call_connection_id,
                    })
                    # Stream translated events back to the websocket (if needed)
                    async for event in invoker.command.receive_events():
                        # You can customize what to send back; here, just send the event as JSON
                        await websocket.send_json(event if isinstance(event, dict) else event.__dict__)
        except Exception as e:
            logger.error(f"WebSocket translation session error: {e}")


@app.post("/incoming-call")
async def incoming_call_handler(request: Request):
    """Handle incoming ACS call events from Event Grid.

    Args:
        request (Request): The incoming HTTP request with Event Grid payload.

    Returns:
        SuccessMessage: Result of call handling or subscription validation.
    """
    
    data = await request.json()
    room_user_observer = app.state.room_user_observer
    for event_dict in data:
        result = await room_user_observer.handle_incoming_call(event_dict)
        if result and "validationResponse" in result:
            return SuccessMessage(title="", message="", content={"validationResponse": result["validationResponse"]})
    return SuccessMessage(title="Incoming call handler", message="Incoming call event processed successfully")


@app.post("/callbacks/{contextId}")
async def callbacks(request: Request):
    """Handle ACS callback events (CallConnected, MediaStreamingStarted, etc).

    Args:
        request (Request): The incoming HTTP request with callback events.

    Returns:
        SuccessMessage: Result of callback event handling.
    """
    data = await request.json()
    room_user_observer = request.app.state.room_user_observer
    for event in data:
        await room_user_observer.handle_callback_event(event)
    return SuccessMessage(title="Incoming call handler", message="Incoming call event processed successfully")


mcp.mount()
