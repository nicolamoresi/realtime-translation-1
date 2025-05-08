"""
A package that holds response schemas and models.
"""

__all__ = [
    "RESPONSES",
    "ErrorMessage",
    "SuccessMessage",
    "Agent",
    "Swarm",
    "Tool",
    "JobResponse",
    "ChatPayload",
    "database_schema",
]

from .models import Swarm, Agent, Tool
from .endpoints import ChatPayload, JobResponse
from .responses import RESPONSES, ErrorMessage, SuccessMessage

database_schema = {
    "Agent Table": Agent.model_json_schema(),
    "Swarm Table": Swarm.model_json_schema(),
}
