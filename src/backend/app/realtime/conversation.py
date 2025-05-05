"""
Conversation state management for Azure real-time translation.

Maintains a coherent view of the conversation by processing events from
the Azure OpenAI Realtime API and aggregating them into a structured model.
"""

import logging
from typing import Any, Callable, Optional

import numpy as np

from .audio_utils import base64_to_array_buffer

logger = logging.getLogger(__name__)


class RealtimeConversation:
    """
    Manages conversation state based on events from the Azure OpenAI Realtime API.
    
    Processes incoming events to build a coherent view of the conversation,
    including messages, audio, transcriptions, and function calls.
    Following Azure best practices, this class:
    - Uses strong typing for all methods
    - Provides comprehensive error handling
    - Implements efficient state management
    - Follows Azure's event processing patterns
    """
    
    default_frequency = 24000  # 24 kHz PCM16
    
    # Define event processors as a class variable for better organization
    EventProcessors: dict[str, Callable] = {
        'conversation.item.created': lambda self, event: self._process_item_created(event),
        'conversation.item.truncated': lambda self, event: self._process_item_truncated(event),
        'conversation.item.deleted': lambda self, event: self._process_item_deleted(event),
        'conversation.item.input_audio_transcription.completed': lambda self, event: self._process_input_audio_transcription_completed(event),
        'input_audio_buffer.speech_started': lambda self, event: self._process_speech_started(event),
        'input_audio_buffer.speech_stopped': lambda self, event, input_audio_buffer: self._process_speech_stopped(event, input_audio_buffer),
        'response.created': lambda self, event: self._process_response_created(event),
        'response.output_item.added': lambda self, event: self._process_output_item_added(event),
        'response.output_item.done': lambda self, event: self._process_output_item_done(event),
        'response.content_part.added': lambda self, event: self._process_content_part_added(event),
        'response.audio_transcript.delta': lambda self, event: self._process_audio_transcript_delta(event),
        'response.audio.delta': lambda self, event: self._process_audio_delta(event),
        'response.text.delta': lambda self, event: self._process_text_delta(event),
        'response.function_call_arguments.delta': lambda self, event: self._process_function_call_arguments_delta(event),
    }
    
    def __init__(self) -> None:
        """Initialize an empty conversation state."""
        self.clear()

    def clear(self) -> None:
        """Reset all conversation state."""
        self.item_lookup: dict[str, dict] = {}
        self.items: list[dict] = []
        self.response_lookup: dict[str, dict] = {}
        self.responses: list[dict] = []
        self.queued_speech_items: dict[str, dict] = {}
        self.queued_transcript_items: dict[str, dict] = {}
        self.queued_input_audio: Optional[bytes] = None

    def queue_input_audio(self, input_audio: bytes) -> None:
        """
        Queue input audio to be associated with the next user message.
        
        Args:
            input_audio: Raw audio bytes
        """
        self.queued_input_audio = input_audio

    def process_event(self, event: dict[str, Any], *args) -> tuple[Optional[dict], Optional[dict]]:
        """
        Process an event from the Azure OpenAI Realtime API.
        
        Args:
            event: The event to process
            *args: Additional arguments for specific event types
            
        Returns:
            tuple of (updated_item, delta) if applicable
            
        Raises:
            Exception: If no processor exists for the event type
        """
        event_processor = self.EventProcessors.get(event['type'])
        if not event_processor:
            raise Exception(f"Missing conversation event processor for {event['type']}")
        return event_processor(self, event, *args)

    def get_item(self, item_id: str) -> Optional[dict]:
        """
        Get a conversation item by ID.
        
        Args:
            item_id: The item ID to retrieve
            
        Returns:
            The item if found, None otherwise
        """
        return self.item_lookup.get(item_id)

    def get_items(self) -> list[dict]:
        """
        Get all conversation items.
        
        Returns:
            Copy of all conversation items
        """
        return self.items[:]
    
    def _process_item_created(self, event: dict[str, Any]) -> tuple[dict, None]:
        """
        Process a conversation.item.created event.
        
        Updates the conversation with a new item, handling text, audio, and tool calls.
        
        Args:
            event: The item creation event
            
        Returns:
            tuple of (updated_item, None)
        """
        item = event['item']
        new_item = item.copy()
        
        if new_item['id'] not in self.item_lookup:
            self.item_lookup[new_item['id']] = new_item
            self.items.append(new_item)
            
        new_item['formatted'] = {
            'audio': [],
            'text': '',
            'transcript': ''
        }
        
        if new_item['id'] in self.queued_speech_items:
            new_item['formatted']['audio'] = self.queued_speech_items[new_item['id']]['audio']
            del self.queued_speech_items[new_item['id']]
            
        if 'content' in new_item:
            text_content = [c for c in new_item['content'] if c['type'] in ['text', 'input_text']]
            for content in text_content:
                new_item['formatted']['text'] += content['text']
                
        if new_item['id'] in self.queued_transcript_items:
            new_item['formatted']['transcript'] = self.queued_transcript_items[new_item['id']]['transcript']
            del self.queued_transcript_items[new_item['id']]
            
        if new_item['type'] == 'message':
            if new_item['role'] == 'user':
                new_item['status'] = 'completed'
                if self.queued_input_audio:
                    new_item['formatted']['audio'] = self.queued_input_audio
                    self.queued_input_audio = None
            else:
                new_item['status'] = 'in_progress'
        elif new_item['type'] == 'function_call':
            new_item['formatted']['tool'] = {
                'type': 'function',
                'name': new_item['name'],
                'call_id': new_item['call_id'],
                'arguments': ''
            }
            new_item['status'] = 'in_progress'
        elif new_item['type'] == 'function_call_output':
            new_item['status'] = 'completed'
            new_item['formatted']['output'] = new_item['output']
            
        return new_item, None

    def _process_item_truncated(self, event: dict[str, Any]) -> tuple[Optional[dict], None]:
        """
        Process a conversation.item.truncated event.
        
        Truncates the audio and transcript of an item at the specified point.
        
        Args:
            event: The truncation event
            
        Returns:
            tuple of (truncated_item, None)
            
        Raises:
            Exception: If the item to truncate is not found
        """
        item_id = event['item_id']
        audio_end_ms = event['audio_end_ms']
        
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'item.truncated: Item "{item_id}" not found')
            
        end_index = (audio_end_ms * self.default_frequency) // 1000
        item['formatted']['transcript'] = ''
        item['formatted']['audio'] = item['formatted']['audio'][:end_index]
        
        return item, None

    def _process_item_deleted(self, event: dict[str, Any]) -> tuple[Optional[dict], None]:
        """
        Process a conversation.item.deleted event.
        
        Removes an item from the conversation.
        
        Args:
            event: The deletion event
            
        Returns:
            tuple of (deleted_item, None)
            
        Raises:
            Exception: If the item to delete is not found
        """
        item_id = event['item_id']
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'item.deleted: Item "{item_id}" not found')
            
        del self.item_lookup[item['id']]
        self.items.remove(item)
        
        return item, None

    def _process_input_audio_transcription_completed(self, event: dict[str, Any]) -> tuple[Optional[dict], Optional[dict]]:
        """
        Process a conversation.item.input_audio_transcription.completed event.
        
        Updates an item with its completed audio transcription.
        
        Args:
            event: The transcription completed event
            
        Returns:
            tuple of (updated_item, delta) or (None, None) if item not found
        """
        item_id = event['item_id']
        content_index = event['content_index']
        transcript = event['transcript']
        formatted_transcript = transcript or ' '
        
        item = self.item_lookup.get(item_id)
        if not item:
            # Queue for later association
            self.queued_transcript_items[item_id] = {'transcript': formatted_transcript}
            return None, None
            
        item['content'][content_index]['transcript'] = transcript
        item['formatted']['transcript'] = formatted_transcript
        
        return item, {'transcript': transcript}

    def _process_speech_started(self, event: dict[str, Any]) -> tuple[None, None]:
        """
        Process an input_audio_buffer.speech_started event.
        
        Records when speech starts in an audio stream.
        
        Args:
            event: The speech started event
            
        Returns:
            tuple of (None, None)
        """
        item_id = event['item_id']
        audio_start_ms = event['audio_start_ms']
        
        self.queued_speech_items[item_id] = {'audio_start_ms': audio_start_ms}
        
        return None, None

    def _process_speech_stopped(self, event: dict[str, Any], input_audio_buffer: bytes) -> tuple[None, None]:
        """
        Process an input_audio_buffer.speech_stopped event.
        
        Records when speech stops and extracts the relevant audio segment.
        
        Args:
            event: The speech stopped event
            input_audio_buffer: The full audio buffer containing the speech
            
        Returns:
            tuple of (None, None)
        """
        item_id = event['item_id']
        audio_end_ms = event['audio_end_ms']
        
        speech = self.queued_speech_items[item_id]
        speech['audio_end_ms'] = audio_end_ms
        
        if input_audio_buffer:
            start_index = (speech['audio_start_ms'] * self.default_frequency) // 1000
            end_index = (speech['audio_end_ms'] * self.default_frequency) // 1000
            speech['audio'] = input_audio_buffer[start_index:end_index]
            
        return None, None

    def _process_response_created(self, event: dict[str, Any]) -> tuple[None, None]:
        """
        Process a response.created event.
        
        Adds a new response to the conversation.
        
        Args:
            event: The response created event
            
        Returns:
            tuple of (None, None)
        """
        response = event['response']
        
        if response['id'] not in self.response_lookup:
            self.response_lookup[response['id']] = response
            self.responses.append(response)
            
        return None, None

    def _process_output_item_added(self, event: dict[str, Any]) -> tuple[None, None]:
        """
        Process a response.output_item.added event.
        
        Associates an item with a response.
        
        Args:
            event: The output item added event
            
        Returns:
            tuple of (None, None)
            
        Raises:
            Exception: If the response is not found
        """
        response_id = event['response_id']
        item = event['item']
        
        response = self.response_lookup.get(response_id)
        if not response:
            raise Exception(f'response.output_item.added: Response "{response_id}" not found')
            
        response['output'].append(item['id'])
        
        return None, None

    def _process_output_item_done(self, event: dict[str, Any]) -> tuple[Optional[dict], None]:
        """
        Process a response.output_item.done event.
        
        Marks an item as completed.
        
        Args:
            event: The output item done event
            
        Returns:
            tuple of (updated_item, None)
            
        Raises:
            Exception: If the item is missing or not found
        """
        item = event['item']
        if not item:
            raise Exception('response.output_item.done: Missing "item"')
            
        found_item = self.item_lookup.get(item['id'])
        if not found_item:
            raise Exception(f'response.output_item.done: Item "{item["id"]}" not found')
            
        found_item['status'] = item['status']
        
        return found_item, None

    def _process_content_part_added(self, event: dict[str, Any]) -> tuple[Optional[dict], None]:
        """
        Process a response.content_part.added event.
        
        Adds a new content part to an item.
        
        Args:
            event: The content part added event
            
        Returns:
            tuple of (updated_item, None)
            
        Raises:
            Exception: If the item is not found
        """
        item_id = event['item_id']
        part = event['part']
        
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'response.content_part.added: Item "{item_id}" not found')
            
        item['content'].append(part)
        
        return item, None

    def _process_audio_transcript_delta(self, event: dict[str, Any]) -> tuple[Optional[dict], dict]:
        """
        Process a response.audio_transcript.delta event.
        
        Updates an item's transcript with new content.
        
        Args:
            event: The audio transcript delta event
            
        Returns:
            tuple of (updated_item, delta)
            
        Raises:
            Exception: If the item is not found
        """
        item_id = event['item_id']
        content_index = event['content_index']
        delta = event['delta']
        
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'response.audio_transcript.delta: Item "{item_id}" not found')
            
        item['content'][content_index]['transcript'] += delta
        item['formatted']['transcript'] += delta
        
        return item, {'transcript': delta}

    def _process_audio_delta(self, event: dict[str, Any]) -> tuple[Optional[dict], Optional[dict]]:
        """
        Process a response.audio.delta event.
        
        Updates an item with new audio content.
        
        Args:
            event: The audio delta event
            
        Returns:
            tuple of (updated_item, delta) or (None, None) if item not found
        """
        item_id = event['item_id']
        content_index = event['content_index']
        delta = event['delta']
        
        item = self.item_lookup.get(item_id)
        if not item:
            logger.debug(f'response.audio.delta: Item "{item_id}" not found')
            return None, None
            
        array_buffer = base64_to_array_buffer(delta)
        append_values = array_buffer.tobytes()
        
        # Note: Azure recommendation is to use proper audio concatenation 
        # TODO: Implement proper int16 array concatenation
        # item['formatted']['audio'] = np.concatenate([item['formatted']['audio'], array_buffer.view(np.int16)])
        
        return item, {'audio': append_values}

    def _process_text_delta(self, event: dict[str, Any]) -> tuple[Optional[dict], dict]:
        """
        Process a response.text.delta event.
        
        Updates an item's text with new content.
        
        Args:
            event: The text delta event
            
        Returns:
            tuple of (updated_item, delta)
            
        Raises:
            Exception: If the item is not found
        """
        item_id = event['item_id']
        content_index = event['content_index']
        delta = event['delta']
        
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'response.text.delta: Item "{item_id}" not found')
            
        item['content'][content_index]['text'] += delta
        item['formatted']['text'] += delta
        
        return item, {'text': delta}

    def _process_function_call_arguments_delta(self, event: dict[str, Any]) -> tuple[Optional[dict], dict]:
        """
        Process a response.function_call_arguments.delta event.
        
        Updates a function call item with new argument data.
        
        Args:
            event: The function call arguments delta event
            
        Returns:
            tuple of (updated_item, delta)
            
        Raises:
            Exception: If the item is not found
        """
        item_id = event['item_id']
        delta = event['delta']
        
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'response.function_call_arguments.delta: Item "{item_id}" not found')
            
        item['arguments'] += delta
        item['formatted']['tool']['arguments'] += delta
        
        return item, {'arguments': delta}
