"""
Real-time Translation API
-------------------------
Lightweight FastAPI application providing real-time translation services using 
Azure OpenAI's Realtime API. The application supports audio streaming, text 
messages, and session management.

Key endpoints:
- POST /chat/start  → Create session and get session_id
- POST /chat/message → Send text for translation
- WS /ws/audio → Stream audio with control messages
- POST /chat/stop → Close session and free resources

Uses Azure OpenAI Realtime API for efficient streaming translation with minimal latency.
"""

import os
import time
import uuid
import asyncio
import psutil
from urllib.parse import urlparse, urlunparse, urlencode

from starlette.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Request, WebSocket
from fastapi.security import OAuth2PasswordBearer
from fastapi_mcp import FastApiMCP

from orchestrator import __app__, __author__, __version__, logger
from orchestrator.schemas import SuccessMessage, ErrorMessage
from orchestrator.background import lifespan
from orchestrator.engine import TranslateCommand, Invoker


tags_metadata: list[dict] = [
    {
        "name": "Inference",
        "description": """
        Use agents to process multi-modal data for RAG.
        """,
    },
    {
        "name": "CRUD - Assemblies",
        "description": "CRUD endpoints for Assembly model.",
    },
    {
        "name": "CRUD - Tools",
        "description": "CRUD endpoints for Tool model.",
    },
    {
        "name": "CRUD - TextData",
        "description": "CRUD endpoints for TextData model.",
    },
    {
        "name": "CRUD - ImageData",
        "description": "CRUD endpoints for ImageData model.",
    },
    {
        "name": "CRUD - AudioData",
        "description": "CRUD endpoints for AudioData model.",
    },
    {
        "name": "CRUD - VideoData",
        "description": "CRUD endpoints for VideoData model.",
    },
]

description: str = """
    .
"""

# Session management
user_sessions: dict[str, str] = {}
session_users: dict[str, str] = {}
track_ids: dict[str, str] = {}

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
    """Azure-recommended health check endpoint with detailed metrics"""
    logger.info("Health check endpoint called from %s", request.client.host)
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
    # pick your command based on language or other context
    command = TranslateCommand(websocket)
    invoker = Invoker(command, create_response=True)

    logger.info("Client connected to WebSocket")
    async with invoker as cmd:
        receive_task = asyncio.create_task(invoker._handle_realtime_messages(client_ws))
        await invoker._from_acs_to_realtime(client_ws)
        receive_task.cancel()


@app.post("/incoming-call")
async def incoming_call_handler(request: Request):

    data = await request.json()
    async for event_dict in data:
        event = EventGridEvent.from_dict(event_dict)
        match event.event_type:
            case SystemEventNames.EventGridSubscriptionValidationEventName:
                logger.info("Validating subscription")
                validation_code = event.data["validationCode"]
                validation_response = {"validationResponse": validation_code}
                return SuccessMessage(title="", message="", content=validation_response)
            case SystemEventNames.AcsIncomingCallEventName:
                logger.debug("Incoming call received: data=%s", event.data)
                caller_id = (
                    event.data["from"]["phoneNumber"]["value"]
                    if event.data["from"]["kind"] == "phoneNumber"
                    else event.data["from"]["rawId"]
                )
                logger.info("incoming call handler caller id: %s", caller_id)
                incoming_call_context = event.data["incomingCallContext"]
                guid = uuid.uuid4()
                query_parameters = urlencode({"callerId": caller_id})
                callback_uri = f"{CALLBACK_EVENTS_URI}/{guid}?{query_parameters}"

                parsed_url = urlparse(CALLBACK_EVENTS_URI)
                websocket_url = urlunparse(("wss", parsed_url.netloc, "/ws", "", "", ""))

                logger.debug("callback url: %s", callback_uri)
                logger.debug("websocket url: %s", websocket_url)

                answer_call_result = await acs_client.answer_call(
                    incoming_call_context=incoming_call_context,
                    operation_context="incomingCall",
                    callback_url=callback_uri,
                    media_streaming=MediaStreamingOptions(
                        transport_url=websocket_url,
                        transport_type=MediaStreamingTransportType.WEBSOCKET,
                        content_type=MediaStreamingContentType.AUDIO,
                        audio_channel_type=MediaStreamingAudioChannelType.MIXED,
                        start_media_streaming=True,
                        enable_bidirectional=True,
                        audio_format=AudioFormat.PCM24_K_MONO,
                    ),
                )
                logger.info(f"Answered call for connection id: {answer_call_result.call_connection_id}")
            case _:
                logger.debug("Event type not handled: %s", event.event_type)
                logger.debug("Event data: %s", event.data)
        return SuccessMessage(
            title="Incoming call handler",
            message="Incoming call event processed successfully"
        )
    return SuccessMessage(
        title="Incoming call handler",
        message="Incoming call event processed successfully"
    )


@app.post("/api/callbacks/<contextId>")
async def callbacks(request: Request):
    data = await request.json()
    for event in data:
        # Parsing callback events
        global call_connection_id
        event_data = event["data"]
        call_connection_id = event_data["callConnectionId"]
        logger.debug(
            f"Received Event:-> {event['type']}, Correlation Id:-> {event_data['correlationId']}, CallConnectionId:-> {call_connection_id}"  # noqa: E501
        )
        match event["type"]:
            case "Microsoft.Communication.CallConnected":
                call_connection_properties = await acs_client.get_call_connection(
                    call_connection_id
                ).get_call_properties()
                media_streaming_subscription = call_connection_properties.media_streaming_subscription
                logger.info(f"MediaStreamingSubscription:--> {media_streaming_subscription}")
                logger.info(f"Received CallConnected event for connection id: {call_connection_id}")
                logger.debug("CORRELATION ID:--> %s", event_data["correlationId"])
                logger.debug("CALL CONNECTION ID:--> %s", event_data["callConnectionId"])
            case "Microsoft.Communication.MediaStreamingStarted" | "Microsoft.Communication.MediaStreamingStopped":
                logger.debug(
                    f"Media streaming content type:--> {event_data['mediaStreamingUpdate']['contentType']}"
                )
                logger.debug(
                    f"Media streaming status:--> {event_data['mediaStreamingUpdate']['mediaStreamingStatus']}"
                )
                logger.debug(
                    f"Media streaming status details:--> {event_data['mediaStreamingUpdate']['mediaStreamingStatusDetails']}"  # noqa: E501
                )
            case "Microsoft.Communication.MediaStreamingFailed":
                logger.warning(
                    f"Code:->{event_data['resultInformation']['code']}, Subcode:-> {event_data['resultInformation']['subCode']}"  # noqa: E501
                )
                logger.warning(f"Message:->{event_data['resultInformation']['message']}")
            case "Microsoft.Communication.CallDisconnected":
                logger.debug(f"Call disconnected for connection id: {call_connection_id}")
    return SuccessMessage(
        title="Incoming call handler",
        message="Incoming call event processed successfully"
    )


mcp.mount()
