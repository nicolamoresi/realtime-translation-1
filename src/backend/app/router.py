# app/router.py
import logging
import asyncio
import time
from typing import Dict, List, Any, Optional
from fastapi import WebSocket

from .processor import SpeechProcessor


# Configure logging
logger = logging.getLogger(__name__)

class ChatMediator:
    """
    Manages WebSocket connections and message distribution for chat rooms
    """
    def __init__(self):
        # Store connections by room and type
        self.voice_sessions: Dict[str, Dict[str, WebSocket]] = {}
        self.video_sessions: Dict[str, Dict[str, WebSocket]] = {}
        self.chat_sessions: Dict[str, Dict[str, WebSocket]] = {}

        # Store message history
        self.chat_history: Dict[str, List[Dict[str, Any]]] = {}
        self.transcript_history: Dict[str, List[Dict[str, Any]]] = {}

        # Lock for thread safety
        self.lock = asyncio.Lock()

        self.audio_buffers: Dict[str, Dict[str, bytes]] = {}  # room_id -> user_id -> buffer
        self.audio_buffer_timestamps: Dict[str, Dict[str, float]] = {}  # For buffer age tracking
        self.min_buffer_size: int = 1024 * 1024  # 1MB minimum buffer size
        self.max_buffer_age: float = 3.0  # Max seconds to hold audio before processing

    async def add_voice_connection(self, room_id: str, user_id: str, connection: WebSocket):
        """Add a voice WebSocket connection to a room"""
        async with self.lock:
            if room_id not in self.voice_sessions:
                self.voice_sessions[room_id] = {}

            # Close existing connection if any
            if user_id in self.voice_sessions[room_id]:
                try:
                    await self.voice_sessions[room_id][user_id].close()
                except Exception as e:
                    logger.error(f"Error closing existing voice connection for {user_id}: {e}")
                    
            self.voice_sessions[room_id][user_id] = connection
            logger.info(f"Added voice connection for {user_id} in room {room_id}")

    async def add_video_connection(self, room_id: str, user_id: str, connection: WebSocket):
        """Add a video WebSocket connection to a room"""
        async with self.lock:
            if room_id not in self.video_sessions:
                self.video_sessions[room_id] = {}
                
            # Close existing connection if any
            if user_id in self.video_sessions[room_id]:
                try:
                    await self.video_sessions[room_id][user_id].close()
                except Exception as e:
                    logger.error(f"Error closing existing video connection for {user_id}: {e}")
                    
            self.video_sessions[room_id][user_id] = connection
            logger.info(f"Added video connection for {user_id} in room {room_id}")
            
    async def add_chat_connection(self, room_id: str, user_id: str, connection: WebSocket):
        """Add a chat WebSocket connection to a room"""
        async with self.lock:
            if room_id not in self.chat_sessions:
                self.chat_sessions[room_id] = {}
                
            # Close existing connection if any
            if user_id in self.chat_sessions[room_id]:
                try:
                    await self.chat_sessions[room_id][user_id].close()
                except Exception as e:
                    logger.error(f"Error closing existing chat connection for {user_id}: {e}")
                    
            self.chat_sessions[room_id][user_id] = connection
            logger.info(f"Added chat connection for {user_id} in room {room_id}")
            
            # Send chat history to new user
            if room_id in self.chat_history:
                try:
                    # Get recent messages (last 50)
                    recent_messages = self.chat_history[room_id][-50:]
                    
                    # Send history
                    await connection.send_json({
                        "type": "chat_history",
                        "messages": recent_messages
                    })
                except Exception as e:
                    logger.error(f"Error sending chat history to {user_id}: {e}")
            
    async def remove_connection(self, room_id: str, user_id: str):
        """Remove a user's connections from a room"""
        async with self.lock:
            removed = False

            # Remove from voice sessions
            if room_id in self.voice_sessions and user_id in self.voice_sessions[room_id]:
                del self.voice_sessions[room_id][user_id]
                if not self.voice_sessions[room_id]:
                    del self.voice_sessions[room_id]
                removed = True

            # Remove from video sessions
            if room_id in self.video_sessions and user_id in self.video_sessions[room_id]:
                del self.video_sessions[room_id][user_id]
                if not self.video_sessions[room_id]:
                    del self.video_sessions[room_id]
                removed = True

            # Remove from chat sessions
            if room_id in self.chat_sessions and user_id in self.chat_sessions[room_id]:
                del self.chat_sessions[room_id][user_id]
                if not self.chat_sessions[room_id]:
                    del self.chat_sessions[room_id]
                removed = True

            if removed:
                logger.info(f"Removed connections for {user_id} from room {room_id}")

                # Broadcast user left message
                await self.broadcast_json(room_id, {
                    "type": "user_left",
                    "user_id": user_id,
                    "timestamp": time.time()
                })
            
    async def broadcast_bytes(
            self, room_id: str, data: bytes,
            target_sessions: Optional[Dict[str, Dict[str, WebSocket]]] = None,
            exclude_user_id: Optional[str] = None
        ) -> None:
        """Broadcast binary data to all connections in a room"""
        if not target_sessions:
            return

        if room_id not in target_sessions:
            logger.debug(f"Attempted to broadcast to non-existent room: {room_id}")
            return

        # Track performance metrics
        sent_count = 0
        total_connections = 0
        start_time = time.time()
            
        # Get a copy of the connections to avoid modification during iteration
        connections = list(target_sessions[room_id].items())
        failed_users = []
        
        for user_id, conn in connections:
            # Skip excluded user if specified
            if exclude_user_id and user_id == exclude_user_id:
                continue
            
            total_connections += 1
                
            try:
                # Verify connection is open before sending
                if hasattr(conn, 'client_state') and conn.client_state.name == "CONNECTED":
                    await conn.send_bytes(data)
                    sent_count += 1
                else:
                    logger.warning(f"Cannot send to {user_id}, WebSocket not in CONNECTED state")
                    failed_users.append(user_id)
            except Exception as e:
                logger.error(f"Failed to broadcast bytes to {user_id} in room {room_id}: {e}")
                failed_users.append(user_id)
        
        # Log success metrics
        if sent_count > 0:
            elapsed = time.time() - start_time
            logger.info(f"Broadcast {len(data)} bytes to {sent_count}/{total_connections} clients in room {room_id} ({elapsed:.3f}s)")
        
        # Handle failed connections separately to avoid modifying while iterating
        if failed_users:
            async with self.lock:
                for user_id in failed_users:
                    logger.info(f"Removing failed connection for {user_id} from room {room_id}")
                    if room_id in target_sessions and user_id in target_sessions[room_id]:
                        del target_sessions[room_id][user_id]
                        
                # Clean up empty rooms
                if room_id in target_sessions and not target_sessions[room_id]:
                    del target_sessions[room_id]
    
    async def broadcast_json(self, room_id: str, message: Dict[str, Any],
                            exclude_user_id: Optional[str] = None) -> None:
        """Broadcast JSON message to all chat connections in a room"""
        if room_id not in self.chat_sessions:
            logger.debug(f"Attempted to broadcast JSON to non-existent room: {room_id}")
            return
            
        # Get a copy of the connections to avoid modification during iteration
        connections = list(self.chat_sessions[room_id].items())
        failed_users = []
        
        for user_id, conn in connections:
            # Skip excluded user if specified
            if exclude_user_id and user_id == exclude_user_id:
                continue
                
            try:
                await conn.send_json(message)
            except Exception as e:
                logger.error(f"Failed to broadcast JSON to {user_id} in room {room_id}: {e}")
                failed_users.append(user_id)
        
        # Handle failed connections separately
        if failed_users:
            async with self.lock:
                for user_id in failed_users:
                    logger.info(f"Removing failed connection for {user_id} from room {room_id}")
                    if room_id in self.chat_sessions and user_id in self.chat_sessions[room_id]:
                        del self.chat_sessions[room_id][user_id]
                        
                # Clean up empty rooms
                if room_id in self.chat_sessions and not self.chat_sessions[room_id]:
                    del self.chat_sessions[room_id]
    
    async def broadcast_video(self, room_id: str, sender_id: str, video_data: bytes) -> None:
        """Broadcast video data to all connections in a room except the sender"""
        await self.broadcast_bytes(
            room_id=room_id,
            data=video_data,
            target_sessions=self.video_sessions,
            exclude_user_id=sender_id
        )
    
    async def add_chat_message(self, room_id: str, user_id: str, message: str) -> None:
        """Add a chat message to the history and broadcast to room"""
        # Create message object
        message_obj = {
            "type": "chat",
            "user_id": user_id,
            "text": message,
            "timestamp": time.time()
        }
        
        # Add to history
        async with self.lock:
            if room_id not in self.chat_history:
                self.chat_history[room_id] = []
                
            self.chat_history[room_id].append(message_obj)
            
            # Limit history size
            if len(self.chat_history[room_id]) > 1000:
                self.chat_history[room_id] = self.chat_history[room_id][-1000:]
                
        # Broadcast to all in room
        await self.broadcast_json(room_id, message_obj)
    
    async def add_transcript(self, room_id: str, user_id: str, transcript: str) -> None:
        """Add a transcript to the history and broadcast to room"""
        # Create transcript object
        transcript_obj = {
            "type": "transcript",
            "user_id": user_id,
            "text": transcript,
            "timestamp": time.time()
        }
        
        # Add to history
        async with self.lock:
            if room_id not in self.transcript_history:
                self.transcript_history[room_id] = []
                
            self.transcript_history[room_id].append(transcript_obj)
            
            # Limit history size
            if len(self.transcript_history[room_id]) > 1000:
                self.transcript_history[room_id] = self.transcript_history[room_id][-1000:]
                
        # Broadcast to all in chat room
        await self.broadcast_json(room_id, transcript_obj)
    
    async def add_translation(self, room_id: str, user_id: str, 
                             original_text: str, translated_text: str) -> None:
        """Add a translation and broadcast to room"""
        # Create translation object
        translation_obj = {
            "type": "translation",
            "user_id": user_id,
            "original": original_text,
            "translated": translated_text,
            "timestamp": time.time()
        }
        
        # Broadcast to all in chat room
        await self.broadcast_json(room_id, translation_obj)
        
    def get_active_rooms(self) -> List[str]:
        """Get a list of active rooms with connections"""
        all_rooms = set()
        
        for sessions in [self.voice_sessions, self.video_sessions, self.chat_sessions]:
            all_rooms.update(sessions.keys())
            
        return list(all_rooms)
        
    def get_room_users(self, room_id: str) -> List[str]:
        """Get a list of users in a room across all connection types"""
        users = set()
        
        if room_id in self.voice_sessions:
            users.update(self.voice_sessions[room_id].keys())
            
        if room_id in self.video_sessions:
            users.update(self.video_sessions[room_id].keys())
            
        if room_id in self.chat_sessions:
            users.update(self.chat_sessions[room_id].keys())
            
        return list(users)
        
    def get_connection_stats(self) -> Dict[str, Any]:
        """Get statistics about active connections"""
        voice_rooms = len(self.voice_sessions)
        voice_connections = sum(len(users) for users in self.voice_sessions.values())
        
        video_rooms = len(self.video_sessions)
        video_connections = sum(len(users) for users in self.video_sessions.values())
        
        chat_rooms = len(self.chat_sessions)
        chat_connections = sum(len(users) for users in self.chat_sessions.values())
        
        return {
            "timestamp": time.time(),
            "voice": {
                "rooms": voice_rooms,
                "connections": voice_connections
            },
            "video": {
                "rooms": video_rooms,
                "connections": video_connections
            },
            "chat": {
                "rooms": chat_rooms,
                "connections": chat_connections
            },
            "total_rooms": len(self.get_active_rooms()),
            "total_connections": voice_connections + video_connections + chat_connections
        }

    # Replace the process_audio_stream method with this implementation

    async def process_audio_stream(
        self, 
        room_id: str, 
        user_id: str, 
        audio_data: bytes,
        processor: 'SpeechProcessor'
    ) -> None:
        """
        Buffer audio data until we have at least 1MB, then process it:
        1. Audio gets translated to the target language and sent back to sender
        2. Audio gets transcribed and translated as text for captions (unless in audio-only mode)
        
        If any model error occurs, the original audio is returned as fallback
        """
        try:
            # Initialize buffer for this user if needed
            buffer_key = f"{room_id}:{user_id}"
            
            async with self.lock:
                # Initialize room in buffer dictionaries if needed
                if room_id not in self.audio_buffers:
                    self.audio_buffers[room_id] = {}
                    self.audio_buffer_timestamps[room_id] = {}
                    
                # Initialize or append to the user's buffer
                if user_id not in self.audio_buffers[room_id]:
                    self.audio_buffers[room_id][user_id] = audio_data
                    self.audio_buffer_timestamps[room_id][user_id] = time.time()
                    logger.debug(f"Created new audio buffer for {user_id} in room {room_id}: {len(audio_data)} bytes")
                else:
                    self.audio_buffers[room_id][user_id] += audio_data
                    buffer_size = len(self.audio_buffers[room_id][user_id])
                    logger.debug(f"Added {len(audio_data)} bytes to buffer for {user_id}, total: {buffer_size} bytes")
                
                # Check if buffer is ready for processing
                current_buffer = self.audio_buffers[room_id][user_id]
                buffer_age = time.time() - self.audio_buffer_timestamps[room_id][user_id]
                
                # Process if buffer is large enough or old enough
                should_process = len(current_buffer) >= self.min_buffer_size or buffer_age >= self.max_buffer_age
                
                if not should_process:
                    # Not enough data yet, wait for more
                    return
                    
                # Get the data and clear the buffer
                buffered_audio = current_buffer
                self.audio_buffers[room_id][user_id] = b''
                self.audio_buffer_timestamps[room_id][user_id] = time.time()
                
            # Log buffer stats before processing
            buffer_size_kb = len(buffered_audio) / 1024
            logger.info(f"Processing audio buffer for {user_id}: {buffer_size_kb:.2f} KB, age: {buffer_age:.2f}s")
            
            # Store original audio for fallback
            original_audio = buffered_audio
            model_error = False
            
            # Start processing time measurement
            start_time = time.time()
            
            # Process the audio data
            process_task = asyncio.create_task(processor.process(buffered_audio))
            
            # Wait for processing to complete with timeout (prevents hanging)
            try:
                result = await asyncio.wait_for(process_task, timeout=120.0)  # Increased timeout for larger buffers
            except asyncio.TimeoutError:
                logger.warning(f"Audio processing timeout for user {user_id} in room {room_id}")
                model_error = True
                logger.error(f"AI_MODEL_TIMEOUT: Processing timeout for audio in room {room_id}")
                result = {"original_text": None, "translated_text": None, "audio": None}
                
            # Check results based on processing mode
            if processor.audio_only:
                # In audio-only mode, only check for audio result
                if not result.get("audio"):
                    model_error = True
                    logger.warning(f"AI_MODEL_ERROR: Audio translation failed for {user_id}")
                    logger.warning(f"AI_MODEL_ERROR: {result}")
            else:
                # In full mode, check if we got error responses or empty responses
                if not result.get("audio") or not result.get("original_text"):
                    logger.error(f"AI_MODEL_ERROR: {result}")
                    model_error = True
                    logger.warning(f"AI_MODEL_ERROR: Partial or complete failure processing audio for {user_id}")
                    
            # Measure processing time
            processing_time = time.time() - start_time
            logger.debug(f"Audio processed in {processing_time:.3f}s for user {user_id}")
            
            # Get the user's voice connection first (for any response)
            voice_ws = None
            if room_id in self.voice_sessions and user_id in self.voice_sessions[room_id]:
                voice_ws = self.voice_sessions[room_id][user_id]
            
            # Handle model error - return original audio as fallback
            if model_error and voice_ws:
                try:
                    logger.info(f"FALLBACK: Returning original audio for {user_id} due to model error")
                    await voice_ws.send_bytes(original_audio)
                    
                    # Also send a notification about the error (if not in audio-only mode)
                    if not processor.audio_only and room_id in self.chat_sessions and user_id in self.chat_sessions[room_id]:
                        chat_ws = self.chat_sessions[room_id][user_id]
                        await chat_ws.send_json({
                            "type": "system_message",
                            "message": "Translation service temporarily unavailable. Using original audio instead.",
                            "timestamp": time.time()
                        })
                    return
                except Exception as e:
                    logger.error(f"Error sending fallback audio to {user_id}: {e}")
            
            # If no model error, proceed with normal flow
            
            # Handle audio translation result
            translated_audio = result.get("audio")
            if translated_audio and voice_ws:
                # Send the translated audio back to the speaker
                try:
                    await voice_ws.send_bytes(translated_audio)
                    logger.debug(f"Sent translated audio ({len(translated_audio)} bytes) back to {user_id}")
                except Exception as e:
                    logger.error(f"Error sending translated audio to {user_id}: {e}")
                    # Try fallback if translation sending fails
                    try:
                        await voice_ws.send_bytes(original_audio)
                        logger.info(f"FALLBACK: Sent original audio after translation send failure")
                    except:
                        pass
            
            # Skip text processing if in audio-only mode
            if processor.audio_only:
                return
                
            # Handle transcription and text translation results
            original_text = result.get("original_text")
            translated_text = result.get("translated_text")
            
            if original_text:
                # Add transcript to history and broadcast to all chat clients
                await self.add_transcript(room_id, user_id, original_text)
                
                # If we also have translated text, broadcast it
                if translated_text:
                    await self.add_translation(room_id, user_id, original_text, translated_text)
                    logger.debug(f"Broadcast transcript and translation for {user_id}: '{original_text[:30]}...'")
        
        except Exception as e:
            logger.error(f"Error processing audio for {user_id}: {e}", exc_info=True)
            
            # On any error, try to send the original audio back as fallback
            try:
                # Check if we have a buffer to return
                buffered_audio = None
                async with self.lock:
                    if room_id in self.audio_buffers and user_id in self.audio_buffers[room_id]:
                        buffered_audio = self.audio_buffers[room_id][user_id]
                        # Clear buffer after getting its contents
                        self.audio_buffers[room_id][user_id] = b''
                
                if buffered_audio and room_id in self.voice_sessions and user_id in self.voice_sessions[room_id]:
                    voice_ws = self.voice_sessions[room_id][user_id]
                    await voice_ws.send_bytes(buffered_audio)
                    logger.info(f"FALLBACK: Sent buffered audio after processing exception")
            except Exception as fallback_error:
                logger.error(f"Even fallback mechanism failed for {user_id}: {fallback_error}")
    
    async def route_video(self, room_id: str, sender_id: str, video_data: bytes) -> None:
        """
        Route video data to all users in the room except the sender
        No processing/modification of video data (following the requirements)
        """
        try:
            # Basic validation (check if data is a reasonable size for a video frame)
            if len(video_data) < 100:
                logger.warning(f"Received suspiciously small video frame ({len(video_data)} bytes) from {sender_id}")
                return
                
            # Verify video JPEG signature (basic format check)
            # JPEG files start with FF D8 and end with FF D9
            if not (video_data[0:2] == b'\xFF\xD8' and video_data[-2:] == b'\xFF\xD9'):
                logger.warning(f"Received invalid JPEG data from {sender_id}")
                # Still send it - might be another format
                
            # Broadcast to all video connections except sender
            await self.broadcast_bytes(
                room_id=room_id,
                data=video_data,
                target_sessions=self.video_sessions,
                exclude_user_id=sender_id
            )
            logger.debug(f"Routed {len(video_data)} bytes of video from {sender_id} in room {room_id}")
        except Exception as e:
            logger.error(f"Error routing video from {sender_id}: {e}")
    
    async def translate_text_message(
        self,
        room_id: str,
        user_id: str,
        text: str,
        processor: 'SpeechProcessor',
        source_language: str = "auto",
        target_language: str = "en"
    ) -> None:
        """
        Translate a text message using the processor's text translation strategy
        and broadcast the result to the room
        """
        if not text or not text.strip():
            return
            
        try:
            # Apply a timeout to prevent blocking indefinitely
            translation = await asyncio.wait_for(
                processor.text_translation_strategy.process(text),
                timeout=5.0  # Azure best practice: always apply timeouts
            )
            
            if translation:
                # Broadcast translation to all users in the room
                await self.add_translation(room_id, user_id, text, translation)
                logger.debug(f"Translated and broadcast text for {user_id} in room {room_id}")
        except asyncio.TimeoutError:
            logger.warning(f"Text translation timeout for {user_id} in room {room_id}")
        except Exception as e:
            logger.error(f"Error translating text for {user_id}: {e}", exc_info=True)
    
    # Add this method to the ChatMediator class

    async def cleanup_old_buffers(self):
        """Clean up audio buffers that are too old (should be called periodically)"""
        now = time.time()
        buffer_timeout = 30.0  # 30 seconds max lifetime for a buffer
        
        async with self.lock:
            rooms_to_check = list(self.audio_buffer_timestamps.keys())
            
            for room_id in rooms_to_check:
                if room_id not in self.audio_buffer_timestamps:
                    continue
                    
                users_to_check = list(self.audio_buffer_timestamps[room_id].keys())
                
                for user_id in users_to_check:
                    if user_id not in self.audio_buffer_timestamps[room_id]:
                        continue
                        
                    buffer_age = now - self.audio_buffer_timestamps[room_id][user_id]
                    
                    if buffer_age > buffer_timeout:
                        # Buffer is too old, process it immediately if not empty
                        if room_id in self.audio_buffers and user_id in self.audio_buffers[room_id]:
                            buffer_data = self.audio_buffers[room_id][user_id]
                            
                            if buffer_data and len(buffer_data) > 0:
                                logger.warning(f"Processing stale buffer for {user_id} in room {room_id}: {len(buffer_data)} bytes, age: {buffer_age:.2f}s")
                                
                                # Clear buffer
                                self.audio_buffers[room_id][user_id] = b''
                                self.audio_buffer_timestamps[room_id][user_id] = now
                                
                                # Get processor for this user if available
                                processor = None
                                if room_id in self.voice_sessions and user_id in self.voice_sessions[room_id]:
                                    # This is a simplification - in real code, you would need to retrieve 
                                    # the processor associated with this connection
                                    processor = SpeechProcessor(audio_only=True)
                                    
                                    # Process the buffer in a separate task
                                    if processor:
                                        asyncio.create_task(self.process_audio_stream(
                                            room_id, user_id, buffer_data, processor
                                        ))
                            else:
                                # Empty buffer, just remove it
                                del self.audio_buffers[room_id][user_id]
                                del self.audio_buffer_timestamps[room_id][user_id]
                                
                # Clean up empty room entries
                if room_id in self.audio_buffers and not self.audio_buffers[room_id]:
                    del self.audio_buffers[room_id]
                    
                if room_id in self.audio_buffer_timestamps and not self.audio_buffer_timestamps[room_id]:
                    del self.audio_buffer_timestamps[room_id]