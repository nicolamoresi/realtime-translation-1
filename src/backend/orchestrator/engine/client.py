"""
Orchestrator client module.

Defines abstractions for Azure OpenAI real-time translation commands
and an Invoker context manager to run those commands through the
AzureRealtimeWebsocket, forwarding audio data between ACS and Azure AI.
"""

import os
import base64
import logging

from abc import ABC, abstractmethod
from typing import Optional, Any
from string import Template

from dotenv import find_dotenv, load_dotenv
from numpy import ndarray

from fastapi import WebSocket

from semantic_kernel import Kernel
from semantic_kernel.connectors.ai import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai import (
    AzureRealtimeExecutionSettings,
    AzureRealtimeWebsocket,
)
from semantic_kernel.connectors.ai.realtime_client_base import RealtimeClientBase
from semantic_kernel.contents import AudioContent, RealtimeAudioEvent


# Configure logging
logger = logging.getLogger(__name__)
load_dotenv(find_dotenv())


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


class AOAITranslationClient(ABC):
    """Abstract base for Azure OpenAI real-time translation clients.

    Manages configuration, environment validation, and exposes the
    underlying AzureRealtimeWebsocket as an async context manager.
    """

    def __init__(self, ws: WebSocket):
        """Initialize the translation client with default settings."""
        self.kernel = Kernel()
        self._raw_ws = AzureRealtimeWebsocket(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-01-preview"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", "")
        )

        self.create_response: bool   = False
        self.available = self._check_configuration()
        self.ws: WebSocket = ws

        self.settings: AzureRealtimeExecutionSettings

    async def __call__(
        self,
        settings: AzureRealtimeExecutionSettings,
        create_response: bool = True,
        kernel: Optional[Kernel] = None
    ):
        """Prepare and return the AzureRealtimeWebsocket context manager.

        Args:
            settings: Execution settings including prompts and audio formats.
            create_response: Whether to request an immediate response.
            kernel: Optional Semantic Kernel instance.

        Returns:
            An async context manager for AzureRealtimeWebsocket.
        """
        self.settings = settings
        self.create_response = create_response
        if kernel:
            self.kernel = kernel

        # THIS returns an async context manager that will
        # call __aenter__ / __aexit__ on the AzureRealtimeWebsocket
        return self._raw_ws(
            settings=settings,
            create_response=create_response,
            kernel=self.kernel
        )

    def _check_configuration(self) -> bool:
        """Verify required environment variables are set.

        Returns:
            True if configuration is valid; False otherwise.
        """
        required_vars = ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"]
        missing = [var for var in required_vars if not os.getenv(var)]

        if missing:
            logger.warning(f"Azure OpenAI client missing configuration: {', '.join(missing)}")
            return False

        return True

    @abstractmethod
    def configure(self) -> None:
        """Configure client settings before invocation.

        Must set self.settings to a valid AzureRealtimeExecutionSettings.
        """
        pass


class TranslateCommand(AOAITranslationClient):
    """Concrete translation command for bidirectional language interpretation."""

    def configure(self, entry_language: str, exit_language: str) -> None:
        """Configure the translation prompt and audio settings.

        Args:
            entry_language: Language code of the source audio.
            exit_language: Language code for the translated output.

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
        raise ValueError("Client not properly configured. Please check your environment variables.")


class Invoker:
    """
    The Invoker is associated with one or several commands. It sends a request
    to the command.
    """

    def __init__(
        self,
        command: AOAITranslationClient,
        create_response: bool = True,
        kernel: Optional[Kernel] = None
    ):
        """Initialize the invoker with a command and kernel.

        Args:
            command: A configured AOAITranslationClient subclass.
            kernel: Semantic Kernel instance for function calls.
            create_response: Whether to request immediate AI response.
        """
        self.command = command
        self.kernel = kernel
        self.create_response = create_response

    async def __aenter__(self):
        """Enter context: configure command and open websocket."""
        self.command.configure()
        await self.command(
            settings=self.command.settings,
            create_response=self.create_response,
            kernel=self.kernel,
        )
        return self.command

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit context: cleanly close the websocket connection."""
        if self.command:
            await self.command._raw_ws.__aexit__(exc_type, exc_val, exc_tb)

    async def _from_realtime_to_acs(self, audio: ndarray):
        """Forward model-generated audio to ACS via WebSocket.

        Args:
            audio: PCM audio samples from the model.
        """
        logger.debug("Audio received from the model, sending to ACS client")
        await self.command.ws.send(
            {
                "kind": "AudioData",
                "audioData": {
                    "data": base64.b64encode(audio.tobytes()).decode("utf-8")
                }
            }
        )

    async def _from_acs_to_realtime(self, client: RealtimeClientBase):
        """Inward model-generated audio to AzureOpenAI via WebSocket.

        Args:
            client: A realtime sk client that implements the integration.
        """
        try:
            data = await self.command.ws.receive()
            while data:
                if data.get("kind", None) == "AudioData":
                    # send it to the Realtime service
                    await client.send(
                        event=RealtimeAudioEvent(
                            audio=AudioContent(
                                data=data.get("audioData", {}).get("data"), data_format="base64", inner_content=data),
                        )
                    )
        except Exception:
            logger.info("Websocket connection closed.")
