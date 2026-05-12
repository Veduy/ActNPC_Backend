import json
from typing import Any

from fastapi import HTTPException
from langchain.agents import create_agent
from langchain.tools import tool

from command_schema import CommandDict
from unity_tools import UnityToolSession, load_object_database_text, load_unity_capabilities_text


PLANNER_MODEL = "gpt-4.1-mini"


def build_planner_prompt() -> str:
    return (
        "You are a command planner for a Unity NPC.\n"
        "You receive the user's original natural language command.\n"
        "Return a final CommandDict that can execute successfully in the current Unity scene.\n"
        "Use Unity tools to inspect scene objects, agent state, and inventory before choosing object_id values.\n"
        "Conversation memory may contain summary, recent messages, and the last command. "
        "Use it only to resolve references to previous items, places, targets, or commands.\n"
        "Do not invent Unity commands. Use only MOVE_TO, GET_ITEM, PUT_ITEM, STOP, or null.\n\n"

        "Output rules:\n"
        "- Return actions only; do not use top-level action/object_name/object_id/position fields.\n"
        "- English for command, object_name, object_id, and action fields. Korean for message.\n"
        "- The Korean message must use casual speech, not honorifics, and every Korean sentence must end with 냥.\n"
        "- Use only object names from the object database in action.object_name.\n"
        "- action.object_id may be used only when it comes from a Unity tool result and identifies one concrete scene or inventory instance.\n"
        "- action_id may be null; the backend will assign stable ids.\n\n"

        "Command parsing rules:\n"
        "- Map pickup/grab/collect/take/fetch/retrieve/get-for-user to GET_ITEM.\n"
        "- Map put down/drop/place/take out from inventory to PUT_ITEM.\n"
        "- Map go/move/approach/head to MOVE_TO.\n"
        "- MOVE_TO requires a known scene object, place name, or explicit world coordinates.\n"
        "- Put coordinate movement targets in position as {x,y,z}. Do not put object names in position.\n"
        "- Relative movement such as forward/back/left/right is unsupported; return actions empty and explain the limitation.\n"
        "- Unsupported physical actions: return actions empty and explain the unavailable capability.\n"
        "- Compound commands become ordered actions.\n"
        "- Explicit repeated item counts should repeat the needed actions. No count means one action sequence.\n"
        "- For all/every item requests, keep the requested item target concise and do not guess object count.\n\n"

        "Planning rules:\n"
        "- Before every GET_ITEM, include MOVE_TO for the same item unless tool results show the NPC is already near it.\n"
        "- PUT_ITEM requires the item to be in inventory.\n"
        "- If the item is not in inventory and the user requested putting that item somewhere, first plan MOVE_TO item then GET_ITEM item.\n"
        "- If putting an item at, near, in front of, or into a place/object, include MOVE_TO for that place/object before PUT_ITEM.\n"
        "- For PUT_ITEM, target the inventory item by object_name and leave object_id null unless a Unity inventory tool provides an explicit inventory id.\n"
        "- If multiple matching scene objects exist, choose the nearest active object unless the user clearly specifies otherwise.\n"
        "- Do not rely on Unity execution failure to discover obvious prerequisites.\n"
        "- Keep the action list minimal but complete.\n\n"

        "Unity capabilities manifest:\n"
        "```json\n"
        f"{load_unity_capabilities_text()}\n"
        "```\n\n"
        "Object database:\n"
        "```json\n"
        f"{load_object_database_text()}\n"
        "```"
    )


def build_planner_tools(tool_session: UnityToolSession):
    @tool
    async def find_scene_objects(query: str, object_type: str | None = None, max_results: int = 5) -> dict:
        """Find Unity scene object instances by object name or alias. Returns object_id, object_name, type, position, active, and distance from the NPC."""
        return await tool_session.request(
            "find_scene_objects",
            {
                "query": query,
                "object_type": object_type,
                "max_results": max_results,
            },
        )

    @tool
    async def get_agent_state() -> dict:
        """Return the NPC position, state, and pickup radius."""
        return await tool_session.request("get_agent_state", {})

    @tool
    async def get_inventory() -> dict:
        """Return the list of items currently held by the NPC."""
        return await tool_session.request("get_inventory", {})

    return [find_scene_objects, get_agent_state, get_inventory]


def build_planner_agent(tool_session: UnityToolSession):
    return create_agent(
        model=PLANNER_MODEL,
        tools=build_planner_tools(tool_session),
        system_prompt=build_planner_prompt(),
        response_format=CommandDict,
    )


async def plan_command(
    tool_session: UnityToolSession,
    user_message: str,
    memory_context: dict | None = None,
) -> dict:
    planner_input = {
        "user_message": user_message,
        "memory": memory_context or {},
    }

    try:
        result = await build_planner_agent(tool_session).ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": json.dumps(planner_input, ensure_ascii=False),
                    }
                ]
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Planner agent invoke failed: {exc}") from exc

    return extract_planner_command(result)


def extract_planner_command(result: Any) -> dict:
    if isinstance(result, dict):
        structured_response = result.get("structured_response")
        if structured_response is not None:
            if hasattr(structured_response, "model_dump"):
                return normalize_command(structured_response.model_dump())
            return normalize_command(dict(structured_response))

    if hasattr(result, "model_dump"):
        return normalize_command(result.model_dump())

    if isinstance(result, dict):
        return normalize_command(dict(result))

    raise HTTPException(status_code=503, detail="Planner agent returned no structured command.")


def normalize_command(command: dict) -> dict:
    actions = command.get("actions")
    if not isinstance(actions, list):
        command["actions"] = []
    else:
        for index, action in enumerate(actions, start=1):
            if not isinstance(action, dict):
                continue
            action.setdefault("action_id", f"action_{index}")
            action.setdefault("object_name", None)
            action.setdefault("object_id", None)
            action.setdefault("position", None)

    message = command.get("message")
    if not isinstance(message, str) or not message.strip():
        command["message"] = "명령을 처리했어요."
        return command
    return command
    if not isinstance(message, str) or not message.strip():
        command["message"] = "명령을 처리했어요."

    return command
