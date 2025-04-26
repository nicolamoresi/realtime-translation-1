# app/router.py
import logging
import asyncio
import time
import json
from typing import Dict, Set, List, Any, Optional, Union
from fastapi import WebSocket

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
            
    async def broadcast_bytes(self, room_id: str, data: bytes, 
                             target_sessions: Optional[Dict[str, Dict[str, WebSocket]]] = None,
                             exclude_user_id: Optional[str] = None) -> None:
        """Broadcast binary data to all connections in a room"""
        if not target_sessions:
            return
            
        if room_id not in target_sessions:
            logger.debug(f"Attempted to broadcast to non-existent room: {room_id}")
            return
            
        # Get a copy of the connections to avoid modification during iteration
        connections = list(target_sessions[room_id].items())
        failed_users = []
        
        for user_id, conn in connections:
            # Skip excluded user if specified
            if exclude_user_id and user_id == exclude_user_id:
                continue
                
            try:
                await conn.send_bytes(data)
            except Exception as e:
                logger.error(f"Failed to broadcast bytes to {user_id} in room {room_id}: {e}")
                failed_users.append(user_id)
        
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
