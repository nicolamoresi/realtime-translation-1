from typing import Optional
from pydantic import BaseModel, Field


class ChatPayload(BaseModel):
    """Either a text message, or an audio chunk in base64."""
    content: Optional[str] = Field(None, description="Text message")
    audio:   Optional[bytes] = Field(None, description="Audio chunk in base64")

    @classmethod
    def validate_payload(cls, v: "ChatPayload"):   # noqa: N805
        if not (v.content or v.audio):
            raise ValueError("Either content or audio must be provided")
        return v


class JobResponse(BaseModel):
    """
    Represents the response from a processing job executed by an assembly.

    Attributes:
        assembly_id (str): The identifier of the assembly that processed the job.
        prompt (str): The input prompt or query that initiated the job.
    """

    assembly_id: str = Field(..., description="Assembly ID")
    prompt: str = Field(..., description="Job Status")


class UserRoomLanguageRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    room_id: str = Field(..., description="Room ID")
    language: str = Field(..., description="User's preferred speaking language")


class UserRoomLanguageResponse(BaseModel):
    user_id: str = Field(..., description="User ID")
    room_id: str = Field(..., description="Room ID")
    language: str = Field(..., description="User's preferred speaking language")
    bot_display_name: str = Field(..., description="Display name for the interpreter bot")
