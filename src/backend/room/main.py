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
import re
from base64 import b64decode

from starlette.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException, Body, Path
from fastapi.security import OAuth2PasswordBearer
from fastapi_mcp import FastApiMCP
from typing import List, cast, Literal

from room import __app__, __author__, __version__, logger
from room.client import AzureRoomManager
from room.schemas.models import RoomModel, RoomParticipant
from azure.communication.identity import CommunicationIdentityClient, CommunicationUserIdentifier, CommunicationTokenScope
from azure.core.exceptions import ResourceNotFoundError


tags_metadata: list[dict] = [
    {
        "name": "Rooms",
        "description": "Endpoints for Azure Communication Rooms management: create, update, retrieve, list, delete rooms, and manage participants and roles using the Azure Communication Rooms SDK.",
    },
    {
        "name": "Participants",
        "description": "Endpoints for managing room participants and their roles in Azure Communication Rooms.",
    },
]

description: str = """
Azure Communication Rooms API
----------------------------
FastAPI backend for managing rooms and participants using Azure Communication Rooms SDK. 
Provides endpoints for room CRUD, participant management, and role assignment, following Azure best practices.
"""


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
app = FastAPI(title=__app__, version=__version__, description=description, openapi_tags=tags_metadata)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

mcp = FastApiMCP(app)

room_manager = AzureRoomManager()

# Initialize ACS Identity Client
ACS_CONNECTION_STRING = os.getenv("ACS_CONNECTION_STRING")
if not ACS_CONNECTION_STRING:
    raise RuntimeError("ACS_CONNECTION_STRING environment variable is not set.")
identity_client = CommunicationIdentityClient.from_connection_string(ACS_CONNECTION_STRING)


@app.post("/rooms", response_model=RoomModel, tags=["Rooms"])
def create_room(
    valid_for_minutes: int = Body(60, embed=True),
    participants: List[RoomParticipant] = Body(default_factory=list, embed=True)
):
    """Create a new room with optional participants."""
    # Validate ACS IDs
    def is_valid_acs_id(acs_id: str) -> bool:
        return bool(re.match(r'^8:[a-z]+:[\w-]+$', acs_id))

    for p in participants:
        if not is_valid_acs_id(p.id):
            logger.error(f"Invalid ACS ID: {p.id}")
            raise HTTPException(status_code=400, detail=f"Invalid ACS ID: {p.id}")
    try:
        room = room_manager.create_room(valid_for_minutes=valid_for_minutes, participants=participants)
        room.participants = participants
        return room
    except Exception as e:
        logger.error(f"Failed to create room: {e}")
        raise HTTPException(status_code=500, detail="Failed to create room")


@app.get("/rooms/{room_id}", response_model=RoomModel, tags=["Rooms"])
def get_room(room_id: str = Path(...)):
    """Get details of a room by ID."""
    return room_manager.get_room(room_id)


@app.get("/rooms", response_model=List[RoomModel], tags=["Rooms"])
def list_rooms():
    """List all rooms."""
    return room_manager.list_rooms()


@app.patch("/rooms/{room_id}", response_model=RoomModel, tags=["Rooms"])
def update_room(
    room_id: str = Path(...),
    valid_until: str = Body(..., embed=True)
):
    """Update a room's valid_until timestamp."""
    from datetime import datetime
    return room_manager.update_room(room_id, valid_until=datetime.fromisoformat(valid_until))


@app.delete("/rooms/{room_id}", status_code=204, tags=["Rooms"])
def delete_room(room_id: str = Path(...)):
    """Delete a room by ID."""
    room_manager.delete_room(room_id)
    return


@app.post("/rooms/{room_id}/participants", status_code=204, tags=["Rooms"])
def add_or_update_participants(
    room_id: str = Path(...),
    participants: List[RoomParticipant] = Body(..., embed=True)
):
    """Add or update participants in a room."""
    room_manager.add_or_update_participants(room_id, participants)
    return


@app.post("/rooms/{room_id}/participants/remove", status_code=204, tags=["Rooms"])
def remove_participants_post(
    room_id: str = Path(...),
    participant_ids: List[str] = Body(..., embed=True)
):
    """Remove participants from a room by their IDs (POST for API consistency)."""
    try:
        room_manager.remove_participants(room_id, participant_ids)
    except Exception as e:
        logger.error(f"Failed to remove participants: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove participants")
    return


@app.delete("/rooms/{room_id}/participants", status_code=204, tags=["Rooms"])
def remove_participants(
    room_id: str = Path(...),
    participant_ids: List[str] = Body(..., embed=True)
):
    """Remove participants from a room by their IDs."""
    try:
        room_manager.remove_participants(room_id, participant_ids)
    except Exception as e:
        logger.error(f"Failed to remove participants: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove participants")
    return


