"""
Observer pattern and ACS event handling for real-time translation backend.

This module defines the Subject/Observer pattern for managing user/room/call state, and integrates Azure Communication Services (ACS) event handling for call automation and media streaming. It also provides session and WebSocket mapping for real-time translation.
"""

from abc import ABC, abstractmethod

import asyncio
import logging
import os
import uuid
import base64

from urllib.parse import urlencode, urlparse, urlunparse
from typing import Dict, Set, Any, Optional

from azure.communication.callautomation import CallAutomationClient, MediaStreamingOptions, CommunicationUserIdentifier
from azure.communication.identity import CommunicationIdentityClient
from azure.eventgrid import EventGridEvent, SystemEventNames


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
        pass

    @abstractmethod
    def detach(self, observer: 'Observer') -> None:
        """Detach an observer from the subject."""
        pass

    @abstractmethod
    def notify(self, event: 'RoomUserEvent') -> None:
        """Notify all observers about an event."""
        pass


class Observer(ABC):
    """Abstract base class for observers in the Observer pattern.

    Methods:
        update(subject, event): Receive update from subject.
    """

    @abstractmethod
    def update(self, subject: Subject, event: 'RoomUserEvent') -> None:
        """Receive update from subject."""
        pass


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

    Manages rooms, users, sessions, and call connection mappings. Handles ACS incoming call and callback events, and triggers translation using the Command pattern.

    Methods:
        join_room(user_id, room_id, user_info): Register a user joining a room.
        leave_room(user_id): Register a user leaving a room.
        handle_incoming_call(event_dict): Handle ACS incoming call events.
        handle_callback_event(event): Handle ACS callback events.
        register_websocket(session_id, websocket): Register a WebSocket for a session.
        unregister_websocket(session_id): Remove a WebSocket mapping.
        map_connection_to_session(call_connection_id, session_id): Map ACS call connection to session.
        get_websocket_for_connection(call_connection_id): Get WebSocket for a call connection.
    """

    def __init__(self):
        self._observers: Set[Observer] = set()
        self._rooms: Dict[str, Set[str]] = {}
        self._user_room: Dict[str, str] = {}
        self._user_info: Dict[str, Dict[str, Any]] = {}
        self._call_connections: Dict[str, dict] = {}
        self._session_websockets: Dict[str, Any] = {}
        self._connection_session: Dict[str, str] = {}
        acs_conn_str = os.environ.get("ACS_CONNECTION_STRING", "")
        self.acs_client = CallAutomationClient.from_connection_string(acs_conn_str)
        self.identity_client = CommunicationIdentityClient.from_connection_string(acs_conn_str)

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

    def join_room(self, user_id: str, room_id: str, user_info: Optional[dict] = None):
        """Register a user joining a room."""
        if room_id not in self._rooms:
            self._rooms[room_id] = set()
        self._rooms[room_id].add(user_id)
        self._user_room[user_id] = room_id
        if user_info:
            self._user_info[user_id] = user_info
        self.notify('user_joined', {'user_id': user_id, 'room_id': room_id, 'user_info': user_info})

    def leave_room(self, user_id: str):
        """Register a user leaving a room."""
        room_id = self._user_room.get(user_id)
        if room_id and user_id in self._rooms.get(room_id, set()):
            self._rooms[room_id].remove(user_id)
            if not self._rooms[room_id]:
                del self._rooms[room_id]
        self._user_room.pop(user_id, None)
        self._user_info.pop(user_id, None)
        self.notify('user_left', {'user_id': user_id, 'room_id': room_id})

    def handle_call_event(self, event_type: str, data: dict):
        """Handle call-related events (e.g., incoming, connected, disconnected)."""
        self.notify(event_type, data)

    def get_users_in_room(self, room_id: str) -> Set[str]:
        """Get the list of users in a room."""
        return self._rooms.get(room_id, set())

    def get_room_of_user(self, user_id: str) -> Optional[str]:
        """Get the room ID of a user."""
        return self._user_room.get(user_id)

    def get_user_info(self, user_id: str) -> Optional[dict]:
        """Get the information of a user."""
        return self._user_info.get(user_id)

    def register_websocket(self, session_id: str, websocket: Any):
        """Register a WebSocket for a session.""" 
        self._session_websockets[session_id] = websocket

    def unregister_websocket(self, session_id: str):
        """Remove a WebSocket mapping for a session."""
        self._session_websockets.pop(session_id, None)

    def map_connection_to_session(self, call_connection_id: str, session_id: str):
        """Associate a call connection ID with a session ID."""
        self._connection_session[call_connection_id] = session_id

    def get_websocket_for_connection(self, call_connection_id: str):
        """Retrieve the WebSocket for a given call connection ID."""
        session_id = self._connection_session.get(call_connection_id)
        if session_id:
            return self._session_websockets.get(session_id)
        return None

    async def handle_incoming_call(self, event_dict):
        """Handles EventGrid events for ACS incoming calls using the ACS SDK."""
        event = EventGridEvent.from_dict(event_dict)
        if event.event_type == SystemEventNames.EventGridSubscriptionValidationEventName:
            return self._handle_subscription_validation(event)
        elif event.event_type == SystemEventNames.AcsIncomingCallEventName:
            return await self._handle_acs_incoming_call(event)
        else:
            self.notify('incoming_call_unhandled', {"event": event_dict})
            return None

    def _handle_subscription_validation(self, event):
        """Handle EventGrid subscription validation event."""
        validation_code = event.data["validationCode"]
        return {"validationResponse": validation_code}

    async def _handle_acs_incoming_call(self, event):
        """Handle ACS incoming call event."""
        caller_id = (
            event.data["from"]["phoneNumber"]["value"]
            if event.data["from"]["kind"] == "phoneNumber"
            else event.data["from"]["rawId"]
        )
        incoming_call_context = event.data["incomingCallContext"]
        guid = uuid.uuid4()
        callback_uri, websocket_url = self._build_callback_uris(caller_id, guid)
        if not self.acs_client:
            raise RuntimeError("ACS client not initialized. Set AZURE_COMMUNICATION_CONNECTION_STRING.")
        try:
            # If your ACS resource or SDK requires a bot_id, add it here. Otherwise, omit it.
            media_streaming_options = MediaStreamingOptions(
                transport_url=websocket_url,
                transport_type="WebSocket",
                content_type="audio",
                audio_channel_type="mixed",
                start_media_streaming=True,
                enable_bidirectional=True,
                audio_format="pcm16_24khz_mono"
            )  #type: ignore
            answer_call_result = self.acs_client.answer_call(
                incoming_call_context=incoming_call_context,
                operation_context="incomingCall",
                callback_url=callback_uri,
                media_streaming=media_streaming_options,
            )
        except Exception as e:
            logging.error(f"Failed to answer ACS call: {e}")
            raise
        self._call_connections[str(guid)] = {
            "caller_id": caller_id,
            "context": incoming_call_context,
            "callback_uri": callback_uri,
            "websocket_url": websocket_url,
            "call_connection_id": answer_call_result.call_connection_id,
        }
        self.notify('incoming_call', {"caller_id": caller_id, "guid": str(guid), "call_connection_id": answer_call_result.call_connection_id})
        return {
            "callback_uri": callback_uri,
            "websocket_url": websocket_url,
            "guid": str(guid),
            "call_connection_id": answer_call_result.call_connection_id,
        }

    def _build_callback_uris(self, caller_id, guid):
        """Build callback and websocket URIs for ACS call answer."""
        query_parameters = urlencode({"callerId": caller_id})
        callback_uri = f"{os.environ.get('CALLBACK_EVENTS_URI')}/{guid}?{query_parameters}"
        parsed_url = urlparse(os.environ.get('CALLBACK_EVENTS_URI'))
        websocket_url = urlunparse(("wss", str(parsed_url.netloc), "/ws", "", "", ""))
        return callback_uri, websocket_url

    async def handle_callback_event(self, event):
        """Handles callbacks from ACS (CallConnected, MediaStreamingStarted, etc). Triggers translation command on CallConnected."""
        event_data = event["data"]
        call_connection_id = event_data.get("callConnectionId")
        event_type = event["type"]
        if event_type == "Microsoft.Communication.CallConnected":
            await self._handle_call_connected(event_data, call_connection_id)
        elif event_type == "Microsoft.Communication.MediaStreamingStarted":
            await self._handle_media_streaming_started(event_data, call_connection_id)
        elif event_type == "Microsoft.Communication.MediaStreamingStopped":
            await self._handle_media_streaming_stopped(event_data, call_connection_id)
        elif event_type == "Microsoft.Communication.MediaStreamingFailed":
            await self._handle_media_streaming_failed(event_data, call_connection_id)
        else:
            self._handle_callback_event_default(event_type, event_data, call_connection_id)
        self.notify('callback_event', {"type": event_type, "call_connection_id": call_connection_id, "data": event_data})
        return {"call_connection_id": call_connection_id, "type": event_type}

    async def _handle_call_connected(self, event_data, call_connection_id):
        if self.acs_client and call_connection_id:
            try:
                call_connection = self.acs_client.get_call_connection(call_connection_id)
                call_properties = call_connection.get_call_properties()
                media_streaming_subscription = getattr(call_properties, "media_streaming_subscription", None)
                self._call_connections[call_connection_id] = {
                    **event_data,
                    "media_streaming_subscription": media_streaming_subscription,
                }
                # Add bot as participant if bot info is available for this call/room
                bot_info = self._call_connections.get(event_data.get('roomId') or event_data.get('room_id'))
                if bot_info and bot_info.get('bot_identifier'):
                    logging.info(
                        "Adding bot '%s' as participant to ACS call (call_connection_id=%s)",
                        bot_info.get('bot_display_name', 'Bot'),
                        call_connection_id
                    )
                    try:
                        add_result = call_connection.add_participant(target_participant=bot_info['bot_identifier'])
                        logging.info(f"Bot add_participant result: {add_result}")
                    except Exception as e:
                        logging.error(f"Failed to add bot as participant: {e}")
                from orchestrator.engine.client import TranslateCommand, Invoker
                ws = self.get_websocket_for_connection(call_connection_id)
                if ws:
                    command = TranslateCommand(ws)
                    invoker = Invoker(command, create_response=True)
                    asyncio.create_task(self._start_translation(invoker))
            except Exception as e:
                logging.error(f"Failed to get call properties for {call_connection_id}: {e}")

    async def _handle_media_streaming_started(self, event_data, call_connection_id):
        # Placeholder for handling MediaStreamingStarted event
        self._call_connections[call_connection_id] = event_data

    async def _handle_media_streaming_stopped(self, event_data, call_connection_id):
        # Placeholder for handling MediaStreamingStopped event
        self._call_connections[call_connection_id] = event_data

    async def _handle_media_streaming_failed(self, event_data, call_connection_id):
        # Placeholder for handling MediaStreamingFailed event
        self._call_connections[call_connection_id] = event_data

    def _handle_callback_event_default(self, event_type, event_data, call_connection_id):
        if call_connection_id:
            self._call_connections[call_connection_id] = event_data

    async def _start_translation(self, invoker):
        """Start translation session using the provided invoker."""
        async with invoker as cmd:
            await asyncio.sleep(0)

    async def handle_incoming_audio(self, user_id: str, room_id: str, audio_b64: str, meta: dict):
        """
        Handle incoming audio from a user, interpret it with the client module, and distribute the result.
        Args:
            user_id (str): The user sending the audio.
            room_id (str): The room the user is in.
            audio_b64 (str): The base64-encoded audio data.
            meta (dict): Additional metadata (e.g., language, timestamp).
        """
        call_connection_id = str(meta.get('call_connection_id', ''))
        if not call_connection_id:
            logging.warning(f"No call_connection_id provided in meta for user {user_id} in room {room_id}")
            return
        ws = self.get_websocket_for_connection(call_connection_id)
        if not ws:
            logging.warning(f"No websocket found for user {user_id} in room {room_id}")
            return
        from orchestrator.engine.client import TranslateCommand, Invoker
        command = TranslateCommand(ws)
        # Use user's preferred language from meta or default
        entry_language = meta.get('language', 'en')
        exit_language = meta.get('target_language', 'zh')
        command.configure(entry_language=entry_language, exit_language=exit_language)
        invoker = Invoker(command, create_response=True)

        audio_bytes = base64.b64decode(audio_b64)
        async with invoker as cmd:
            await command.send_audio_from_acs(audio_bytes, meta)
            # Optionally, handle the response/streaming events here

    def join_bot_to_acs_call(self, room_id: str, bot_info: dict):
        """
        Prepare the bot to join the ACS call for the given room. The bot will be added as a participant after the call is established (in _handle_call_connected).
        """
        if not self.acs_client:
            logging.error("ACS client not initialized. Cannot join bot to ACS call.")
            raise RuntimeError("ACS client not initialized. Set AZURE_COMMUNICATION_CONNECTION_STRING.")

        # Always create a new ACS user for the bot (stateless, safe for demo)
        bot_user = self.identity_client.create_user()
        bot_identifier = CommunicationUserIdentifier(bot_user.properties['id'])

        # Store bot info for later use in _handle_call_connected
        self._call_connections[room_id] = {
            "bot_identifier": bot_identifier,
            "bot_display_name": bot_info.get('display_name', 'Bot'),
            "room_id": room_id
        }
        logging.info(f"Bot info stored for room {room_id}, will add after call is established.")

        # Optionally, you may want to trigger the call connection here if not already done
        # (If connect_call is needed, ensure it is only called once per room/call)


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
        print(f"[LoggingObserver] Event: {event.event_type}, User: {event.user_id}, Room: {event.room_id}, Data: {event.data}")
