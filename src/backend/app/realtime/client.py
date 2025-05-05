"""
High-level client for Azure real-time translation services.

Provides a convenient API for applications to interact with the Azure OpenAI
Realtime API, handling configuration, state management, and tool integration.
"""

import asyncio
import json
import logging
import traceback
from datetime import datetime
from typing import Any, Callable, Optional, Union

import numpy as np

from .api import RealtimeAPI
from .audio_utils import array_buffer_to_base64
from .conversation import RealtimeConversation
from .event_system import RealtimeEventHandler

logger = logging.getLogger(__name__)


class RealtimeClient(RealtimeEventHandler):
    """
    High-level client for Azure real-time translation services.
    
    Combines a RealtimeAPI instance with a RealtimeConversation to provide
    a complete solution for real-time communication with the Azure OpenAI Realtime API.
    """
    
    def __init__(self, system_prompt: str) -> None:
        """
        Initialize a new real-time client.
        
        Args:
            system_prompt: System instructions for the conversation
        """
        super().__init__()
        self.system_prompt = system_prompt
        self.default_session_config = {
            "modalities": ["text", "audio"],
            "instructions": self.system_prompt,
            "voice": "shimmer",
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_transcription": { "model": 'whisper-1' },
            "turn_detection": { "type": 'server_vad' },
            "tools": [],
            "tool_choice": "auto",
            "temperature": 0.6,
            "max_response_output_tokens": 4096,
        }
        self.session_config: dict[str, Any] = {}
        self.transcription_models = [{"model": "whisper-1"}]
        self.default_server_vad_config = {
            "type": "server_vad",
            "threshold": 0.9,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 500,
        }
        self.realtime = RealtimeAPI()
        self.conversation = RealtimeConversation()
        self._reset_config()
        self._add_api_event_handlers()
    
    # Initialization helpers
    
    def _reset_config(self) -> bool:
        """Reset client configuration to defaults."""
        self.session_created = False
        self.tools: dict[str, dict] = {}
        self.session_config = self.default_session_config.copy()
        self.input_audio_buffer = bytearray()
        return True

    def _add_api_event_handlers(self) -> None:
        """Register event handlers for API events."""
        self.realtime.on("client.*", self._log_event)
        self.realtime.on("server.*", self._log_event)
        self.realtime.on("server.session.created", self._on_session_created)
        self.realtime.on("server.response.created", self._process_event)
        self.realtime.on("server.response.output_item.added", self._process_event)
        self.realtime.on("server.response.content_part.added", self._process_event)
        self.realtime.on("server.input_audio_buffer.speech_started", self._on_speech_started)
        self.realtime.on("server.input_audio_buffer.speech_stopped", self._on_speech_stopped)
        self.realtime.on("server.conversation.item.created", self._on_item_created)
        self.realtime.on("server.conversation.item.truncated", self._process_event)
        self.realtime.on("server.conversation.item.deleted", self._process_event)
        self.realtime.on("server.conversation.item.input_audio_transcription.completed", self._process_event)
        self.realtime.on("server.response.audio_transcript.delta", self._process_event)
        self.realtime.on("server.response.audio.delta", self._process_event)
        self.realtime.on("server.response.text.delta", self._process_event)
        self.realtime.on("server.response.function_call_arguments.delta", self._process_event)
        self.realtime.on("server.response.output_item.done", self._on_output_item_done)
    
    # Event handlers
    
    def _log_event(self, event: dict[str, Any]) -> None:
        """Log and relay API events."""
        realtime_event = {
            "time": datetime.now().isoformat(),
            "source": "client" if event["type"].startswith("client.") else "server",
            "event": event,
        }
        self.dispatch("realtime.event", realtime_event)

    def _on_session_created(self, event: dict[str, Any]) -> None:
        """Handle session creation events."""
        self.session_created = True

    def _process_event(self, event: dict[str, Any], *args) -> Any:
        """Process events through the conversation manager."""
        item, delta = self.conversation.process_event(event, *args)
        if event["type"] == "conversation.item.input_audio_transcription.completed":
            self.dispatch("conversation.item.input_audio_transcription.completed", {"item": item, "delta": delta})
        if item:
            self.dispatch("conversation.updated", {"item": item, "delta": delta})
        return item, delta

    def _on_speech_started(self, event: dict[str, Any]) -> None:
        """Handle speech start events."""
        self._process_event(event)
        self.dispatch("conversation.interrupted", event)

    def _on_speech_stopped(self, event: dict[str, Any]) -> None:
        """Handle speech stop events."""
        self._process_event(event, self.input_audio_buffer)

    def _on_item_created(self, event: dict[str, Any]) -> None:
        """Handle item creation events."""
        item, delta = self._process_event(event)
        self.dispatch("conversation.item.appended", {"item": item})
        if item and item["status"] == "completed":
            self.dispatch("conversation.item.completed", {"item": item})

    async def _on_output_item_done(self, event: dict[str, Any]) -> None:
        """Handle output item completion."""
        item, delta = self._process_event(event)
        if item and item["status"] == "completed":
            self.dispatch("conversation.item.completed", {"item": item})
        if item and item.get("formatted", {}).get("tool"):
            await self._call_tool(item["formatted"]["tool"])

    async def _call_tool(self, tool: dict[str, Any]) -> bool:
        """
        Execute a tool/function based on model request.
        
        Args:
            tool: Tool definition including name, arguments and call ID
            
        Returns:
            True if tool was executed
        """
        try:
            logger.info("Arguments: %s", str(tool["arguments"]))
            json_arguments = json.loads(tool["arguments"])
            tool_config = self.tools.get(tool["name"])
            
            if not tool_config:
                raise Exception(f'Tool "{tool["name"]}" has not been added')
                
            result = await tool_config["handler"](**json_arguments)
            await self.realtime.send("conversation.item.create", {
                "item": {
                    "type": "function_call_output",
                    "call_id": tool["call_id"],
                    "output": json.dumps(result),
                }
            })
        except Exception as e:
            logger.error(traceback.format_exc())
            await self.realtime.send("conversation.item.create", {
                "item": {
                    "type": "function_call_output",
                    "call_id": tool["call_id"],
                    "output": json.dumps({"error": str(e)}),
                }
            })
            
        await self.create_response()
        return True
    
    # Public API
    
    def is_connected(self) -> bool:
        """Check if connected to the Azure OpenAI Realtime API."""
        return self.realtime.is_connected()

    async def reset(self) -> bool:
        """Reset the client state and disconnect."""
        await self.disconnect()
        self.realtime.clear_event_handlers()
        self._reset_config()
        self._add_api_event_handlers()
        return True

    async def connect(self) -> bool:
        """
        Connect to the Azure OpenAI Realtime API.
        
        Raises:
            Exception: If already connected
        """
        if self.is_connected():
            raise Exception("Already connected, use .disconnect() first")
        await self.realtime.connect()
        await self.update_session()
        return True

    async def wait_for_session_created(self) -> bool:
        """
        Wait for session creation to complete.
        
        Raises:
            Exception: If not connected
        """
        if not self.is_connected():
            raise Exception("Not connected, use .connect() first")
        while not self.session_created:
            await asyncio.sleep(0.001)
        return True

    async def disconnect(self) -> None:
        """Disconnect from the Azure OpenAI Realtime API."""
        self.session_created = False
        self.conversation.clear()
        if self.realtime.is_connected():
            await self.realtime.disconnect()

    def get_turn_detection_type(self) -> Optional[str]:
        """Get the current turn detection type."""
        return self.session_config.get("turn_detection", {}).get("type")

    async def add_tool(self, definition: dict[str, Any], handler: Callable) -> dict[str, Any]:
        """
        Add a tool/function to the session.
        
        Args:
            definition: Tool definition
            handler: Function to execute when tool is called
            
        Returns:
            The added tool configuration
            
        Raises:
            Exception: If tool name is missing or already exists
        """
        if not definition.get("name"):
            raise Exception("Missing tool name in definition")
            
        name = definition["name"]
        if name in self.tools:
            raise Exception(f'Tool "{name}" already added. Please use .removeTool("{name}") before trying to add again.')
            
        if not callable(handler):
            raise Exception(f'Tool "{name}" handler must be a function')
            
        self.tools[name] = {"definition": definition, "handler": handler}
        await self.update_session()
        return self.tools[name]

    def remove_tool(self, name: str) -> bool:
        """
        Remove a tool/function from the session.
        
        Args:
            name: Tool name to remove
            
        Returns:
            True if successful
            
        Raises:
            Exception: If tool doesn't exist
        """
        if name not in self.tools:
            raise Exception(f'Tool "{name}" does not exist, can not be removed.')
        del self.tools[name]
        return True

    async def delete_item(self, item_id: str) -> bool:
        """
        Delete a conversation item.
        
        Args:
            item_id: Item ID to delete
            
        Returns:
            True if successful
        """
        await self.realtime.send("conversation.item.delete", {"item_id": item_id})
        return True

    async def update_session(self, **kwargs) -> bool:
        """
        Update session configuration.
        
        Args:
            **kwargs: Configuration parameters to update
            
        Returns:
            True if successful
        """
        self.session_config.update(kwargs)
        use_tools = [
            {**tool_definition, "type": "function"}
            for tool_definition in self.session_config.get("tools", [])
        ] + [
            {**self.tools[key]["definition"], "type": "function"}
            for key in self.tools
        ]
        session = {**self.session_config, "tools": use_tools}
        if self.realtime.is_connected():
            await self.realtime.send("session.update", {"session": session})
        return True
    
    async def create_conversation_item(self, item: dict[str, Any]) -> None:
        """
        Create a new conversation item.
        
        Args:
            item: Item definition
        """
        await self.realtime.send("conversation.item.create", {
            "item": item
        })

    async def send_user_message_content(self, content: list[dict[str, Any]] = []) -> bool:
        """
        Send a user message with optional content.

        Args:
            content: list of content items (text, audio, etc.)

        Returns:
            True if successful
        """
        if content:
            for c in content:
                if c["type"] == "input_audio":
                    if isinstance(c["audio"], (bytes, bytearray)):
                        c["audio"] = array_buffer_to_base64(c["audio"])
            await self.realtime.send("conversation.item.create", {
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": content,
                }
            })
        await self.create_response()
        return True

    async def append_input_audio(self, array_buffer: Union[bytes, bytearray, np.ndarray]) -> bool:
        """
        Append audio data to the input buffer.

        Args:
            array_buffer: Audio data

        Returns:
            True if successful
        """
        if len(array_buffer) > 0:
            await self.realtime.send("input_audio_buffer.append", {
                "audio": array_buffer_to_base64(np.array(array_buffer)),
            })
            self.input_audio_buffer.extend(array_buffer)
        return True

    async def create_response(self) -> bool:
        """
        Request a response from the model.

        Returns:
            True if successful
        """
        if self.get_turn_detection_type() is None and len(self.input_audio_buffer) > 0:
            await self.realtime.send("input_audio_buffer.commit")
            self.conversation.queue_input_audio(self.input_audio_buffer)
            self.input_audio_buffer = bytearray()
        await self.realtime.send("response.create")
        return True

    async def cancel_response(self, item_id: Optional[str] = None, sample_count: int = 0) -> dict[str, Any]:
        """
        Cancel an in-progress response.
        
        Args:
            item_id: Optional item ID to truncate
            sample_count: Sample count for truncation
            
        Returns:
            dict containing the affected item if applicable
            
        Raises:
            Exception: For invalid item or operation
        """
        if not item_id:
            await self.realtime.send("response.cancel")
            return {"item": None}
        else:
            item = self.conversation.get_item(item_id)
            if not item:
                raise Exception(f'Could not find item "{item_id}"')
            if item["type"] != "message":
                raise Exception('Can only cancelResponse messages with type "message"')
            if item["role"] != "assistant":
                raise Exception('Can only cancelResponse messages with role "assistant"')
                
            await self.realtime.send("response.cancel")
            audio_index = next((i for i, c in enumerate(item["content"]) if c["type"] == "audio"), -1)
            
            if audio_index == -1:
                raise Exception("Could not find audio on item to cancel")
                
            await self.realtime.send("conversation.item.truncate", {
                "item_id": item_id,
                "content_index": audio_index,
                "audio_end_ms": int((sample_count / self.conversation.default_frequency) * 1000),
            })
            return {"item": item}

    async def wait_for_next_item(self) -> dict[str, Any]:
        """
        Wait for the next item to be appended to the conversation.
        
        Returns:
            dict containing the new item
        """
        event = await self.wait_for_next("conversation.item.appended")
        return {"item": event["item"]}

    async def wait_for_next_completed_item(self) -> dict[str, Any]:
        """
        Wait for the next item to be completed.
        
        Returns:
            dict containing the completed item
        """
        event = await self.wait_for_next("conversation.item.completed")
        return {"item": event["item"]}
