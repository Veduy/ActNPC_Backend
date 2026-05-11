import json
from typing import Any

from fastapi import HTTPException
from langchain.agents import create_agent

from command_schema import CommandDict
from unity_tools import load_object_database_text, load_unity_capabilities_text
from langchain.tools import tool


def build_planner_prompt() -> str:
    return (
        "You are a command planner for a Unity NPC.\n"
        "Convert the user's command into ordered executable actions using only the Unity capabilities manifest.\n"
        "Return no actions if the command needs unsupported actions, unavailable reasoning, crafting/building mechanics, or unknown prerequisites.\n"
        "Do not invent Unity commands. Use only executable Unity command values.\n"
        "Translate action field values into English. The AI message must be Korean.\n"
   
        "Unity capabilities manifest:\n"
        "```json\n"
        f"{load_unity_capabilities_text()}\n"
        "```\n\n"
        
        "Object database. Use Only these names and aliases as planning hints, but leave object_id null until Unity resolves it:\n"
        "```json\n"
        f"{load_object_database_text()}\n"
        "```"
    )


PLANNER_MODEL = "gpt-4.1-mini"
planner_agent = None


def get_planner_agent():
    global planner_agent

    if planner_agent is None:
        planner_agent = create_agent(
            model=PLANNER_MODEL,
            tools=[],
            system_prompt=build_planner_prompt(),
            response_format=CommandDict,
        )

    return planner_agent

@tool
def get_objects_of_scene():