@app.get("/rooms/{room_id}/participants", response_model=List[RoomParticipant], tags=["Rooms"])
def list_participants(room_id: str = Path(...)):
    """List all participants in a room."""
    return room_manager.list_participants(room_id)


@app.post("/rooms/{room_id}/token", tags=["Rooms"])
def get_room_token(
    room_id: str = Path(...),
    user_id: str = Body(None, embed=True),
    role: str = Body("Attendee", embed=True)
):
    """Get an ACS token for a user to join a room. If user_id is not provided, create a new ACS user (anonymous join). Adds user as participant if not present."""
    logger.info(f"[get_room_token] Called for room_id={room_id}, user_id={user_id}, role={role}")
    try:

        if room_id == "demo":
            demo_user = identity_client.create_user()
            demo_user_id = getattr(demo_user, 'properties', {}).get("id", getattr(demo_user, 'id', None))
            logger.info(f"[get_room_token] Created demo ACS user: {demo_user_id}")
            if not isinstance(demo_user_id, str) or not demo_user_id:
                logger.error(f"[get_room_token] Failed to create a valid ACS user for demo room.")
                raise HTTPException(status_code=500, detail="Failed to create demo ACS user")
            if not user_id:
                user_id = demo_user_id
            role_literal = "Presenter"
            logger.info(f"[get_room_token] Adding demo user {user_id} as {role_literal} to demo room {room_id}")
            room_manager.add_or_update_participants(room_id, [RoomParticipant(id=user_id, role=role_literal, join_time=None)])
            user = CommunicationUserIdentifier(user_id)
            scopes = [CommunicationTokenScope.VOIP]
            token_response = identity_client.get_token(user, scopes)
            logger.info(f"[get_room_token] Issued demo token for user {user_id} in room {room_id}")
            return {
                "user_id": user_id,
                "token": token_response.token,
                "expires_on": token_response.expires_on
            }

        if user_id:
            user = CommunicationUserIdentifier(user_id)
        else:
            user = identity_client.create_user()
            user_id = getattr(user, 'properties', {}).get("id", getattr(user, 'id', ''))
            logger.info(f"[get_room_token] Created new ACS user: {user_id}")
            if not isinstance(user_id, str) or not user_id:
                logger.error(f"[get_room_token] Failed to create ACS user")
                raise HTTPException(status_code=500, detail="Failed to create ACS user")
        # Ensure role is a valid literal
        valid_roles = ["Presenter", "Attendee", "Consumer"]
        role_literal = role if role in valid_roles else "Attendee"
        # Cast to the expected Literal type
        role_literal = cast(Literal['Presenter', 'Attendee', 'Consumer'], role_literal)
        try:
            logger.info(f"[get_room_token] Adding/updating user {user_id} as {role_literal} in room {room_id}")
            room_manager.add_or_update_participants(room_id, [RoomParticipant(id=user_id, role=role_literal, join_time=None)])
        except Exception as e:
            logger.warning(f"[get_room_token] Could not add participant (may already exist): {e}")
        # Confirm user is present in room after add
        participants = room_manager.list_participants(room_id)
        logger.info(f"[get_room_token] Participants in room {room_id} after add: {[p.id for p in participants]}")
        if not any(p.id == user_id for p in participants):
            logger.error(f"[get_room_token] User {user_id} not present in room {room_id} after add.")
            raise HTTPException(status_code=500, detail="User not present in room after add.")
        # Issue token
        scopes = [CommunicationTokenScope.VOIP]
        token_response = identity_client.get_token(user, scopes)
        logger.info(f"[get_room_token] Issued token for user {user_id} in room {room_id} with role {role_literal}")
        logger.info(f"[get_room_token] Token: {token_response.token[:10]}... expires_on: {token_response.expires_on}")
        return {
            "user_id": user_id,
            "token": token_response.token,
            "expires_on": token_response.expires_on  # integer timestamp
        }
    except ResourceNotFoundError:
        logger.error(f"[get_room_token] Room not found: {room_id}")
        raise HTTPException(status_code=404, detail="Room not found")
    except Exception as e:
        logger.error(f"[get_room_token] Failed to get room token: {e}")
        raise HTTPException(status_code=500, detail="Failed to get room token")


@app.post("/acs/users", tags=["ACS"])
def create_acs_user():
    """Create a new ACS user and return its ID."""
    try:
        user = identity_client.create_user()
        user_id = getattr(user, 'properties', {}).get("id", getattr(user, 'id', None))
        if not user_id:
            raise HTTPException(status_code=500, detail="Failed to create ACS user")
        return {"id": user_id}
    except Exception as e:
        logger.error(f"Failed to create ACS user: {e}")
        raise HTTPException(status_code=500, detail="Failed to create ACS user")
