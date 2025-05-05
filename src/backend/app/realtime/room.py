"""
Multi-peer room implementation for Azure real-time translation.

Provides coordination between multiple RealtimeClient instances to create
virtual "rooms" where multiple participants can communicate.
"""
import asyncio
import uuid
from collections import defaultdict
from typing import Any

from .client import RealtimeClient


class RealtimeRoom:
    """
    Creates a logical room grouping multiple RealtimeClient instances.
    
    Each client maintains its own WebSocket connection to the Azure OpenAI
    Realtime API, while the room coordinates event distribution and provides
    a unified interface.
    
    Follows Azure best practices:
    - Unique identification of users with UUIDs
    - Event-driven communication
    - Resource lifecycle management
    - Error isolation between participants
    """
    
    def __init__(self, system_prompt: str) -> None:
        """
        Initialize a new real-time room.
        
        Args:
            system_prompt: System instructions for all participants
        """
        self.system_prompt = system_prompt
        self.participants: dict[str, RealtimeClient] = {}
        self.user_identities: dict[str, dict[str, str]] = {}
        self._listeners = defaultdict(lambda: [])  # room-level event listeners

    def _generate_user_id(self, username: str) -> str:
        """
        Generate a unique user ID with random suffix for anonymous users.
        
        Args:
            username: Base username or anonymous identifier
            
        Returns:
            A unique user ID
        """
        if username.startswith("anonymous-"):
            # Add a random UUID suffix for anonymous users
            session_id = str(uuid.uuid4())[:8]
            return f"{username}_{session_id}"
        return username

    async def add_participant(self, username: str) -> tuple[str, RealtimeClient]:
        """
        Add a new participant to the room.
        
        Creates a unique user ID, establishes a RealtimeClient,
        and sets up event relaying.
        
        Args:
            username: The participant's username or identifier
            
        Returns:
            A tuple of (user_id, client)
            
        Raises:
            RuntimeError: If establishing the connection fails
        """
        # Generate unique user ID
        user_id = self._generate_user_id(username)
        
        # Check if participant already exists
        if user_id in self.participants:
            # Remove existing participant
            await self.remove_participant(user_id)
        
        # Create and connect a new client
        client = RealtimeClient(self.system_prompt)
        
        try:
            # Connect to Azure OpenAI
            await client.connect()
            await client.wait_for_session_created()
            
            # Store participant
            self.participants[user_id] = client
            
            # Store identity information
            self.user_identities[user_id] = {
                "username": username,
                "session_id": user_id.split("_")[1] if "_" in user_id else ""
            }
            
            # Set up event relaying
            client.on("conversation.item.appended",
                     lambda e, p=user_id: self._relay("item.appended", p, e))
            client.on("conversation.item.completed",
                     lambda e, p=user_id: self._relay("item.completed", p, e))
            
            return user_id, client
            
        except Exception as e:
            # Clean up if connection fails
            if client.is_connected():
                await client.disconnect()
            raise RuntimeError(f"Failed to add participant: {e}")

    async def remove_participant(self, user_id: str) -> None:
        """
        Remove a participant from the room.
        
        Args:
            user_id: Identifier of the participant to remove
        """
        client = self.participants.pop(user_id, None)
        self.user_identities.pop(user_id, None)
        
        if client and client.is_connected():
            await client.disconnect()

    def get_participants(self) -> list[dict[str, Any]]:
        """
        Get information about all participants in the room.
        
        Returns:
            list of participant information dictionaries
        """
        return [
            {
                "user_id": user_id,
                "username": self.user_identities.get(user_id, {}).get("username", user_id),
                "session_id": self.user_identities.get(user_id, {}).get("session_id"),
                "anonymous": user_id.startswith("anonymous-")
            }
            for user_id in self.participants.keys()
        ]

    async def broadcast_message(self, content: Any) -> None:
        """
        Send the same message to all participants.
        
        Args:
            content: Message content to broadcast
        """
        # Create tasks for each participant
        tasks = []
        for user_id, client in self.participants.items():
            if client.is_connected():
                tasks.append(client.send_user_message_content(content))
        
        # Execute in parallel
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def on(self, event_name: str, handler: Any) -> None:
        """
        Register an event handler at the room level.
        
        Args:
            event_name: Event to listen for
            handler: Function or coroutine to call when event occurs
        """
        self._listeners[event_name].append(handler)

    def _relay(self, room_event: str, from_user_id: str, payload: Any) -> None:
        """
        Relay events from a participant to room-level listeners.
        
        Args:
            room_event: Event type
            from_user_id: Source participant ID
            payload: Event data
        """
        for handler in self._listeners[room_event]:
            if asyncio.iscoroutinefunction(handler):
                asyncio.create_task(handler(from_user_id, payload))
            else:
                handler(from_user_id, payload)
