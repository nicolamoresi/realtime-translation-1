"""
Module for managing chat room states and transitions.

This module defines abstract and concrete classes for chat room states,
including WaitingState, ActiveState, and EndedState, as well as a controller
to handle state transitions.
"""

from abc import ABC, abstractmethod
from orchestrator.session import SessionStateSubject


class ChatRoomState(ABC):
    """
    Abstract base class representing a chat room state.
    """

    @abstractmethod
    async def handle(self, controller):
        """
        Handle the behavior associated with the current state.

        Args:
            controller: The chat room controller instance.
        """
        pass


class WaitingState(ChatRoomState):
    """
    State representing a chat room in a waiting condition.
    """

    async def handle(self, controller: 'ChatRoomController'):
        """
        Set the session state to 'WAITING'.

        Args:
            controller: The chat room controller instance.
        """
        controller.subject.set_state("WAITING")


class ActiveState(ChatRoomState):
    """
    State representing an active chat room.
    """

    async def handle(self, controller: 'ChatRoomController'):
        """
        Set the session state to 'ACTIVE'.

        Args:
            controller: The chat room controller instance.
        """
        controller.subject.set_state("ACTIVE")


class EndedState(ChatRoomState):
    """
    State representing a chat room that has ended.
    """

    async def handle(self, controller: 'ChatRoomController'):
        """
        Set the session state to 'ENDED'.

        Args:
            controller: The chat room controller instance.
        """
        controller.subject.set_state("ENDED")


class ChatRoomController:
    """
    Controller for managing chat room state transitions.
    """

    def __init__(self):
        """
        Initialize the ChatRoomController.

        This creates a SessionStateSubject and sets the initial state to WaitingState.
        """
        self.subject = SessionStateSubject()
        self._state = WaitingState()

    async def change_state(self, state: ChatRoomState):
        """
        Change the current state and apply its handling.

        Args:
            state (ChatRoomState): The new state to transition into.
        """
        self._state = state
        await self._state.handle(self)
