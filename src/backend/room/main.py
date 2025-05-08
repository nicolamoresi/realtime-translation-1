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
import asyncio
import uuid
import psutil
from base64 import b64decode

from starlette.middleware.cors import CORSMiddleware
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status, Depends, HTTPException, Header
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import JSONResponse
from fastapi_mcp import FastApiMCP


from room import __app__, __author__, __version__, logger
from orchestrator.auth import create_token, validate_token, AuthError
from orchestrator.background import lifespan
from orchestrator.client import RealtimeClient, setup_realtime_client, cleanup_session, get_client_or_404


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
sessions: dict[str, RealtimeClient] = {}  # session_id -> RealtimeClient
user_sessions: dict[str, str]       = {}  # user_id -> session_id
session_users: dict[str, str]       = {}  # session_id -> user_id
track_ids: dict[str, str]           = {}  # session_id -> current audio track


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


# User authentication endpoints
@app.post("/signup", response_model=TokenResponse)
async def signup(user_data: UserCreate):
    """Register a new user and return an access token"""
    if user_db.user_exists(user_data.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )

    if user_db.email_exists(user_data.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # For demo purposes, we'll store the password directly (don't do this in production!)
    new_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=user_data.password  # Should be hashed in production
    )
    
    # Add user to database
    user_db.add_user(new_user)

    # Create access token
    token = create_token(new_user.username)
    
    logger.info(f"User registered: {new_user.username}")
    return TokenResponse(access_token=token)


@app.post("/token", response_model=TokenResponse)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """OAuth2-compatible token login, get an access token for future requests"""
    user = user_db.get_user(form_data.username)
    
    if not user or user.hashed_password != form_data.password:  # Should use proper password verification in production
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Update last active timestamp
    user.update_activity()
    
    # Create access token
    token = create_token(user.username)
    
    logger.info(f"User logged in via oauth2: {user.username}")
    return TokenResponse(access_token=token)


@app.post("/signin", response_model=TokenResponse)
async def signin(user_data: UserLogin):
    """Sign in and get an access token"""
    user = user_db.get_user(user_data.username)
    
    if not user or user.hashed_password != user_data.password:  # Should use proper password verification in production
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    # Update last active timestamp
    user.update_activity()
    
    # Create access token
    token = create_token(user.username)
    
    logger.info(f"User signed in: {user.username}")
    return TokenResponse(access_token=token)


