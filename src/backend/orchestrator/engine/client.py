"""
Client and command abstractions for Azure OpenAI real-time translation.

This module defines the AOAITranslationClient base class, the TranslateCommand for translation logic, and the Invoker context manager for orchestrating translation sessions and audio forwarding between ACS and Azure OpenAI.
"""

import os
import json
import base64
from datetime import datetime
import time

from abc import ABC, abstractmethod
from typing import Optional
from string import Template

from numpy import ndarray

from fastapi import WebSocket

from semantic_kernel import Kernel
from semantic_kernel.connectors.ai import FunctionChoiceBehavior
from semantic_kernel.contents import AudioContent, RealtimeAudioEvent, RealtimeTextEvent
from semantic_kernel.connectors.ai.open_ai import AzureRealtimeExecutionSettings, AzureRealtimeWebsocket
from semantic_kernel.connectors.ai.open_ai.services._open_ai_realtime import ListenEvents

from orchestrator import logger



INTERPRETER_PROMPT = Template("""
You are an interpreter who can help people who speak different languages interact with chinese-speaking people.
Your sole function is to translate the input from the user accurately and with proper grammar, maintaining the original meaning and tone of the message.

Whenever the user speaks in {{entry_language}}, you will translate it to {{exit_language}}.

Act like an interpreter, DO NOT add, omit, or alter any information.

DO NOT provide explanations, opinions, or any additional text beyond the direct translation.
DO NOT respond to the speakers' questions or asks and DO NOT add your own thoughts. You only need to translate the audio input coming from the two speakers.
You are not aware of any other facts, knowledge, or context beyond the audio input you are translating.
Wait until the speaker is done speaking before you start translating, and translate the entire audio inputs in one go. If the speaker is providing a series of instructions, wait until the end of the instructions before translating.

# Notes
- Handle technical terms literally if no equivalent exists.
- In cases of unclear audio, indicate uncertainty: "[unclear: possible interpretation]".
- ONLY RESPOND WITH THE TRANSLATED TEXT. DO NOT ADD ANY OTHER TEXT, EXPLANATIONS, OR CONTEXTUAL INFORMATION.
""")

AZURE_OPENAI_API_KEY=os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_API_VERSION=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-01-preview")
AZURE_OPENAI_ENDPOINT=os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_DEPLOYMENT=os.getenv("AZURE_OPENAI_DEPLOYMENT", "")


class AOAITranslationClient(ABC):
    """Abstract base for Azure OpenAI real-time translation clients.

    Manages configuration, environment validation, and exposes the
    underlying AzureRealtimeWebsocket as an async context manager.
    """

    def __init__(self, observer=None):
        """
        Args:
            ws (WebSocket): The FastAPI WebSocket connection.
            observer (Optional[Any]): Optional observer/handler for events.
        """
        self.kernel = Kernel()
        self._raw_ws = AzureRealtimeWebsocket(
            api_key=AZURE_OPENAI_API_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            deployment_name=AZURE_OPENAI_DEPLOYMENT
        )
        self.create_response: bool = False
        self.available = self._check_configuration()
        self._websocket: WebSocket
        self.settings: AzureRealtimeExecutionSettings
        self.observer = observer

    def __call__(
        self,
        create_response: bool = True
    ):
        """Prepare and return the AzureRealtimeWebsocket context manager.

        Args:
            settings (AzureRealtimeExecutionSettings): Execution settings including prompts and audio formats.
            create_response (bool): Whether to request an immediate response.
            kernel (Optional[Kernel]): Optional Semantic Kernel instance.

        Returns:
            An async context manager for AzureRealtimeWebsocket.
        """
        self.create_response = create_response
        self._raw_ws(
            settings=self.settings,
            kernel=self.kernel,
            create_response=create_response
        )

    async def _receive_events(self, audio_output_callback=None):
        """Async generator for model events, with optional audio callback."""
        async for event in self._raw_ws.receive(audio_output_callback=audio_output_callback):
            if self.observer:
                await self.observer.handle_event(event)
            yield event

    @property
    def ws(self) -> WebSocket:
        return self._websocket

    @ws.setter
    def ws(self, websocket: WebSocket):
        self._websocket = websocket

    def _check_configuration(self) -> bool:
        """Verify required environment variables are set and log their values for debugging."""
        required_vars = [
            ("AZURE_OPENAI_API_KEY", AZURE_OPENAI_API_KEY),
            ("AZURE_OPENAI_ENDPOINT", AZURE_OPENAI_ENDPOINT),
            ("AZURE_OPENAI_API_VERSION", AZURE_OPENAI_API_VERSION),
            ("AZURE_OPENAI_DEPLOYMENT", AZURE_OPENAI_DEPLOYMENT),
        ]
        missing = [var for var, val in required_vars if not val]
        for var, val in required_vars:
            logger.info(f"[AOAITranslationClient] {var}={'SET' if val else 'MISSING'}")
        if missing:
            logger.warning(f"[AOAITranslationClient] Azure OpenAI client missing configuration: {', '.join(missing)}")
            return False
        return True

    @abstractmethod
    def configure(self) -> None:
        """Configure client settings before invocation.

        Must set self.settings to a valid AzureRealtimeExecutionSettings.
        """

    @abstractmethod
    async def handle_realtime_messages(self):
        """Handle real-time messages from the model and forward them to ACS.

        This method should be implemented to process incoming audio data and
        send it to the Azure Communication Services (ACS) client.
        """

    @abstractmethod
    async def _from_realtime_to_acs(self):
        """Configure client settings before invocation.

        Must set self.settings to a valid AzureRealtimeExecutionSettings.
        """

    @abstractmethod
    async def _from_acs_to_realtime(self):
        """Configure client settings before invocation.

        Must set self.settings to a valid AzureRealtimeExecutionSettings.
        """


