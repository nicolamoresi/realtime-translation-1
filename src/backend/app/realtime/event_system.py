"""
Event system for Azure real-time translation components.

Provides a publish/subscribe implementation optimized for asynchronous 
WebSocket communication, following Azure best practices for reactive systems.
"""

import asyncio
import inspect
from collections import defaultdict
from typing import Any, Callable, Dict, List


class RealtimeEventHandler:
    """
    Foundation for event-based communication between components.
    
    Implements a flexible pub/sub pattern that handles both synchronous and
    asynchronous event handlers transparently, following Azure's recommended
    event-driven architecture pattern.
    """
    
    def __init__(self) -> None:
        """Initialize the event handler with empty subscriber lists."""
        self.event_handlers: Dict[str, List[Callable]] = defaultdict(list)

    def on(self, event_name: str, handler: Callable) -> None:
        """
        Register a callback for a specific event.
        
        Args:
            event_name: The event to subscribe to
            handler: Function or coroutine function to call when event occurs
        """
        self.event_handlers[event_name].append(handler)
        
    def clear_event_handlers(self) -> None:
        """Remove all event handlers."""
        self.event_handlers = defaultdict(list)

    def dispatch(self, event_name: str, event: Dict[str, Any]) -> None:
        """
        Trigger all handlers for a specific event.
        
        Args:
            event_name: The event name to trigger
            event: The event payload to pass to handlers
        """
        for handler in self.event_handlers[event_name]:
            if inspect.iscoroutinefunction(handler):
                # Run coroutine functions asynchronously
                asyncio.create_task(handler(event))
            else:
                # Run synchronous functions directly
                handler(event)

    async def wait_for_next(self, event_name: str) -> Dict[str, Any]:
        """
        Asynchronously wait for the next occurrence of an event.
        
        Args:
            event_name: The event to wait for
            
        Returns:
            The event payload when it occurs
        """
        future: asyncio.Future = asyncio.Future()

        def handler(event: Dict[str, Any]) -> None:
            """One-time event handler that resolves the future."""
            if not future.done():
                future.set_result(event)

        self.on(event_name, handler)
        return await future
