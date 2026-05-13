from typing import Literal

from pydantic import BaseModel, Field


class Vector3Dict(BaseModel):
    """3D world position."""

    x: float = Field(description="World x coordinate.")
    y: float = Field(description="World y coordinate.")
    z: float = Field(description="World z coordinate.")


class CommandAction(BaseModel):
    """One executable action for a Unity NPC command."""

    action_id: str | None = Field(
        default=None,
        description="Stable action id. Use null when the backend should assign one.",
    )
    command: Literal["MOVE_TO", "GET_ITEM", "PUT_ITEM", "STOP"] | None = Field(
        description="Executable Unity command. Use MOVE_TO, GET_ITEM, PUT_ITEM, STOP, or null.",
    )
    object_name: str | None = Field(
        default=None,
        description="Human-readable target object or place name in English. Use only names allowed by the object database. Use null if the action has no named target.",
    )
    object_id: str | None = Field(
        default=None,
        description="Unique Unity scene object instance id for the selected target. Use null until a concrete scene or inventory instance is selected.",
    )
    position: Vector3Dict | None = Field(
        default=None,
        description="Target world position for coordinate movement. Use null when moving to or acting on a selected scene object.",
    )


class CommandDict(BaseModel):
    """User natural language command converted into a command for one NPC."""

    actions: list[CommandAction] = Field(
        description="Ordered executable Unity actions. Use an empty list for non-executable input.",
    )
    message: str = Field(description="AI response message for the user.")
