"""
Module for managing user, chat room, and video stream resources.

This module defines classes for User, ChatRoom, and VideoStream as well as an
abstract factory interface (ResourceFactory) and its default implementation for
creating these resources.
"""

import time
from abc import ABC, abstractmethod
from fastapi import WebSocket
from typing import Dict, Optional, List
from pydantic import BaseModel, EmailStr


class User:
    """
    Represents a user in the chat system.

    Attributes:
        username (str): The username of the user.
        email (str, optional): The email address of the user.
        hashed_password (str, optional): The hashed password for authentication.
        created_at (float): Timestamp when the user was created.
        last_active (float): Timestamp of the user's last activity.
    """

    def __init__(self, username: str, email: Optional[str] = None, hashed_password: Optional[str] = None) -> None:
        """
        Initialize a User instance.

        Args:
            username (str): The username of the user.
            email (str, optional): The email address of the user.
            hashed_password (str, optional): The hashed password for authentication.
        """
        self.username = username
        self.email = email
        self.hashed_password = hashed_password
        self.created_at = time.time()
        self.last_active = self.created_at
        self.active_sessions: List[str] = []  # To track active sessions

    def to_dict(self) -> Dict:
        """Convert user to dictionary (excluding sensitive info)"""
        return {
            "username": self.username,
            "email": self.email,
            "created_at": self.created_at,
            "last_active": self.last_active
        }
        
    def update_activity(self) -> None:
        """Update the last active timestamp"""
        self.last_active = time.time()


class ChatRoom:
    """
    Represents a chat room.

    Attributes:
        room_id (str): The identifier for the chat room.
    """

    def __init__(self, room_id: str) -> None:
        """
        Initialize a ChatRoom instance.

        Args:
            room_id (str): The unique identifier for the chat room.
        """
        self.room_id = room_id


class VideoStream:
    """
    Represents a video stream for a chat room.

    Attributes:
        room_id (str): The identifier of the chat room.
        ws (WebSocket): The WebSocket connection associated with the video stream.
    """

    def __init__(self, room_id: str, ws: WebSocket) -> None:
        """
        Initialize a VideoStream instance.

        Args:
            room_id (str): The identifier for the chat room.
            ws (WebSocket): The WebSocket connection for the video stream.
        """
        self.room_id = room_id
        self.ws = ws


class ResourceFactory(ABC):
    """
    Abstract factory interface for creating chat-related resources.
    """

    @abstractmethod
    def create_user(self, username: str) -> User:
        """
        Create a new User instance.

        Args:
            username (str): The username for the user.

        Returns:
            User: A new User instance.
        """
        pass

    @abstractmethod
    def create_chatroom(self, room_id: str) -> ChatRoom:
        """
        Create a new ChatRoom instance.

        Args:
            room_id (str): The identifier for the chat room.

        Returns:
            ChatRoom: A new ChatRoom instance.
        """
        pass

    @abstractmethod
    def create_videostream(self, room_id: str, ws: WebSocket) -> VideoStream:
        """
        Create a new VideoStream instance.

        Args:
            room_id (str): The identifier for the chat room.
            ws (WebSocket): The WebSocket connection for the video stream.

        Returns:
            VideoStream: A new VideoStream instance.
        """
        pass


class DefaultResourceFactory(ResourceFactory):
    """
    Default implementation of the ResourceFactory interface.
    """

    def create_user(self, username: str) -> User:
        """
        Create a new User instance.

        Args:
            username (str): The username for the user.

        Returns:
            User: A new User instance.
        """
        return User(username)

    def create_chatroom(self, room_id: str) -> ChatRoom:
        """
        Create a new ChatRoom instance.

        Args:
            room_id (str): The identifier for the chat room.

        Returns:
            ChatRoom: A new ChatRoom instance.
        """
        return ChatRoom(room_id)

    def create_videostream(self, room_id: str, ws: WebSocket) -> VideoStream:
        """
        Create a new VideoStream instance.

        Args:
            room_id (str): The identifier for the chat room.
            ws (WebSocket): The WebSocket connection for the video stream.

        Returns:
            VideoStream: A new VideoStream instance.
        """
        return VideoStream(room_id, ws)


class UserDB:
    """
    Simple in-memory user database.
    In a production environment, this would be replaced with a real database.
    """
    def __init__(self):
        self.users: Dict[str, User] = {}
        
    def add_user(self, user: User) -> None:
        """Add a user to the database"""
        self.users[user.username] = user
        
    def get_user(self, username: str) -> Optional[User]:
        """Get a user by username"""
        return self.users.get(username)
        
    def user_exists(self, username: str) -> bool:
        """Check if a user exists"""
        return username in self.users
        
    def email_exists(self, email: str) -> bool:
        """Check if an email is already registered"""
        return any(user.email == email for user in self.users.values())


# Create a global instance of UserDB
user_db = UserDB()


class UserCreate(BaseModel):
    """Model for user registration"""
    username: str
    email: EmailStr
    password: str

    
class UserLogin(BaseModel):
    """Model for user login"""
    username: str
    password: str


class TokenResponse(BaseModel):
    """Model for token response"""
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """Model for user response"""
    username: str
    email: Optional[EmailStr] = None
    created_at: float
    last_active: float
