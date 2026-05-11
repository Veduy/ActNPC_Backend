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
        "You receive the user's original command and an initial CommandDict.\n"
        "Return a final CommandDict that can execute successfully in the current Unity scene.\n"
        "Use Unity tools to inspect scene objects, agent state, and inventory before choosing object_id values.\n"
        "Do not invent Unity commands. Use only MOVE_TO, GET_ITEM, PUT_ITEM, STOP, or null.\n"
        "Use only object names from the object database in action.object_name.\n"
        "Use action.object_id only when it comes from a Unity tool result and identifies one concrete scene instance.\n"
        "The AI message must be Korean.\n\n"
        "Planning rules:\n"
        "- GET_ITEM requires the NPC to be near the item.\n"
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
        """Find Unity scene object instances by object name or alias."""
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
        """Return the NPC inventory items."""
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
    initial_command: dict,
) -> dict:
    planner_input = {
        "user_message": user_message,
        "initial_command": initial_command,
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
                return structured_response.model_dump()
            return dict(structured_response)

    if hasattr(result, "model_dump"):
        return result.model_dump()

    if isinstance(result, dict):
        return dict(result)

    raise HTTPException(status_code=503, detail="Planner agent returned no structured command.")