@app.get("/me", response_model=UserResponse)
async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Get current user profile"""
    try:
        username = validate_token(token)
        user = user_db.get_user(username)
        
        if not user and username != "demo_user":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        if username == "demo_user":
            demo_user = User(username="demo_user", email="demo@example.com")
            return UserResponse(**demo_user.to_dict())

        return UserResponse(**user.to_dict())  #type: ignore
    except AuthError as e:
        raise HTTPException(
            status_code=e.code,
            detail=e.message
        )


@app.get("/anonymous-access/{room_id}", response_model=TokenResponse)
async def get_anonymous_access(room_id: str):
    """Generate an anonymous user token for a specific room"""
    # Count existing anonymous users
    anonymous_count = 0
    for user_id in user_sessions.keys():
        if user_id.startswith("anonymous-"):
            try:
                # Extract number from anonymous-X format
                num = int(user_id.split("-")[1].split("_")[0])
                anonymous_count = max(anonymous_count, num)
            except (ValueError, IndexError):
                pass
    
    # Generate new anonymous username
    anonymous_username = f"anonymous-{anonymous_count + 1}"
    
    # Create an access token for this anonymous user
    token = create_token(anonymous_username)
    
    logger.info(f"Created anonymous access for {anonymous_username} in room {room_id}")
    return TokenResponse(access_token=token)


@app.get("/demo-token", response_model=TokenResponse)
async def get_demo_token():
    """Get a demo token for testing"""
    from orchestrator.auth import generate_demo_token
    token = generate_demo_token()
    return TokenResponse(access_token=token)


# New session management endpoints
@app.post("/chat/start")
async def start_chat(token: str = Depends(oauth2_scheme)):
    """
    Start a new chat session and return a session ID.
    
    Returns:
        A JSON response with session_id and welcome message
    """
    try:
        # Validate user token
        username = validate_token(token)
        user_id = generate_user_id(username)
        
        # Check if user already has an active session
        if user_id in user_sessions:
            old_session_id = user_sessions[user_id]
            # Clean up old session
            await cleanup_session(old_session_id)
            logger.info(f"Cleaned up previous session for user {user_id}")
        
        # Create new session
        session_id = str(uuid.uuid4())
        
        # Define system prompt
        system_prompt = """
        You are an interpreter who can help people who speak different languages interact with chinese-speaking people.
        Your sole function is to translate the input from the user accurately and with proper grammar, maintaining the original meaning and tone of the message.

        Whenever the user speaks in English, you will translate it to Portuguese.
        Whenever the user speaks in Portuguese, you will translate it to English.

        Act like an interpreter, DO NOT add, omit, or alter any information.
        DO NOT provide explanations, opinions, or any additional text beyond the direct translation.
        DO NOT respond to the speakers' questions or asks and DO NOT add your own thoughts. You only need to translate the audio input coming from the two speakers.
        You are not aware of any other facts, knowledge, or context beyond the audio input you are translating.
        Wait until the speaker is done speaking before you start translating, and translate the entire audio inputs in one go. If the speaker is providing a series of instructions, wait until the end of the instructions before translating.

        # Steps

        1. **Receive Audio Input**: Process the provided audio input.
        2. **Transcribe the Audio**: Accurately transcribe the spoken content into text in English.
        3. **Translate**: Convert the transcribed text to the other language, ensuring clarity, correctness, and cultural appropriateness.
        4. **Maintain Original Meaning**: Preserve the original intent, context, and tone of the message.
        5. **Check Grammar and Style**: Ensure the translated text adheres to proper grammar, spelling, and sentence structure suitable for the other language.

        # Output Format

        Provide the output as plain text in the same language spoken by the respective speaker. 
        Ensure that it is organized and easy to read, but avoid adding extra formatting unless necessary for context.

        # Notes

        - If the original audio includes idioms, cultural references, or expressions, adapt them into their closest equivalents where possible while retaining the intended meaning.
        - Handle technical terms with their closest translation or state them as-is if no appropriate equivalent exists.
        - In cases of unclear audio, provide the best-guess translation and indicate uncertainty with a note (e.g., "[unclear: possible interpretation]"). 
        - Do not include extraneous details or analysis not present in the user's input.
        - ONLY RESPOND WITH THE TRANSLATED TEXT. DO NOT ADD ANY OTHER TEXT, EXPLANATIONS, OR CONTEXTUAL INFORMATION.
        """
        
        # Set up realtime client
        await setup_realtime_client(session_id, user_id, system_prompt)
        
        logger.info(f"Created new session {session_id} for user {user_id}")
        
        return JSONResponse({
            "session_id": session_id,
            "message": "Welcome to the real-time translation service. Press the microphone button to start speaking."
        })
    except AuthError as e:
        raise HTTPException(
            status_code=e.code,
            detail=e.message
        )
    except Exception as e:
        logger.error(f"Error starting chat: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start chat session"
        )


@app.post("/chat/message")
async def send_message(
    payload: ChatPayload = Depends(ChatPayload.validate_payload),
    x_session_id: str = Header(..., alias="X-Session-ID"),
):
    """
    Process user input and return the assistant's response with text and audio.
    
    Instead of just enqueuing the message, this endpoint waits for the model response
    and returns the complete answer including text transcript and audio data.
    """
    try:
        client = get_client_or_404(x_session_id)

        if not client.is_connected():
            await client.connect()

        if not payload.audio:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Audio data is required",
            )
        try:
            # Decode base64 audio
            raw_audio = b64decode(payload.audio, validate=True)
            
            # Audio conversion is already handled by client.append_input_audio
            await client.append_input_audio(raw_audio)
            logger.info(f"Session {x_session_id} sent audio ({len(raw_audio)} bytes)")
            
        except Exception as e:
            logger.error(f"Audio processing error: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid audio data",
            ) from e
        
        # After sending the input, create a response
        await client.create_response()
        
        # Wait for the model to process and respond (with timeout)
        try:
            # Wait for the completed item with the assistant's response
            response_data = await asyncio.wait_for(
                client.wait_for_next_completed_item(), 
                timeout=10.0  # Azure best practice: set reasonable timeout
            )
            
            # Extract response data from the completed item
            item = response_data.get("item", {})
            
            # Get the text transcript
            reply_text = item.get("formatted", {}).get("transcript", "")
            
            # Get the audio data if available
            reply_audio = None
            if audio_content := next((c for c in item.get("content", []) if c.get("type") == "audio"), None):
                if audio_data := audio_content.get("data"):
                    # Convert to base64 for sending to frontend
                    from base64 import b64encode
                    reply_audio = b64encode(bytes(audio_data)).decode("utf-8")
            
            # Update last activity
            setattr(client, "last_activity", time.time())
            
            # Log the successful exchange
            logger.info(f"Session {x_session_id} received assistant reply: {reply_text[:50]}...")

            if not client.is_connected():
                await client.disconnect()
            
            # Return both text and audio to the frontend
            return {
                "status": "success",
                "reply": reply_text,
                "audio_base64": reply_audio
            }
            
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for response in session {x_session_id}")
            return {
                "status": "timeout",
                "echo": payload.content,
                "message": "Request is still processing. Try again with a shorter input."
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in /chat/message: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process message",
        )


@app.post("/chat/stop")
async def stop_chat(x_session_id: str = Header(..., alias="X-Session-ID")):
    """
    Stop a chat session and clean up resources.
    
    Args:
        x_session_id: Session ID header
        
    Returns:
        Status confirmation
    """
    try:
        # Make sure session exists
        _ = get_client_or_404(x_session_id)
        
        # Clean up the session
        await cleanup_session(x_session_id)
        logger.info(f"Closed session {x_session_id}")
        
        return {"status": "closed"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error stopping chat: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to stop chat session"
        )

# WebSocket endpoint for audio streaming
@app.websocket("/ws/audio")
async def websocket_audio(ws: WebSocket, x_session_id: str = Header(..., alias="X-Session-ID")):
    """
    WebSocket endpoint for streaming audio with control messages.
    
    Protocol:
    - Binary frames = raw PCM16 audio data to be processed
    - Text frame "start" = initiate the Azure OpenAI connection
    - Text frame "end" = terminate the connection gracefully
    
    Args:
        ws: The WebSocket connection
        x_session_id: Session ID header
    """
    try:
        # Validate session before accepting connection
        client = get_client_or_404(x_session_id)
        
        # Accept the connection
        await ws.accept()
        logger.info(f"Audio WebSocket connected for session {x_session_id}")
        
        while True:
            # Receive a message
            frame = await ws.receive()
            
            # Update last activity timestamp
            setattr(client, "last_activity", time.time())
            
            # Process text control messages
            if "text" in frame:
                msg = frame["text"]
                
                # Handle connection initialization
                if msg == "start":
                    try:
                        # Connect to Azure OpenAI
                        await client.connect()
                        logger.info(f"Realtime Azure connection established for session {x_session_id}")
                    except Exception as e:
                        logger.error(f"Failed to connect to Azure: {e}", exc_info=True)
                        await ws.close(code=1011, reason=str(e))
                        return
                
                # Handle graceful termination
                elif msg == "end":
                    await client.disconnect()
                    await ws.close(code=1000)
                    logger.info(f"WebSocket closed gracefully for session {x_session_id}")
                    return
                
                # Reject unsupported messages
                else:
                    logger.warning(f"Unsupported control message: {msg}")
                    await ws.close(code=1003, reason="Unsupported control message")
                    return
            
            # Process binary audio data
            elif "bytes" in frame:
                audio_data = frame["bytes"]
                
                # Only process if connected to Azure
                if client.is_connected():
                    await client.append_input_audio(audio_data)
                    logger.debug(f"Processed {len(audio_data)} bytes of audio for session {x_session_id}")
                else:
                    logger.warning(f"Received audio data before connection started for {x_session_id}")
            
            # Reject other frame types
            else:
                logger.warning(f"Received unsupported frame type")
                await ws.close(code=1003)
                return
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for session {x_session_id}")
    except HTTPException as e:
        logger.error(f"HTTP error in WebSocket: {e.detail}")
        try:
            await ws.close(code=1008, reason=e.detail)
        except:
            pass
    except Exception as e:
        logger.error(f"Error in audio WebSocket: {e}", exc_info=True)
        try:
            await ws.close(code=1011, reason=str(e))
        except:
            pass
    finally:
        # Log memory usage for Azure monitoring
        log_memory_usage()

# Health check endpoint
@app.get("/health")
async def health_check():
    """Azure-recommended health check endpoint with detailed metrics"""
    memory_usage = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    
    active_sessions = len(sessions)
    
    return {
        "status": "ok",
        "timestamp": time.time(),
        "metrics": {
            "memory_mb": round(memory_usage, 2),
            "active_sessions": active_sessions,
            "user_count": len(set(session_users.values()))
        },
        "version": "1.0.0"
    }