"""
Observer pattern and ACS event handling for real-time translation backend.

This module defines the Subject/Observer pattern for managing user/room/call state, and integrates
Azure Communication Services (ACS) event handling for call automation and media streaming.
It also provides session and WebSocket mapping for real-time translation.
"""

from abc import ABC, abstractmethod

import os
import uuid

from urllib.parse import urlencode
from typing import Dict, Set, Any, Optional

from azure.communication.callautomation import CallAutomationClient, MediaStreamingOptions
from azure.communication.rooms import RoomsClient, RoomParticipant, ParticipantRole
from azure.communication.identity import CommunicationIdentityClient
from azure.eventgrid import EventGridEvent, SystemEventNames

from orchestrator.engine import Invoker
from orchestrator.schemas.models import CallConnectionInfo
from orchestrator import logger


ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")
CALLBACK_URI = os.environ.get("CALLBACK_EVENTS_URI", "https://svd8j22b-9000.brs.devtunnels.ms/callbacks")
WEBSOCKET_URI = os.environ.get('WEBSOCKET_EVENTS_URI', 'wss://svd8j22b-9000.brs.devtunnels.ms/ws')


class Subject(ABC):
    """Abstract base class for subjects in the Observer pattern.

    Methods:
        attach(observer): Attach an observer.
        detach(observer): Detach an observer.
        notify(event): Notify all observers of an event.
    """

    @abstractmethod
    def attach(self, observer: 'Observer') -> None:
        """Attach an observer to the subject."""

    @abstractmethod
    def detach(self, observer: 'Observer') -> None:
        """Detach an observer from the subject."""

    @abstractmethod
    def notify(self, event: 'RoomUserEvent') -> None:
        """Notify all observers about an event."""


class Observer(ABC):
    """Abstract base class for observers in the Observer pattern.

    Methods:
        update(subject, event): Receive update from subject.
    """

    @abstractmethod
    def update(self, subject: Subject, event: 'RoomUserEvent') -> None:
        """Receive update from subject."""


class RoomUserEvent:
    """Represents an event in the room/user system (join, leave, call, etc).

    Attributes:
        event_type (str): The type of event.
        user_id (str): The user ID involved.
        room_id (str): The room ID involved.
        data (dict): Additional event data.
    """

    def __init__(self, event_type: str, user_id: Optional[str] = None, room_id: Optional[str] = None, data: Optional[dict] = None):
        self.event_type = event_type
        self.user_id = user_id
        self.room_id = room_id
        self.data = data or {}


