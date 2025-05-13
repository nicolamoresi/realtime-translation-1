"""
Room management using Azure Communication Rooms SDK (synchronous version).
Implements room CRUD, participant management, and role assignment.
Follows Azure SDK best practices for error handling and logging.
"""
import os
from datetime import datetime, timedelta
from typing import List, Optional
from azure.communication.rooms import RoomsClient, RoomParticipant, ParticipantRole
from azure.communication.rooms._shared.models import CommunicationUserIdentifier
from .schemas.models import RoomModel, RoomParticipant as RoomParticipantModel, RoomRole
import logging

logger = logging.getLogger(__name__)

COMMUNICATION_CONNECTION_STRING = os.getenv("AZURE_COMMUNICATION_CONNECTION_STRING")

class AzureRoomManager:
    """Manages rooms using Azure Communication Rooms SDK (synchronous)."""
    def __init__(self):
        if not COMMUNICATION_CONNECTION_STRING:
            raise RuntimeError("AZURE_COMMUNICATION_CONNECTION_STRING not set")
        self.client = RoomsClient.from_connection_string(COMMUNICATION_CONNECTION_STRING)

    def create_room(self, valid_for_minutes: int = 60, participants: Optional[List[RoomParticipantModel]] = None) -> RoomModel:
        valid_from = datetime.utcnow()
        valid_until = valid_from + timedelta(minutes=valid_for_minutes)
        sdk_participants = []
        if participants:
            for p in participants:
                sdk_participants.append(RoomParticipant(
                    communication_identifier=CommunicationUserIdentifier(p.id),
                    role=p.role if isinstance(p.role, ParticipantRole) else str(p.role)
                ))
        room = self.client.create_room(
            valid_from=valid_from,
            valid_until=valid_until,
            participants=sdk_participants or None
        )
        # Defensive: ensure required fields are not None
        return RoomModel(
            room_id=room.id or "",
            valid_from=room.valid_from or valid_from,
            valid_until=room.valid_until or valid_until,
            participants=[],
            created_at=getattr(room, "created_at", None),
            updated_at=getattr(room, "updated_at", None)
        )

    def get_room(self, room_id: str) -> RoomModel:
        room = self.client.get_room(room_id)
        return RoomModel(
            room_id=room.id or room_id,
            valid_from=room.valid_from or datetime.utcnow(),
            valid_until=room.valid_until or (datetime.utcnow() + timedelta(hours=1)),
            participants=[],
            created_at=getattr(room, "created_at", None),
            updated_at=getattr(room, "updated_at", None)
        )

    def list_rooms(self) -> List[RoomModel]:
        rooms = self.client.list_rooms()
        result = []
        for room in rooms:
            result.append(RoomModel(
                room_id=room.id or "",
                valid_from=room.valid_from or datetime.utcnow(),
                valid_until=room.valid_until or (datetime.utcnow() + timedelta(hours=1)),
                participants=[],
                created_at=getattr(room, "created_at", None),
                updated_at=getattr(room, "updated_at", None)
            ))
        return result

    def update_room(self, room_id: str, valid_until: Optional[datetime] = None) -> RoomModel:
        room = self.client.update_room(room_id=room_id, valid_until=valid_until)
        return RoomModel(
            room_id=room.id or room_id,
            valid_from=room.valid_from or datetime.utcnow(),
            valid_until=room.valid_until or (datetime.utcnow() + timedelta(hours=1)),
            participants=[],
            created_at=getattr(room, "created_at", None),
            updated_at=getattr(room, "updated_at", None)
        )

    def delete_room(self, room_id: str):
        self.client.delete_room(room_id=room_id)

    def add_or_update_participants(self, room_id: str, participants: List[RoomParticipantModel]):
        sdk_participants = [RoomParticipant(
            communication_identifier=CommunicationUserIdentifier(p.id),
            role=p.role if isinstance(p.role, ParticipantRole) else str(p.role)
        ) for p in participants]
        self.client.add_or_update_participants(room_id=room_id, participants=sdk_participants)

    def remove_participants(self, room_id: str, participant_ids: List[str]):
        sdk_ids: list = [CommunicationUserIdentifier(pid) for pid in participant_ids]
        self.client.remove_participants(room_id=room_id, participants=sdk_ids)  # type: ignore

    def list_participants(self, room_id: str) -> List[RoomParticipantModel]:
        result = self.client.list_participants(room_id=room_id)
        participants = []
        for p in result:
            # Always use RoomRole enum for the role field
            role_str = p.role if isinstance(p.role, str) else p.role.name
            participants.append(RoomParticipantModel(
                id=p.communication_identifier.raw_id,
                role=RoomRole(role_str),
                join_time=getattr(p, "joined_at", None)
            ))
        return participants
