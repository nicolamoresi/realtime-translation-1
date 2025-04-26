"""
Module for handling transcript state management and call commands.

This module contains classes for managing transcript snapshots via a data channel,
saving transcript history to a file, and ending a call by transitioning the call
controller state.
"""

import json
from typing import List, Optional
from aiortc import RTCDataChannel


class TranscriptMemento:
    """
    Memento for capturing and sending transcript snapshots via a RTCDataChannel.
    """

    def __init__(self, channel: RTCDataChannel) -> None:
        """
        Initialize the TranscriptMemento with a data channel.

        Args:
            channel (RTCDataChannel): The data channel to send transcripts.
        """
        self._channel = channel

    def send_transcripts(self, transcripts: List[str]) -> None:
        """
        Send transcripts as a JSON-encoded string over the data channel.

        Args:
            transcripts (List[str]): List of transcript strings.
        """
        self._channel.send(json.dumps(transcripts))


class TranscriptCaretaker:
    """
    Caretaker to manage the transcript history and associated mementos.
    """

    def __init__(self) -> None:
        """
        Initialize the TranscriptCaretaker with empty transcript and memento lists.
        """
        self._transcripts: List[str] = []
        self._mementos: List[TranscriptMemento] = []

    def add_transcript(self, transcript: str) -> None:
        """
        Add a transcript line to the history.

        Args:
            transcript (str): A single line of transcript.
        """
        self._transcripts.append(transcript)

    def snapshot(self, channel: RTCDataChannel) -> TranscriptMemento:
        """
        Create a snapshot of the current transcripts and send it over the given channel.

        Args:
            channel (RTCDataChannel): The data channel to send the snapshot.

        Returns:
            TranscriptMemento: The memento containing the snapshot.
        """
        memento = TranscriptMemento(channel)
        memento.send_transcripts(self._transcripts)
        self._mementos.append(memento)
        return memento

    def get_all(self) -> List[str]:
        """
        Retrieve a copy of all transcript lines.

        Returns:
            List[str]: The current transcript history.
        """
        return list(self._transcripts)

    def get_memento(self, index: int) -> TranscriptMemento:
        """
        Retrieve a specific transcript memento by index.

        Args:
            index (int): The index of the desired memento.

        Returns:
            TranscriptMemento: The corresponding memento.
        """
        return self._mementos[index]

    def restore(self, index: int) -> None:
        """
        Restore transcripts to a previous state based on the memento.

        Args:
            index (int): The index of the memento to restore.

        Note:
            Restoration logic is not implemented.
        """
        pass


class SaveTranscriptCommand:
    """
    Command to save the transcript history to a file.
    """

    def __init__(self, room_id: str, caretaker: Optional[TranscriptCaretaker]) -> None:
        """
        Initialize the SaveTranscriptCommand with a room ID and caretaker instance.

        Args:
            room_id (str): Identifier for the room.
            caretaker (Optional[TranscriptCaretaker]): Instance managing the transcripts.
        """
        self._room_id = room_id
        self._caretaker = caretaker

    async def execute(self) -> None:
        """
        Execute the command to save transcripts.

        The transcripts are saved in a file named 'transcript_<room_id>.txt'
        with each transcript on a new line.
        """
        transcripts = self._caretaker.get_all() if self._caretaker else []
        filename = f"transcript_{self._room_id}.txt"
        with open(filename, "w", encoding="utf-8") as file:
            for transcript in transcripts:
                file.write(transcript + "\n")


class EndCallCommand:
    """
    Command to end a call by changing the state of the call controller.
    """

    def __init__(self, controller) -> None:
        """
        Initialize the EndCallCommand with the controller instance.

        Args:
            controller: The controller responsible for managing call state.
        """
        self._controller = controller

    async def execute(self) -> None:
        """
        Execute the command to end the call.

        This method transitions the call controller's state to 'EndedState'.
        """
        from app.room import EndedState
        await self._controller.change_state(EndedState())