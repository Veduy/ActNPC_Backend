import json
from typing import Any

from fastapi import HTTPException
from langchain.agents import create_agent

from command_schema import CommandDict
from unity_tools import load_object_database_text, load_unity_capabilities_text


def build_planner_prompt() -> str:
    return (
        "You are a command planner for a Unity NPC.\n"
        "Convert the user's command into ordered executable actions using only the Unity capabilities manifest.\n"
        "Return no actions if the command needs unsupported actions, unavailable reasoning, crafting/building mechanics, or unknown prerequisites.\n"
        "Do not invent Unity commands. Use only executable Unity command values: MOVE_TO, GET_ITEM, PUT_ITEM, STOP.\n"
        "Translate action field values into English. The message must be Korean.\n"
        "Prefer the smallest useful action list that can be executed now.\n\n"
        "Unity capabilities manifest:\n"
        "```json\n"
        f"{load_unity_capabilities_text()}\n"
        "```\n\n"
        "Object database. Use these names and aliases as planning hints, but leave object_id null until Unity resolves it:\n"
        "```json\n"
        f"{load_object_database_text()}\n"
        "```"
    )


PLANNER_MODEL_NAME = "gpt-4.1-nano"
planner_agent = None


def get_planner_agent():
    global planner_agent

    if planner_agent is None:
        planner_agent = create_agent(
            model=PLANNER_MODEL_NAME,
            tools=[],
            system_prompt=build_planner_prompt(),
            response_format=CommandDict,
        )

    return planner_agent


async def run_planner(message: str) -> dict:
    planner_input = {
        "user_command": message,
    }

    try:
        result = await get_planner_agent().ainvoke(
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

    command = extract_planner_command(result)
    normalize_planner_command(command)
    return command


def extract_planner_command(result: Any) -> dict:
    if isinstance(result, dict):
        structured_response = result.get("structured_response")
        if structured_response is not None:
            if hasattr(structured_response, "model_dump"):
                return structured_response.model_dump()
            return dict(structured_response)

    raise HTTPException(status_code=503, detail="Planner agent returned no structured command.")


def normalize_planner_command(command: dict) -> None:
    actions = command.get("actions")
    if not isinstance(actions, list):
        command["actions"] = []

    command.setdefault("message", "명령을 실행 가능한 단계로 바꿨어요.")