class RoomUserObserver(Subject):
    """Observer subject for managing room/user state and ACS event handling.

    Manages rooms, users, sessions, and call connection mappings.
    Handles ACS incoming call and callback events, and triggers translation using the Command pattern.

    Methods:
        handle_incoming_call(event_dict): Handle ACS incoming call events.
        handle_callback_event(event): Handle ACS callback events.
        register_websocket(session_id, websocket): Register a WebSocket for a session.
        get_websocket_for_connection(call_connection_id): Get WebSocket for a call connection.
    """

    def __init__(self):
        self._observers: Set[Observer] = set()
        self._rooms: Dict[str, Set[str]] = {}
        self._user_room: Dict[str, str] = {}
        self._user_info: Dict[str, Dict[str, Any]] = {}
        self._call_connections: Dict[str, CallConnectionInfo] = {}
        self._invokers: Dict[str, Invoker] = {}
        self._connection_session: Dict[str, str] = {}
        acs_conn_str = os.environ.get("ACS_CONNECTION_STRING", "")
        self.acs_client = CallAutomationClient.from_connection_string(acs_conn_str)
        self.identity_client = CommunicationIdentityClient.from_connection_string(acs_conn_str)
        self.rooms_client = RoomsClient.from_connection_string(acs_conn_str)

    def attach(self, observer: 'Observer') -> None:
        """Attach an observer to the subject."""
        self._observers.add(observer)

    def detach(self, observer: 'Observer') -> None:
        """Detach an observer from the subject."""
        self._observers.discard(observer)

    def notify(self, event_type: str, payload: dict) -> None:
        """Notify all observers with a RoomUserEvent."""
        event = RoomUserEvent(
            event_type=event_type,
            user_id=payload.get('user_id'),
            room_id=payload.get('room_id'),
            data=payload
        )
        for observer in self._observers:
            observer.update(self, event)

    def register_invoker(self, session_id: str, invoker: Invoker):
        """Register a WebSocket for a session.""" 
        self._invokers[session_id] = invoker

    def unregister_invoker(self, session_id: str):
        """Remove a WebSocket mapping for a session."""
        self._invokers.pop(session_id, None)

    def map_connection_to_session(self, call_connection_id: str, session_id: str):
        """Associate a call connection ID with a session ID."""
        self._connection_session[call_connection_id] = session_id

    def get_invoker_for_connection(self, call_connection_id: str):
        """Retrieve the WebSocket for a given call connection ID."""
        return self._invokers.get(call_connection_id)

    async def handle_incoming_call(self, event_dict):
        """Handles EventGrid events for ACS incoming calls using the ACS SDK."""
        event = EventGridEvent.from_dict(event_dict)
        match event.event_type:
            case SystemEventNames.EventGridSubscriptionValidationEventName:
                return self._handle_subscription_validation(event)
            case 'Microsoft.Communication.CallStarted':
                return await self._handle_acs_incoming_call(event)
            case _:
                self.notify('incoming_call_unhandled', {"event": event_dict})
                return None

    def _handle_subscription_validation(self, event):
        """Handle EventGrid subscription validation event."""
        validation_code = event.data["validationCode"]
        return {"validationResponse": validation_code}

    async def _handle_acs_incoming_call(self, event):
        """Handle ACS incoming call event."""
        caller_id = event.data["startedBy"]["communicationIdentifier"]["rawId"]
        room_id = event.data["room"]["id"]
        guid = uuid.uuid4()
        callback_uri, websocket_url = self._build_callback_uris(caller_id, guid)
        if not self.acs_client:
            raise RuntimeError("ACS client not initialized. Set AZURE_COMMUNICATION_CONNECTION_STRING.")
        try:
            media_streaming_options = MediaStreamingOptions(
                transport_url=websocket_url,
                transport_type="websocket",
                content_type="audio",
                audio_channel_type="mixed",
                start_media_streaming=True,
                enable_bidirectional=True,
                audio_format="pcm16KMono"
            )  #type: ignore
            answer_call_result = self.acs_client.connect_call(
                room_id=room_id,
                operation_context="incomingCall",
                callback_url=callback_uri,
                media_streaming=media_streaming_options,
            )

        except Exception as e:
            logger.error(f"Failed to answer ACS call: {e}")
            raise RuntimeError(f"Failed to answer ACS call: {e}")

        call_connection_id = answer_call_result.call_connection_id

        if not call_connection_id:
            logger.error("Failed to answer ACS call, no call_connection_id returned.")
            raise RuntimeError("Failed to answer ACS call, no call_connection_id returned.")

        bot_info = {"display_name": "Interpreter", "language": "en"}

        self._call_connections[call_connection_id] = CallConnectionInfo(**{
            "caller_id": caller_id,
            "room_id": room_id,
            "callback_uri": callback_uri,
            "websocket_url": websocket_url,
            "call_connection_id": answer_call_result.call_connection_id,
            "bot_display_name": bot_info["display_name"],
            "bot_language": bot_info["language"]
        })

        self.notify('incoming_call', self._call_connections[call_connection_id].model_dump())
        return self._call_connections[call_connection_id]

    def _build_callback_uris(self, caller_id, guid):
        """Build callback and websocket URIs for ACS call answer."""
        query_parameters = urlencode({"callerId": caller_id})
        callback_uri = f"{CALLBACK_URI}/{guid}?{query_parameters}"
        websocket_url = WEBSOCKET_URI
        return callback_uri, websocket_url

    async def handle_callback_event(self, event):
        """Handles callbacks from ACS (CallConnected, MediaStreamingStarted, etc). Triggers translation command on CallConnected."""
        event_data = event["data"]
        call_connection_id = event_data.get("callConnectionId")
        event_type = event["type"]

        match event_type:
            case "Microsoft.Communication.CallConnected":
                await self._handle_call_connected(event_data, call_connection_id)
            case "Microsoft.Communication.MediaStreamingStarted":
                await self._handle_media_streaming_started(event_data, call_connection_id)
            case "Microsoft.Communication.MediaStreamingStopped":
                await self._handle_media_streaming_stopped(event_data, call_connection_id)
            case "Microsoft.Communication.MediaStreamingFailed":
                await self._handle_media_streaming_failed(event_data, call_connection_id)
            case "Microsoft.Communication.ParticipantsUpdated":
                await self._handle_participant_updated(event_data, call_connection_id)
            case "Microsoft.Communication.AddParticipantFailed":
                await self._handle_add_participant_failed(event_data, call_connection_id)                
            case _:
                self._handle_callback_event_default(event_type, event_data, call_connection_id)
        self.notify('callback_event', {"type": event_type, "call_connection_id": call_connection_id, "data": event_data})
        return {"call_connection_id": call_connection_id, "type": event_type}

    async def _handle_call_connected(self, event_data, call_connection_id):
        logger.info(f"Connecting to call with id {call_connection_id}")
        if self.acs_client and call_connection_id:
            try:
                call_connection = self.acs_client.get_call_connection(call_connection_id)
                call_properties = call_connection.get_call_properties()
                media_streaming_subscription = getattr(call_properties, "media_streaming_subscription", None)

                self._call_connections[call_connection_id].last_event_data = event_data
                self._call_connections[call_connection_id].media_streaming_subscription = media_streaming_subscription

                call_info = self._call_connections.get(call_connection_id, None)

                if not call_info:
                    logger.error(f"No bot_info found for call_connection_id={call_connection_id}. Cannot join bot to call.")
                    call_connection.hang_up(is_for_everyone=True)

                bot_info = {'display_name': call_info.bot_display_name, 'language': call_info.bot_language}  #type: ignore
                logger.info(f"bot_info for call_connection_id={call_connection_id}: {bot_info}")

                self.join_bot_to_acs_call(call_connection_id, bot_info)
            except Exception as e:
                logger.error(f"Failed to get call properties for {call_connection_id}: {e}")

    async def _handle_media_streaming_started(self, event_data, call_connection_id):
        logger.info(f"Media streaming started for call_connection_id={call_connection_id}")

    async def _handle_media_streaming_stopped(self, event_data, call_connection_id):
        logger.info(f"Media streaming stopped for call_connection_id={call_connection_id}")
        if not call_connection_id in self._call_connections:
            logger.warning(f"Call connection {call_connection_id} not found in active connections.")
        call_connection = self.acs_client.get_call_connection(call_connection_id)
        call_connection.hang_up(is_for_everyone=True)

    async def _handle_media_streaming_failed(self, event_data, call_connection_id):
        logger.error(f"Media streaming failed for call_connection_id={call_connection_id}")
        call_connection = self.acs_client.get_call_connection(call_connection_id)
        call_connection.hang_up(is_for_everyone=True)

    async def _handle_participant_updated(self, event_data, call_connection_id):
        call_data = self._call_connections.get(call_connection_id)
        participants = [
            participant.communication_identifier.raw_id
            for participant in self.rooms_client.list_participants(room_id=call_data.room_id)  # type: ignore
        ]
        logger.info(f"Participants updated for call_connection_id={call_connection_id}: {participants}")

    async def _handle_add_participant_failed(self, event_data, call_connection_id):
        logger.error(f"Failed to add participant to call_connection_id={call_connection_id}: {event_data.get('errorMessage', 'Unknown error')}")
        call_connection = self.acs_client.get_call_connection(call_connection_id)
        call_connection.hang_up(is_for_everyone=True)
        logger.error(f"Failed to add participant to call_connection_id={call_connection_id}. Hanging up call.")

    def _handle_callback_event_default(self, event_type, event_data, call_connection_id):
        logger.warning(f"Unhandled ACS callback event: {event_type} for call_connection_id={call_connection_id}")

    def join_bot_to_acs_call(self, connection_id: str, bot_info: dict):
        """
        Prepare the bot to join the ACS call for the given room.
        The bot will be added as a participant after the call is established (in _handle_call_connected).
        """
        logger.info(
            "Adding bot '%s' as participant to ACS call (call_connection_id=%s)",
            bot_info.get('bot_display_name', 'Bot'),
            connection_id
        )
        bot_user, bot_token = self.identity_client.create_user_and_token(scopes=["voip", "chat"])
        current_connection = self._call_connections[connection_id]
        current_connection.bot_id = bot_user.raw_id

        room = self.rooms_client.get_room(current_connection.room_id)
        if not room:
            logger.error(f"Room with ID {current_connection.room_id} not found.")
            raise RuntimeError(f"Room with ID {current_connection.room_id} not found.")

        participant = RoomParticipant(
            communication_identifier=bot_user,  # type: ignore
            role=ParticipantRole.PRESENTER  # Adjust role as needed
        )

        try:
            self.rooms_client.add_or_update_participants(
                room_id=current_connection.room_id,
                participants=[participant]
            )
            logger.info(f"Bot successfully added as participant to room {current_connection.room_id} with ID {bot_user.raw_id}.")
        except Exception as e:
            logger.error(f"Failed to add bot as participant: {e}")

        logger.info(f"Bot info stored for room {connection_id}, will add after call is established.")


class RoomUserEventObserver(Observer):
    """Example observer that reacts to room/user events."""

    def update(self, subject: RoomUserObserver, event: RoomUserEvent) -> None:
        """React to room/user events."""
        if event.event_type == 'user_joined':
            pass
        elif event.event_type == 'user_left':
            pass
        elif event.event_type.startswith('call'):
            pass


class LoggingObserver(Observer):
    """Observer that logs all events for debugging and monitoring."""

    def update(self, subject: Subject, event: RoomUserEvent) -> None:
        """Log the event details."""
        print(f"[LoggingObserver] Event: {event.event_type}, \n User: {event.user_id}, \n Room: {event.room_id}, \n Data: {event.data}")
