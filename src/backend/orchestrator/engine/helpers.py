from urllib.parse import urlencode, urlparse, urlunparse

from azure.communication.callautomation.aio import CallAutomationClient
from typing import Dict, Set, Optional



class ParticipantAudioController:
    """Controls muting/unmuting of participants in an ACS call using Call Automation SDK."""
    def __init__(self, acs_client: CallAutomationClient):
        self.acs_client = acs_client

    async def mute_participant(self, call_connection_id: str, participant_id: str):
        call_connection = self.acs_client.get_call_connection(call_connection_id)
        call_properties = await call_connection.get_call_properties()
        # Try to get participants from 'targets' or fallback to event tracking
        participants = getattr(call_properties, 'targets', None)
        if not participants:
            raise RuntimeError("Could not retrieve participants from call properties. Ensure you are tracking participant identifiers from ACS events.")
        identifier = self._find_participant_identifier(participants, participant_id)
        if identifier:
            await call_connection.mute_participant(identifier)
        else:
            raise ValueError(f"Participant with id {participant_id} not found in call participants.")

    def _find_participant_identifier(self, participants, participant_id: str):
        # participants is a list of CommunicationIdentifier objects
        for p in participants:
            if hasattr(p, 'raw_id') and p.raw_id == participant_id:
                return p
        return None

    async def mute_all_except(self, call_connection_id: str, except_participant_id: str, participants: Set[str]):
        for pid in participants:
            if pid != except_participant_id:
                await self.mute_participant(call_connection_id, pid)

    async def unmute_all(self, call_connection_id: str, participants: Set[str]):
        # ACS Call Automation SDK does not support unmuting participants programmatically.
        # You may notify users to unmute themselves or use ACS events to request unmute.
        pass


class UserTranslationSession:
    """Tracks per-user translation session state."""
    def __init__(self, user_id: str, room_id: str):
        self.user_id = user_id
        self.room_id = room_id
        self.active = True
        self.last_activity = None  # Timestamp of last activity
        self.translation_language = ""

    def update_activity(self, timestamp):
        self.last_activity = timestamp

    def set_language(self, language: str):
        self.translation_language = language

    def end(self):
        self.active = False


class TranslationSessionManager:
    """Manages all active translation sessions per user."""
    def __init__(self):
        self.sessions: Dict[str, UserTranslationSession] = {}

    def start_session(self, user_id: str, room_id: str, language: str = ""):
        session = UserTranslationSession(user_id, room_id)
        if language:
            session.set_language(language)
        self.sessions[user_id] = session
        return session

    def get_session(self, user_id: str) -> Optional[UserTranslationSession]:
        return self.sessions.get(user_id)

    def end_session(self, user_id: str):
        session = self.sessions.get(user_id)
        if session:
            session.end()
            del self.sessions[user_id]


class BotAudioDistributor:
    """Handles routing of translated audio to users (placeholder for actual implementation)."""
    def __init__(self):
        pass

    async def send_audio(self, user_id: str, audio_data: bytes):
        # Implement actual audio routing logic here (e.g., via WebSocket)
        pass


class BotSpeechCoordinator:
    """Coordinates bot speech events and manages muting/unmuting of users."""
    def __init__(self, audio_controller: ParticipantAudioController, session_manager: TranslationSessionManager):
        self.audio_controller = audio_controller
        self.session_manager = session_manager
        self.bot_id = None  # Set this to the bot's participant ID

    async def on_bot_speaking(self, call_connection_id: str, participants: Set[str]):
        # Mute all users except the bot
        if self.bot_id:
            await self.audio_controller.mute_all_except(call_connection_id, self.bot_id, participants)

    async def on_bot_stopped_speaking(self, call_connection_id: str, participants: Set[str]):
        # Unmuting is not supported by ACS Call Automation SDK; notify users to unmute themselves if needed.
        await self.audio_controller.unmute_all(call_connection_id, participants)

    def set_bot_id(self, bot_id: str):
        self.bot_id = bot_id

    def is_user_speaking(self, event_data: dict, user_id: str) -> bool:
        # Placeholder: Implement logic to check if user is speaking from ACS callback event data
        # For example, check event_data['activeSpeakerId'] == user_id
        return event_data.get('activeSpeakerId') == user_id
