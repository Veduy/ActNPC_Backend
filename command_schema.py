from typing_extensions import Annotated, NotRequired, TypedDict


class Vector3Dict(TypedDict):
    """3D world position."""

    x: Annotated[float, ..., "World x coordinate."]
    y: Annotated[float, ..., "World y coordinate."]
    z: Annotated[float, ..., "World z coordinate."]


class CommandAction(TypedDict):
    """One executable action for a Unity NPC command."""

    action_id: NotRequired[Annotated[
        str | None,
        "Stable action id. Use null when the backend should assign one.",
    ]]
    command: Annotated[
        str | None,
        ...,
        "Executable Unity command. Use MOVE_TO, GET_ITEM, PUT_ITEM, STOP, or null.",
    ]
    object_name: NotRequired[Annotated[
        str | None,
        "Human-readable target object or place name in English. Use only names allowed by the object database. Use null if the action has no named target.",
    ]]
    object_id: NotRequired[Annotated[
        str | None,
        "Unique Unity scene object instance id for the selected target. This must identify one concrete object in the current scene. Use null until a specific scene instance is selected.",
    ]]
    position: NotRequired[Annotated[
        Vector3Dict | None,
        "Target world position for coordinate movement. Use null when moving to or acting on a selected scene object.",
    ]]


class CommandDict(TypedDict):
    """User natural language command converted into a command for one NPC."""

    actions: Annotated[
        list[CommandAction],
        ...,
        "Ordered executable Unity actions. Use an empty list for non-executable input.",
    ]
    message: Annotated[str, ..., "AI response message for the user."]
