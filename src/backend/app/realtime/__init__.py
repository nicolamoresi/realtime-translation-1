"""
Azure Real-time Translation
==========================

A modular implementation for real-time translation services using Azure OpenAI.

This package provides components for:
- WebSocket communication with Azure OpenAI Realtime API
- Audio processing and format conversions
- Event-based communication architecture
- Conversation state management
- Multi-peer room coordination
"""

from .audio_utils import (
    float_to_16bit_pcm,
    base64_to_array_buffer,
    array_buffer_to_base64,
    merge_int16_arrays,
    ensure_pcm16le_24khz
)
from .event_system import RealtimeEventHandler
from .api import RealtimeAPI
from .conversation import RealtimeConversation
from .client import RealtimeClient
from .room import RealtimeRoom

__all__ = [
    # Audio utilities
    "float_to_16bit_pcm",
    "base64_to_array_buffer",
    "array_buffer_to_base64",
    "merge_int16_arrays",
    "ensure_pcm16le_24khz",
    # Classes
    "RealtimeEventHandler",
    "RealtimeAPI",
    "RealtimeConversation",
    "RealtimeClient",
    "RealtimeRoom",
]