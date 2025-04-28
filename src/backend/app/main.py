# app/main.py
import os
import sys
import time
import asyncio
import logging

import json
from logging.handlers import RotatingFileHandler
import psutil

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status, Depends, HTTPException, Body
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from starlette.middleware.cors import CORSMiddleware

from app.auth import create_token, validate_token, AuthError
from app.router import ChatMediator
from app.processor import AzureOpenAIClient, SpeechProcessor
from app.user import User, UserCreate, UserLogin, TokenResponse, UserResponse, user_db


# Configure logging
def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_format)
    
    # File handler
    file_handler = RotatingFileHandler(
        "app.log", maxBytes=10*1024*1024, backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(file_format)
    
    # Add handlers
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger

# Initialize logging
logger = setup_logging()

async def buffer_cleanup_task():
    """Background task to periodically clean up old audio buffers and ping connections"""
    while True:
        try:
            await chat_mediator.cleanup_old_buffers()
            
            # Ping all video connections to keep them alive
            for room_id, users in chat_mediator.video_sessions.items():
                for user_id, ws in users.items():
                    try:
                        if ws.client_state.name == "CONNECTED":
                            await ws.send_json({"type": "ping", "timestamp": time.time()})
                    except Exception as e:
                        logger.error(f"Error pinging video connection for {user_id}: {e}")
                        
        except Exception as e:
            logger.error(f"Error in buffer cleanup task: {e}")
        
        # Run every 5 seconds
        await asyncio.sleep(5)

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add this to the app startup event handler
@app.on_event("startup")
async def startup_event():
    """Start background tasks on application startup"""
    # Start the buffer cleanup task
    asyncio.create_task(buffer_cleanup_task())
    logger.info("Started audio buffer cleanup background task")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Initialize chat mediator
chat_mediator = ChatMediator()

# Initialize Azure OpenAI client
openai_client = AzureOpenAIClient()

# Initialize speech processor
speech_processor = SpeechProcessor()

def log_memory_usage():
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()
    logger.info(f"Memory usage: {memory_info.rss / 1024 / 1024:.2f} MB")

    
async def connection_monitor(ws: WebSocket, user_id: str, room_id: str, last_data_time: asyncio.Event):
    ping_interval = 45  # seconds - increased from 30 for better stability
    ping_timeout = 15   # seconds
    while True:
        try:
            # Wait for inactivity
            try:
                await asyncio.wait_for(last_data_time.wait(), timeout=ping_interval)
                # Data received, reset the event
                last_data_time.clear()
                logger.debug(f"Activity detected for {user_id} in room {room_id}")
            except asyncio.TimeoutError:
                # No data received in ping_interval, send ping
                logger.debug(f"No data received from {user_id} in {ping_interval}s, sending ping")
                ping_payload = {"type": "ping", "timestamp": time.time()}
                await ws.send_json(ping_payload)
                
                # Wait for pong response
                try:
                    await asyncio.wait_for(last_data_time.wait(), timeout=ping_timeout)
                    last_data_time.clear()
                    logger.debug(f"Received activity from {user_id} after ping")
                except asyncio.TimeoutError:
                    # No pong received, connection may be dead
                    logger.warning(f"No response to ping from {user_id} after {ping_timeout}s, closing connection")
                    return  # Exit monitor, which will trigger connection cleanup
        except asyncio.CancelledError:
            logger.info(f"Connection monitor for {user_id} cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in connection monitor for {user_id}: {e}")
            return  # Exit on any error



@app.post("/signup", response_model=TokenResponse)
async def signup(user_data: UserCreate):
    """Register a new user and return an access token"""
    # Check if username already exists
    if user_db.user_exists(user_data.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
        
    # Check if email already exists
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
            # Create a demo user on the fly
            demo_user = User(username="demo_user", email="demo@example.com")
            return UserResponse(**demo_user.to_dict())
            
        return UserResponse(**user.to_dict())  #type: ignore
    except AuthError as e:
        raise HTTPException(
            status_code=e.code,
            detail=e.message
        )

# Demo token endpoint for testing
@app.get("/demo-token", response_model=TokenResponse)
async def get_demo_token():
    """Get a demo token for testing"""
    from app.auth import generate_demo_token
    token = generate_demo_token()
    return TokenResponse(access_token=token)


@app.websocket("/ws/voice/{room_id}")
async def ws_voice(ws: WebSocket, room_id: str):
    """
    WebSocket endpoint for voice processing with optional audio-only mode
    that skips transcription and text translation operations
    """
    # Track connection variables for cleanup
    user_id = None
    monitor_task = None
    processor = None
    
    try:
        # --- Connection setup and authentication ---
        token = ws.query_params.get("token")
        if not token:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing authentication")
            return
            
        # Validate token
        try:
            user_id = validate_token(token)
        except Exception as e:
            logger.error(f"Token validation error: {e}")
            await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid authentication")
            return
            
        # Extract parameters from query params
        target_language = ws.query_params.get("target_lang", "en")
        audio_only_param = ws.query_params.get("audio_only", None)
        audio_only = audio_only_param.lower() in ["false", "1"] if audio_only_param else True

        # Accept the connection
        await ws.accept()
        logger.info(f"Voice WebSocket connected: user={user_id}, room={room_id}, language={target_language}, audio_only={audio_only}")
        
        # Create dedicated speech processor for this connection
        processor = SpeechProcessor(target_language=target_language, audio_only=audio_only)
        
        # Create activity tracking event
        last_data_time = asyncio.Event()
        
        # Start connection monitor
        monitor_task = asyncio.create_task(
            connection_monitor(ws, user_id, room_id, last_data_time)
        )
        
        # Add to mediator
        await chat_mediator.add_voice_connection(room_id, user_id, ws)
        
        # --- Main receive loop ---
        while True:
            try:
                # Verify connection state
                if ws.client_state.name != "CONNECTED":
                    logger.warning(f"WebSocket for {user_id} is in state {ws.client_state.name}, closing")
                    break
                    
                # Receive message with timeout
                message = await asyncio.wait_for(ws.receive(), timeout=30.0)
                last_data_time.set()  # Signal activity
                
                # Process binary audio data
                if "bytes" in message:
                    audio_data = message["bytes"]
                    logger.debug(f"Received {len(audio_data)} bytes of audio from {user_id}")
                    
                    # Process through the router
                    asyncio.create_task(
                        chat_mediator.process_audio_stream(
                            room_id, 
                            user_id, 
                            audio_data,
                            processor
                        )
                    )
                
                # Process text control messages
                elif "text" in message:
                    try:
                        json_data = json.loads(message["text"])
                        message_type = json_data.get("type", "unknown")
                        
                        if message_type == "pong":
                            logger.debug(f"Received pong from {user_id}")
                            
                        elif message_type == "config":
                            # Handle language and mode change
                            new_language = json_data.get("target_language")
                            audio_only_param = json_data.get("audio_only")
                            
                            should_update = False
                            
                            if new_language and new_language != target_language:
                                target_language = new_language
                                should_update = True
                            
                            if audio_only_param is not None:
                                audio_only = audio_only_param
                                should_update = True
                            
                            if should_update:
                                # Create new processor with updated settings
                                processor = SpeechProcessor(
                                    target_language=target_language, 
                                    audio_only=audio_only
                                )
                                
                                logger.info(f"Updated settings for {user_id}: lang={target_language}, audio_only={audio_only}")
                                await ws.send_json({
                                    "type": "config_update",
                                    "status": "success",
                                    "target_language": target_language,
                                    "audio_only": audio_only
                                })
                        else:
                            logger.debug(f"Received text message: {message['text'][:100]}")
                            
                    except json.JSONDecodeError:
                        logger.debug(f"Received non-JSON text from {user_id}")
                    
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected for {user_id}")
                break
            except asyncio.TimeoutError:
                # This is not an error, just check if the connection is still active
                continue
            except Exception as e:
                logger.error(f"Error in voice WebSocket for {user_id}: {e}")
                break
                
    except Exception as e:
        logger.error(f"Unhandled exception in voice websocket: {e}", exc_info=True)
        
    finally:
        # --- Cleanup resources ---
        if user_id:
            await chat_mediator.remove_connection(room_id, user_id)
            
        if monitor_task and not monitor_task.done():
            monitor_task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(monitor_task, return_exceptions=True),
                    timeout=2.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for monitor task cleanup for {user_id}")
                
        try:
            await ws.close()
        except Exception as e:
            logger.debug(f"Error during WebSocket closure: {e}")
        
        log_memory_usage()


@app.websocket("/ws/video/{room_id}")
async def ws_video(ws: WebSocket, room_id: str):
    """
    WebSocket endpoint for video - routes video data between clients
    without processing (following the requirements)
    """
    # Track connection variables for cleanup
    user_id = None
    monitor_task = None
    
    try:
        # --- Connection setup and authentication ---
        token = ws.query_params.get("token")
        if not token:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing authentication")
            return
            
        # Validate token
        try:
            user_id = validate_token(token)
        except Exception as e:
            logger.error(f"Token validation error: {e}")
            await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid authentication")
            return
            
        # Accept connection
        await ws.accept()
        logger.info(f"Video WebSocket connected: user={user_id}, room={room_id}")
        
        # Activity tracking
        last_data_time = asyncio.Event()
        
        # Start connection monitor
        monitor_task = asyncio.create_task(
            connection_monitor(ws, user_id, room_id, last_data_time)
        )
        
        # Add to mediator
        await chat_mediator.add_video_connection(room_id, user_id, ws)
        
        # --- Main receive loop ---
        while True:
            try:
                # Check connection state
                if ws.client_state.name != "CONNECTED":
                    logger.warning(f"WebSocket for {user_id} is in state {ws.client_state.name}, closing")
                    break
                    
                # Receive with timeout (Azure best practice)
                message = await asyncio.wait_for(ws.receive(), timeout=30.0)
                last_data_time.set()  # Signal activity
                
                # Process binary data (video frames)
                if "bytes" in message:
                    video_data = message["bytes"]
                    
                    # Log receipt of data with tracking info (for observability)
                    frame_size = len(video_data)
                    logger.debug(f"Received video frame: {frame_size} bytes from {user_id}")
                    
                    # Simply route video to other participants without processing
                    asyncio.create_task(
                        chat_mediator.route_video(room_id, user_id, video_data)
                    )
                    
                # Process text messages (pongs, control messages)
                elif "text" in message:
                    try:
                        json_data = json.loads(message["text"])
                        message_type = json_data.get("type", "unknown")
                        
                        if message_type == "pong":
                            logger.debug(f"Received pong from {user_id}")
                        else:
                            logger.debug(f"Received text message type: {message_type}")
                    except json.JSONDecodeError:
                        pass
                        
            except WebSocketDisconnect:
                logger.info(f"Video WebSocket disconnected for {user_id}")
                break
            except asyncio.TimeoutError:
                # Not an error, just check connection
                continue
            except Exception as e:
                logger.error(f"Error in video WebSocket for {user_id}: {e}")
                break
                
    except Exception as e:
        logger.error(f"Unhandled exception in video websocket: {e}", exc_info=True)
        
    finally:
        # --- Cleanup resources following Azure best practices ---
        
        # Remove from mediator
        if user_id:
            await chat_mediator.remove_connection(room_id, user_id)
            
        # Cancel monitor task
        if monitor_task and not monitor_task.done():
            monitor_task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(monitor_task, return_exceptions=True),
                    timeout=2.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for monitor task cleanup for {user_id}")
                
        # Close WebSocket gracefully
        try:
            await ws.close()
        except Exception:
            pass
            
        # Log metrics
        log_memory_usage()


# Health check endpoint
@app.get("/health")
async def health_check():
    log_memory_usage()
    return {"status": "ok", "timestamp": time.time()}
