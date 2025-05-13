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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status, Depends, HTTPException, Header, Body, Path, Query
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import JSONResponse
from fastapi_mcp import FastApiMCP
from typing import List

from room import __app__, __author__, __version__, logger
from .room import AzureRoomManager
from .schemas.models import RoomModel, RoomParticipant, RoomRole


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


@app.post("/rooms", response_model=RoomModel, tags=["Rooms"])
def create_room(
    valid_for_minutes: int = Body(60, embed=True),
    participants: List[RoomParticipant] = Body(default_factory=list, embed=True)
):
    """Create a new room with optional participants."""
    return room_manager.create_room(valid_for_minutes=valid_for_minutes, participants=participants)


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


@app.delete("/rooms/{room_id}/participants", status_code=204, tags=["Rooms"])
def remove_participants(
    room_id: str = Path(...),
    participant_ids: List[str] = Body(..., embed=True)
):
    """Remove participants from a room by their IDs."""
    room_manager.remove_participants(room_id, participant_ids)
    return


@app.get("/rooms/{room_id}/participants", response_model=List[RoomParticipant], tags=["Rooms"])
def list_participants(room_id: str = Path(...)):
    """List all participants in a room."""
    return room_manager.list_participants(room_id)
