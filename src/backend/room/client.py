"""
Room management using Azure Communication Rooms SDK (synchronous version).
Implements room CRUD, participant management, and role assignment.
Follows Azure SDK best practices for error handling and logging.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from dotenv import find_dotenv, load_dotenv
from azure.communication.rooms import RoomsClient, RoomParticipant, ParticipantRole, CommunicationUserIdentifier

from room import logger
from room.schemas.models import RoomModel, RoomParticipant as RoomParticipantModel

load_dotenv(find_dotenv())
COMMUNICATION_CONNECTION_STRING = os.getenv("ACS_CONNECTION_STRING", "")


class AzureRoomManager:
    """Manages rooms using Azure Communication Rooms SDK (synchronous)."""
    def __init__(self):
        if not COMMUNICATION_CONNECTION_STRING:
            logger.error("ACS_CONNECTION_STRING not set")
            raise RuntimeError("ACS_CONNECTION_STRING not set")
        self.client = RoomsClient.from_connection_string(COMMUNICATION_CONNECTION_STRING)
        logger.info("AzureRoomManager initialized successfully")

    def _to_participant_role(self, role):
        if isinstance(role, ParticipantRole):
            return role
        if isinstance(role, str):
            try:
                return ParticipantRole(role.capitalize())
            except Exception:
                return ParticipantRole.ATTENDEE
        return ParticipantRole.ATTENDEE

    def create_room(self, valid_for_minutes: int = 60, participants: Optional[List[RoomParticipantModel]] = None) -> RoomModel:
        logger.info("Creating room with validity of %d minutes", valid_for_minutes)
        valid_from = datetime.now(timezone.utc)
        valid_until = valid_from + timedelta(minutes=valid_for_minutes)
        sdk_participants = []
        if participants:
            for p in participants:
                logger.debug("Adding participant with ID: %s and role: %s", p.id, p.role)
                sdk_participants.append(RoomParticipant(
                    communication_identifier=CommunicationUserIdentifier(p.id),
                    role=self._to_participant_role(p.role)
                ))
        try:
            room = self.client.create_room(
                valid_from=valid_from,
                valid_until=valid_until,
                participants=sdk_participants or None
            )
            logger.info("Room created successfully with ID: %s", room.id)
            participants_list = self.list_participants(room.id or "")
            return RoomModel(
                room_id=room.id or "",
                valid_from=room.valid_from or valid_from,
                valid_until=room.valid_until or valid_until,
                participants=participants_list,
                created_at=getattr(room, "created_at", None),
                updated_at=getattr(room, "updated_at", None)
            )
        except Exception as e:
            logger.error(f"Failed to create room: {e}")
            raise

    def get_room(self, room_id: str) -> RoomModel:
        logger.info("Fetching room with ID: %s", room_id)
        try:
            room = self.client.get_room(room_id)
            logger.info("Room fetched successfully with ID: %s", room.id)
            participants_list = self.list_participants(room.id or room_id)
            return RoomModel(
                room_id=room.id or room_id,
                valid_from=room.valid_from or datetime.now(timezone.utc),
                valid_until=room.valid_until or (datetime.now(timezone.utc) + timedelta(hours=1)),
                participants=participants_list,
                created_at=getattr(room, "created_at", None),
                updated_at=getattr(room, "updated_at", None)
            )
        except Exception as e:
            logger.error(f"Failed to fetch room: {e}")
            raise

    def list_rooms(self) -> List[RoomModel]:
        logger.info("Listing all rooms")
        try:
            rooms = self.client.list_rooms()
            result = []
            for room in rooms:
                logger.debug("Found room with ID: %s", room.id)
                participants_list = self.list_participants(room.id or "")
                result.append(RoomModel(
                    room_id=room.id or "",
                    valid_from=room.valid_from or datetime.now(timezone.utc),
                    valid_until=room.valid_until or (datetime.now(timezone.utc) + timedelta(hours=1)),
                    participants=participants_list,
                    created_at=getattr(room, "created_at", None),
                    updated_at=getattr(room, "updated_at", None)
                ))
            logger.info("Total rooms listed: %d", len(result))
            return result
        except Exception as e:
            logger.error(f"Failed to list rooms: {e}")
            raise

    def update_room(self, room_id: str, valid_until: Optional[datetime] = None) -> RoomModel:
        logger.info("Updating room with ID: %s", room_id)
        try:
            room = self.client.update_room(room_id=room_id, valid_until=valid_until)
            logger.info("Room updated successfully with ID: %s", room.id)
            participants_list = self.list_participants(room.id or room_id)
            return RoomModel(
                room_id=room.id or room_id,
                valid_from=room.valid_from or datetime.now(timezone.utc),
                valid_until=room.valid_until or (datetime.now(timezone.utc) + timedelta(hours=1)),
                participants=participants_list,
                created_at=getattr(room, "created_at", None),
                updated_at=getattr(room, "updated_at", None)
            )
        except Exception as e:
            logger.error(f"Failed to update room: {e}")
            raise

    def delete_room(self, room_id: str):
        logger.info("Deleting room with ID: %s", room_id)
        self.client.delete_room(room_id=room_id)
        logger.info("Room deleted successfully with ID: %s", room_id)

    def add_or_update_participants(self, room_id: str, participants: List[RoomParticipantModel]):
        logger.info("Adding or updating participants for room ID: %s", room_id)
        sdk_participants = [RoomParticipant(
            communication_identifier=CommunicationUserIdentifier(id=p.id),
            role=self._to_participant_role(p.role)
        ) for p in participants]
        try:
            self.client.add_or_update_participants(room_id=room_id, participants=sdk_participants)
            logger.info("Participants added or updated successfully for room ID: %s", room_id)
        except Exception as e:
            logger.error(f"Failed to add or update participants: {e}")
            raise

    def remove_participants(self, room_id: str, participant_ids: List[str]):
        logger.info("Removing participants from room ID: %s", room_id)
        sdk_ids: list = [CommunicationUserIdentifier(id=pid) for pid in participant_ids]
        self.client.remove_participants(room_id=room_id, participants=sdk_ids)  # type: ignore
        logger.info("Participants removed successfully from room ID: %s", room_id)

    def list_participants(self, room_id: str) -> List[RoomParticipantModel]:
        logger.info("Listing participants for room ID: %s", room_id)
        result = self.client.list_participants(room_id=room_id)
        participants = []
        for p in result:
            logger.debug("Found participant with ID: %s and role: %s", p.communication_identifier.raw_id, p.role)
            role_str = p.role if isinstance(p.role, str) else p.role.name
            valid_roles = ["Attendee", "Consumer", "Presenter"]
            role_literal = role_str if role_str in valid_roles else "Consumer"
            participants.append(RoomParticipantModel(
                id=p.communication_identifier.raw_id,
                role=role_literal,  # type: ignore
                join_time=getattr(p, "joined_at", None)
            ))
        logger.info("Total participants listed for room ID %s: %d", room_id, len(participants))
        return participants
