# app/main.py
import os
import time
import asyncio
import logging
import sys
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

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    
    # In a real app, hash the password!
    # from passlib.context import CryptContext
    # pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    # hashed_password = pwd_context.hash(user_data.password)
    
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
    # Connection acceptance and setup
    try:
        token = ws.query_params.get("token")
        if not token:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing authentication")
            return
            
        # Validate token and get user_id
        try:
            user_id = validate_token(token)
        except Exception as e:
            logger.error(f"Token validation error: {e}")
            await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid authentication")
            return
            
        await ws.accept()
        logger.info(f"Voice WebSocket connection established for user {user_id} in room {room_id}")
        
        # Set up queues with backpressure
        q_tx: asyncio.Queue[bytes] = asyncio.Queue(maxsize=50)  # Limit queue size
        q_audio: asyncio.Queue[bytes] = asyncio.Queue(maxsize=50)
        
        # Create event for tracking last data receipt
        last_data_time = asyncio.Event()
        
        # Start monitor task
        monitor_task = asyncio.create_task(
            connection_monitor(ws, user_id, room_id, last_data_time)
        )
        
        # Add to session
        await chat_mediator.add_voice_connection(room_id, user_id, ws)
        
        # Define transcription task with proper error handling
        async def run_transcribe():
            try:
                logger.info(f"Starting transcription task for {user_id}")
                async for transcript in speech_processor.transcribe_audio_stream(q_tx):
                    # Process transcript
                    if transcript and transcript.strip():
                        # Send to chat mediator
                        await chat_mediator.add_transcript(room_id, user_id, transcript)
                        
                        # Send to translation if needed
                        if q_audio.qsize() < q_audio.maxsize:
                            await q_audio.put(transcript.encode('utf-8'))
                        else:
                            logger.warning(f"Translation queue full for {user_id}, dropping transcript")
            except asyncio.CancelledError:
                logger.info(f"Transcription task cancelled for {user_id}")
                raise
            except Exception as e:
                logger.error(f"Error in transcription task for {user_id}: {e}", exc_info=True)
                # Signal that a critical task has failed
                monitor_task.cancel()
                raise
                
        # Define translation task
        async def run_audio_translate():
            try:
                logger.info(f"Starting translation task for {user_id}")
                while True:
                    # Get transcript
                    transcript = await q_audio.get()
                    transcript_text = transcript.decode('utf-8')
                    
                    # Process translation
                    try:
                        translation = await openai_client.translate_text(
                            transcript_text, 
                            source_language="en",  # Determine dynamically in real app
                            target_language="es"   # Determine dynamically in real app
                        )
                        
                        # Send translated text back to client
                        if translation:
                            await chat_mediator.add_translation(
                                room_id, user_id, transcript_text, translation
                            )
                    except Exception as e:
                        logger.error(f"Translation error for {user_id}: {e}")
                        
                    # Mark task as done
                    q_audio.task_done()
            except asyncio.CancelledError:
                logger.info(f"Translation task cancelled for {user_id}")
                raise
            except Exception as e:
                logger.error(f"Error in translation task for {user_id}: {e}", exc_info=True)
                monitor_task.cancel()
                raise
        
        # Create tasks with error handling
        tasks = [
            asyncio.create_task(run_transcribe()),
            asyncio.create_task(run_audio_translate()),
            monitor_task
        ]
        
        try:
            # Main receive loop with error handling
            while True:
                try:
                    # First, check if the connection is still open before trying to receive
                    if ws.client_state.name != "CONNECTED":
                        logger.warning(f"WebSocket state for {user_id} is {ws.client_state.name}, exiting receive loop")
                        break
                        
                    # Use a timeout for receiving to prevent blocking indefinitely
                    message = await asyncio.wait_for(ws.receive(), timeout=10.0)
                    
                    # Handle different message types
                    if "bytes" in message:
                        data = message["bytes"]
                        last_data_time.set()  # Signal activity
                        logger.debug(f"Received {len(data)} bytes from {user_id}")
                        
                        # Process or queue data
                        try:
                            # Use non-blocking put with timeout to implement backpressure
                            await asyncio.wait_for(q_tx.put(data), timeout=1.0)
                        except asyncio.TimeoutError:
                            logger.warning(f"Queue full for {user_id}, dropping data")
                            
                    # Handle text messages (including pongs)
                    elif "text" in message:
                        text_data = message["text"]
                        last_data_time.set()  # Signal activity
                        
                        # Process text message...
                        
                except WebSocketDisconnect:
                    logger.info(f"WebSocket disconnected for {user_id} in room {room_id}")
                    break
                except asyncio.TimeoutError:
                    # Timeout on receive is not an error, just check connection state and continue
                    logger.debug(f"Receive timeout for {user_id}, checking connection state")
                    if ws.client_state.name != "CONNECTED":
                        logger.info(f"Connection no longer active for {user_id}, exiting receive loop")
                        break
                    continue
                except Exception as e:
                    logger.error(f"Error receiving data from {user_id}: {e}")
                    break
                    
        finally:
            # Remove from session
            await chat_mediator.remove_connection(room_id, user_id)
            
            # Ensure all tasks are properly cleaned up
            for task in tasks:
                if not task.done():
                    task.cancel()
                    
            # Wait for tasks to complete with timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for tasks to complete for {user_id}")
                
            logger.info(f"All tasks cleaned up for {user_id}")
            
            # Ensure connection is closed
            try:
                await ws.close()
            except:
                pass
                
            # Log memory usage periodically
            log_memory_usage()
            
    except Exception as e:
        logger.error(f"Unhandled exception in voice websocket handler: {e}", exc_info=True)
        try:
            await ws.close(code=status.WS_1011_INTERNAL_ERROR)
        except:
            pass

