"""
Module for session state management using the Observer pattern.

This module defines a SessionStateSubject class to manage session state changes and
notify subscribed observers, as well as an abstract SessionStateObserver that must be
implemented by concrete observer classes.
"""

from abc import ABC, abstractmethod
from typing import List


class SessionStateSubject:
    """
    Subject for managing session state and notifying observers.

    Attributes:
        _observers (List[SessionStateObserver]): List of observers subscribed to state changes.
        _state (str): The current session state.
    """

    def __init__(self) -> None:
        """
        Initialize the SessionStateSubject with no observers and set the default state to 'WAITING'.
        """
        self._observers: List[SessionStateObserver] = []
        self._state: str = "WAITING"

    def attach(self, observer: "SessionStateObserver") -> None:
        """
        Attach an observer to be notified of state changes.

        Args:
            observer (SessionStateObserver): The observer to attach.
        """
        self._observers.append(observer)

    def detach(self, observer: "SessionStateObserver") -> None:
        """
        Detach an observer, so it no longer receives state change notifications.

        Args:
            observer (SessionStateObserver): The observer to detach.
        """
        self._observers.remove(observer)

    def _notify(self) -> None:
        """
        Notify all subscribed observers of the current state.
        """
        for observer in self._observers:
            observer.update(self._state)

    def set_state(self, state: str) -> None:
        """
        Set a new session state and notify all attached observers.

        Args:
            state (str): The new session state.
        """
        self._state = state
        self._notify()


class SessionStateObserver(ABC):
    """
    Abstract base class for observers that subscribe to session state changes.
    """

    @abstractmethod
    def update(self, state: str) -> None:
        """
        Receive an update when the session state changes.

        Args:
            state (str): The new session state.
        """
        pass
