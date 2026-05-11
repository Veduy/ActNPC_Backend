from fastapi import Body, FastAPI, HTTPException, Query

import os
import json
from pathlib import Path
from typing import Literal
from fastapi import WebSocket, WebSocketDisconnect
from langchain.chat_models import init_chat_model
from dotenv import load_dotenv
from typing_extensions import Annotated, TypedDict

from paring_tools import (
    extract_structured_output,
    normalize_to_minimal_command,
    parse_command,
    replan_after_action_failure,
)
from unity_tools import (
    apply_resolved_object_ids,
    collect_unity_context_if_needed,
    finalize_unity_command,
    handle_action_result,
    is_action_result,
    is_client_function_result,
    load_unity_capabilities,
    parse_json_text,
    actions_need_object_resolution,
)

load_dotenv()

# model setting
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
INPUT_ROUTER_MODEL_NAME = "gpt-4.1-nano"
input_router_base_model = init_chat_model(INPUT_ROUTER_MODEL_NAME)
PROMPTS_DIR = Path(__file__).with_name("prompts")
INPUT_ROUTER_PROMPT_PATH = PROMPTS_DIR / "input_router_system.md"


class UserInputRoute(TypedDict):
    """Single-pass route for user input before loading heavier context."""

    route: Annotated[
        Literal[
            "dialogue",
            "command",
        ],
        ...,
        "Single route for the user input.",
    ]
    confidence: Annotated[float, ..., "Classifier confidence from 0.0 to 1.0."]
    reason: Annotated[str, ..., "Short English reason for the route."]


class DialogueResponse(TypedDict):
    """Non-executable NPC response for conversation input."""

    message: Annotated[str, ..., "Natural Korean response for the user."]


input_router_model = input_router_base_model.with_structured_output(UserInputRoute, include_raw=True)
dialogue_model = input_router_base_model.with_structured_output(DialogueResponse, include_raw=True)


def load_prompt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt file was not found: {path.name}") from exc


app = FastAPI(
    title="ActNPC Backend",
    version="0.1.0",
    description="FastAPI backend for the Unity intelligent NPC agent."
)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "actnpc-backend",
        "version": "0.1.0",
    }


@app.get("/health/openai")
async def openai_health_check(
    message: str = Query(..., min_length=1, description="Natural language input for the connected model"),
):
    input_route, command = await handle_user_input(message)

    return {
        "status": "ok",
        "input": message,
        "input_route": input_route,
        "command": command,
    }


@app.get("/unity/capabilities")
def unity_capabilities():
    try:
        return load_unity_capabilities()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="unity_capabilities.json was not found.") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"unity_capabilities.json is invalid JSON: {exc}") from exc


@app.post("/command")
async def command(
    message: Annotated[
        str,
        Body(..., embed=True, min_length=1, description="Natural language command from Unity."),
    ],
):
    input_route, command_data = await handle_user_input(message)

    return {
        "status": "ok",
        "input": message,
        "input_route": input_route,
        "command": command_data,
    }

@app.post("/command/test")
async def command_test():
    return {
        "status": "ok",
        "input": "사과로 이동해",
        "command": {
            "actions": [
                {
                    "action_id": "act_001",
                    "command": "MOVE_TO",
                    "object_name": "apple",
                    "object_id": None,
                    "position": None,
                }
            ],
            "message": "사과 위치로 이동할게요.",
        },
    }


@app.websocket("/ws/agent")
async def websocket_agent(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            raw_message = await websocket.receive_text()

            parsed_message = parse_json_text(raw_message)
            if is_client_function_result(parsed_message):
                await websocket.send_json(
                    {
                        "type": "error",
                        "payload": {
                            "code": "UNEXPECTED_CLIENT_FUNCTION_RESULT",
                            "message": "Client function result was received without a pending server request.",
                        },
                    }
                )
                continue
            if is_action_result(parsed_message):
                await handle_action_result(websocket, parsed_message, replan_after_action_failure)
                continue

            user_message = raw_message
            try:
                input_route, command_data = await handle_user_input(user_message)
            except HTTPException as exc:
                await websocket.send_json(
                    {
                        "type": "error",
                        "status": "error",
                        "input": user_message,
                        "payload": {
                            "code": "COMMAND_PARSE_FAILED",
                            "message": exc.detail,
                        },
                    }
                )
                continue

            if input_route.get("route") == "dialogue":
                await websocket.send_json(
                    {
                        "type": "final_command",
                        "status": "ok",
                        "input": user_message,
                        "input_route": input_route,
                        "command": command_data,
                        "client_context": None,
                    }
                )
                continue

            client_context = await collect_unity_context_if_needed(websocket, command_data)
            apply_resolved_object_ids(command_data, client_context)
            command_data = await normalize_to_minimal_command(user_message, command_data, client_context)
            if actions_need_object_resolution(command_data):
                normalized_context = await collect_unity_context_if_needed(websocket, command_data)
                apply_resolved_object_ids(command_data, normalized_context)
            finalize_unity_command(command_data)

            await websocket.send_json(
                {
                    "type": "final_command",
                    "status": "ok",
                    "input": user_message,
                    "input_route": input_route,
                    "command": command_data,
                    "client_context": client_context,
                }
            )

    except WebSocketDisconnect:
        print("Unity client disconnected")


# 1차로 LLM이 사용자 입력 의도를 분류
async def handle_user_input(message: str) -> tuple[dict, dict]:
    input_route = await route_input(message)
    selected_route = input_route.get("route")

    if selected_route == "dialogue":
        return input_route, await build_dialogue_command(
            message,
        )
    if selected_route == "command":
        return input_route, await parse_command(message)

    return input_route, build_noop_command("입력 의도를 분류하지 못했어요.")


async def route_input(message: str) -> dict:
    try:
        result = await input_router_model.ainvoke(
            [
                ("system", load_prompt(INPUT_ROUTER_PROMPT_PATH)),
                ("human", message),
            ]
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OpenAI input router invoke failed: {exc}") from exc

    route = extract_structured_output(result, "route_input", INPUT_ROUTER_MODEL_NAME)
    if route.get("route") not in {
        "dialogue",
        "command",
    }:
        raise HTTPException(status_code=503, detail=f"route_input returned invalid route: {route.get('route')}")

    return route


async def build_dialogue_command(
    message: str,
) -> dict:
    system_prompt = (
        "You are a friendly Unity NPC. Answer questions and small talk in Korean. "
        "Do not claim that you performed any physical action."
    )

    try:
        result = await dialogue_model.ainvoke(
            [
                ("system", system_prompt),
                ("human", message),
            ]
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OpenAI dialogue invoke failed: {exc}") from exc

    response = extract_structured_output(result, "build_dialogue_command", INPUT_ROUTER_MODEL_NAME)
    return build_noop_command(response.get("message"))


def build_noop_command(message: object) -> dict:
    return {
        "actions": [],
        "message": message if isinstance(message, str) and message.strip() else "지금은 실행할 명령이 없어요.",
    }


def main():
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