class TranslateCommand(AOAITranslationClient):
    """Concrete translation command for bidirectional language interpretation.

    Methods:
        configure(entry_language, exit_language): Set up translation prompt and audio settings.
    """

    def configure(self, entry_language: str, exit_language: str) -> None:
        """Configure the translation prompt and audio settings.

        Args:
            entry_language (str): Language code of the source audio.
            exit_language (str): Language code for the translated output.

        Raises:
            ValueError: If environment variables are missing.
        """
        if self.available:
            self.settings = AzureRealtimeExecutionSettings(
                instructions=INTERPRETER_PROMPT.safe_substitute(
                    entry_language=entry_language,
                    exit_language=exit_language
                ).strip(),
                turn_detection={"type": "server_vad"},
                voice="shimmer",
                input_audio_format="pcm16",
                output_audio_format="pcm16",
                input_audio_transcription={"model": "whisper-1"},
                function_choice_behavior=FunctionChoiceBehavior.Auto(),
            )

    async def _from_realtime_to_acs(self, audio: ndarray):
        logger.debug("Audio received from the model, sending to ACS client")
        try:
            await self.ws.send_json(
                {"Kind": "AudioData", "AudioData": {"data": base64.b64encode(audio.tobytes()).decode("utf-8")}}
            )
        except Exception as e:
            logger.error(f"[TranslateCommand] Error sending audio to ACS: {e}")

    async def handle_realtime_messages(self):
        """Forward model-generated audio to ACS via WebSocket, optimized for low latency and with detailed logging."""
        logger.info("[TranslateCommand] Starting _from_realtime_to_acs audio streaming loop.")
        try:
            async for event in self._raw_ws.receive(audio_output_callback=self._from_realtime_to_acs):
                match event.service_type:
                    case ListenEvents.SESSION_CREATED:
                        logger.info("Session Created Message")
                        logger.debug(f"  Session Id: {event.service_event.session.id}")  #type: ignore
                    case ListenEvents.ERROR:
                        logger.error(f"  Error: {event.service_event.error}")  #type: ignore
                    case ListenEvents.INPUT_AUDIO_BUFFER_CLEARED:
                        logger.info("[TranslateCommand] Input audio buffer cleared.")
                    case ListenEvents.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
                        logger.debug(f"Voice activity detection started at {event.service_event.audio_start_ms} [ms]")  #type: ignore
                        await self.ws.send_json({"Kind": "StopAudio", "AudioData": None, "StopAudio": {}})
                    case ListenEvents.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
                        logger.info(f" User:-- {event.service_event.transcript}")  #type: ignore
                    case ListenEvents.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_FAILED:
                        logger.error(f"  Error: {event.service_event.error}")  #type: ignore
                    case ListenEvents.RESPONSE_DONE:
                        logger.info("Response Done Message")
                        logger.debug(f"  Response Id: {event.service_event.response.id}")  #type: ignore
                        if event.service_event.response.status_details:  #type: ignore
                            logger.debug(
                                f"  Status Details: {event.service_event.response.status_details.model_dump_json()}"  #type: ignore
                            )
                    case ListenEvents.RESPONSE_AUDIO_TRANSCRIPT_DONE:
                        logger.info(f" AI:-- {event.service_event.transcript}")  #type: ignore
                    case _:
                        logger.warning(f"[TranslateCommand] Received unexpected event type: {type(event)}")
        except Exception as exc:
            logger.error(f"[TranslateCommand] Exception in _from_realtime_to_acs: {exc}")
            raise
        logger.info("[TranslateCommand] Exiting _from_realtime_to_acs audio streaming loop.")

    async def _from_acs_to_realtime(self):
        """Forward audio coming in from ACS (binary frames) into the Azure OpenAI websocket."""
        while True:
            try:
                msg = await self.ws.receive_json()
                setattr(self.ws, "last_activity", time.time())
                if msg.get("text"):
                    try:
                        if msg["text"].strip().startswith("{"):
                            payload = json.loads(msg["text"])
                        else:
                            logger.warning("[TranslateCommand] Received text frame that does not look like JSON, skipping.")
                            continue
                    except Exception as e:
                        logger.error(f"[TranslateCommand] Error decoding JSON from ACS: {str(e)}")
                        continue
                else:
                    payload = msg
                    if payload.get("kind") == "AudioMetadata":
                        continue
                    if payload.get("kind") == "AudioData":
                        await self._raw_ws.send(
                            event=RealtimeAudioEvent(
                                audio=AudioContent(
                                    data=payload["audioData"]["data"],
                                    data_format="base64",
                                    inner_content=msg.get("text")
                                )
                            )
                        )
                        continue
            except Exception as e:
                logger.info(f"[TranslateCommand] WebSocket connection closed or error: {e}")
                break
            logger.info("[TranslateCommand] Exiting _from_acs_to_realtime audio streaming loop.")

