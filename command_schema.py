from typing_extensions import Annotated, TypedDict


class Vector3Dict(TypedDict):
    """3D world position."""

    x: Annotated[float, ..., "World x coordinate."]
    y: Annotated[float, ..., "World y coordinate."]
    z: Annotated[float, ..., "World z coordinate."]


class CommandAction(TypedDict):
    """One executable action for a Unity NPC command."""

    action_id: Annotated[
        str | None,
        ...,
        "Stable action id. Use null when the backend should assign one.",
    ]
    command: Annotated[
        str | None,
        ...,
        "Executable Unity command. Use MOVE_TO, GET_ITEM, PUT_ITEM, STOP, or null.",
    ]
    object_name: Annotated[
        str | None,
        ...,
        "Target object or place name in English. Use null if the action has no named target.",
    ]
    object_id: Annotated[
        str | None,
        ...,
        "Resolved Unity object id for this action. Use null until Unity resolves a concrete object id.",
    ]
    position: Annotated[
        Vector3Dict | None,
        ...,
        "Target world position for coordinate movement. Use null when moving to a named object.",
    ]


class CommandDict(TypedDict):
    """User natural language command converted into a command for one NPC."""

    actions: Annotated[
        list[CommandAction],
        ...,
        "Ordered executable Unity actions. Use an empty list for non-executable input.",
    ]
    message: Annotated[str, ..., "AI response message for the user."]