@app.websocket("/ws/video/{room_id}")
async def ws_video(ws: WebSocket, room_id: str):
    # Similar structure to voice endpoint but for video
    # With the same error handling and connection management improvements
    try:
        token = ws.query_params.get("token")
        if not token:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing authentication")
            return
            
        # Validate token and get user_id
        try:
            user_id = validate_token(token)
        except Exception as e:
            logger.error(f"Token validation error: {e}")
            await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid authentication")
            return
            
        await ws.accept()
        logger.info(f"Video WebSocket connection established for user {user_id} in room {room_id}")
        
        # Add to mediator
        await chat_mediator.add_video_connection(room_id, user_id, ws)
        
        # Set up data tracking
        last_data_time = asyncio.Event()
        
        # Start monitor task
        monitor_task = asyncio.create_task(
            connection_monitor(ws, user_id, room_id, last_data_time)
        )
        
        try:
            # Main receive loop
            while True:
                try:
                    message = await ws.receive()
                    last_data_time.set()  # Signal activity
                    
                    if "bytes" in message:
                        data = message["bytes"]
                        logger.debug(f"Received {len(data)} bytes of video from {user_id}")
                        
                        # Broadcast video data to other clients
                        await chat_mediator.broadcast_video(room_id, user_id, data)
                        
                except WebSocketDisconnect:
                    logger.info(f"Video WebSocket disconnected for user {user_id} in room {room_id}")
                    break
                except Exception as e:
                    logger.error(f"Error in video websocket for {user_id}: {e}")
                    break
                    
        finally:
            # Clean up
            await chat_mediator.remove_connection(room_id, user_id)
            
            if not monitor_task.done():
                monitor_task.cancel()
                
            try:
                await asyncio.wait_for(
                    asyncio.gather(monitor_task, return_exceptions=True),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for monitor task to complete for {user_id}")
                
            try:
                await ws.close()
            except:
                pass
                
    except Exception as e:
        logger.error(f"Unhandled exception in video websocket handler: {e}", exc_info=True)
        try:
            await ws.close(code=status.WS_1011_INTERNAL_ERROR)
        except:
            pass

@app.websocket("/ws/chat/{room_id}")
async def ws_chat(ws: WebSocket, room_id: str):
    # Text chat websocket endpoint
    # With the same error handling and connection management improvements
    try:
        token = ws.query_params.get("token")
        if not token:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing authentication")
            return
            
        # Validate token and get user_id
        try:
            user_id = validate_token(token)
        except Exception as e:
            logger.error(f"Token validation error: {e}")
            await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid authentication")
            return
            
        await ws.accept()
        logger.info(f"Chat WebSocket connection established for user {user_id} in room {room_id}")
        
        # Add to mediator
        await chat_mediator.add_chat_connection(room_id, user_id, ws)
        
        # Set up data tracking
        last_data_time = asyncio.Event()
        
        # Start monitor task
        monitor_task = asyncio.create_task(
            connection_monitor(ws, user_id, room_id, last_data_time)
        )
        
        try:
            # Main receive loop
            while True:
                try:
                    message = await ws.receive_json()
                    last_data_time.set()  # Signal activity
                    
                    # Process chat message
                    message_type = message.get("type", "unknown")
                    
                    if message_type == "chat":
                        text = message.get("text", "")
                        if text:
                            # Add message to chat history
                            await chat_mediator.add_chat_message(room_id, user_id, text)
                            
                            # Translate if needed
                            if message.get("translate", False):
                                try:
                                    translation = await openai_client.translate_text(
                                        text,
                                        source_language=message.get("source_lang", "auto"),
                                        target_language=message.get("target_lang", "en")
                                    )
                                    
                                    # Send translation back
                                    if translation:
                                        await chat_mediator.add_translation(
                                            room_id, user_id, text, translation
                                        )
                                except Exception as e:
                                    logger.error(f"Translation error for chat: {e}")
                                    await ws.send_json({
                                        "type": "error",
                                        "message": "Translation failed"
                                    })
                    elif message_type == "pong":
                        logger.debug(f"Received pong from {user_id}")
                    else:
                        logger.warning(f"Unknown message type from {user_id}: {message_type}")
                        
                except WebSocketDisconnect:
                    logger.info(f"Chat WebSocket disconnected for user {user_id} in room {room_id}")
                    break
                except Exception as e:
                    logger.error(f"Error in chat websocket for {user_id}: {e}")
                    break
                    
        finally:
            # Clean up
            await chat_mediator.remove_connection(room_id, user_id)
            
            if not monitor_task.done():
                monitor_task.cancel()
                
            try:
                await asyncio.wait_for(
                    asyncio.gather(monitor_task, return_exceptions=True),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for monitor task to complete for {user_id}")
                
            try:
                await ws.close()
            except:
                pass
                
    except Exception as e:
        logger.error(f"Unhandled exception in chat websocket handler: {e}", exc_info=True)
        try:
            await ws.close(code=status.WS_1011_INTERNAL_ERROR)
        except:
            pass

# Health check endpoint
@app.get("/health")
async def health_check():
    log_memory_usage()
    return {"status": "ok", "timestamp": time.time()}