class Invoker:
    """Invoker context manager for running translation commands.

    Orchestrates the execution of AOAITranslationClient commands, manages context, and provides methods for audio forwarding between ACS and Azure OpenAI.

    Methods:
        __aenter__(): Enter context, configure and open websocket.
        __aexit__(): Exit context, close websocket.
        _from_realtime_to_acs(audio): Forward audio to ACS.
        _from_acs_to_realtime(client): Forward audio to Azure OpenAI.
    """

    def __init__(
        self,
        command: AOAITranslationClient,
        create_response: bool = True,
        kernel: Optional[Kernel] = None
    ):
        """Initialize the invoker with a command and kernel.

        Args:
            command (AOAITranslationClient): A configured AOAITranslationClient subclass.
            kernel (Optional[Kernel]): Semantic Kernel instance for function calls.
            create_response (bool): Whether to request immediate AI response.
        """
        self.command = command
        self.kernel = kernel
        self.create_response = create_response

    async def __aenter__(self):
        """Enter context: configure command and open websocket."""
        self.command(create_response=self.create_response)
        await self.command._raw_ws.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context: cleanly close the websocket connection."""
        if self.command:
            await self.command._raw_ws.__aexit__(exc_type, exc_val, exc_tb)

    async def start(self) -> None:
        await self.command.ws.accept()

    async def open_if_closed(self):
        """Re-open the websocket connection if it is closed. Safe to call before sending/receiving new data."""
        ws = getattr(self.command, "_raw_ws", None)
        if ws is None:
            logger.warning("[Invoker] No _raw_ws found on command; cannot check connection state.")
            return
        # Check if the websocket is closed (assume _raw_ws has an 'closed' or 'is_closed' property, fallback to context manager state)
        is_closed = getattr(ws, "closed", None)
        if is_closed is None:
            # Fallback: try to check if context manager has exited
            is_closed = getattr(ws, "_closed", False)
        if is_closed:
            logger.info("[Invoker] Websocket is closed, re-opening via __aenter__.")
            await ws.__aenter__()
        else:
            logger.debug("[Invoker] Websocket is already open; no action taken.")
