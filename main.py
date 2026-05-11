from fastapi import Body, FastAPI, HTTPException, Query

import os
import json
from pathlib import Path
from typing import Literal
from fastapi import WebSocket, WebSocketDisconnect
from langchain.chat_models import init_chat_model
from dotenv import load_dotenv
from typing_extensions import Annotated, TypedDict

from paring_tools import parse_command
from unity_tools import (
    is_client_function_result,
    load_unity_capabilities,
    parse_json_text,
)

load_dotenv()

# model setting
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
INPUT_ROUTER_MODEL_NAME = "gpt-4.1-mini"
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


input_router_model = input_router_base_model.with_structured_output(UserInputRoute)


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
            if parsed_message is not None and parsed_message.get("type") == "action_result":
                await websocket.send_json(
                    {
                        "type": "error",
                        "payload": {
                            "code": "ACTION_RESULT_IGNORED",
                            "message": "Action result handling is disabled in the simplified backend flow.",
                        },
                    }
                )
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

            await websocket.send_json(
                {
                    "type": "final_command",
                    "status": "ok",
                    "input": user_message,
                    "input_route": input_route,
                    "command": command_data,
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

    route = dict(result)
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
        result = await input_router_base_model.ainvoke(
            [
                ("system", system_prompt),
                ("human", message),
            ]
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OpenAI dialogue invoke failed: {exc}") from exc

    return build_noop_command(getattr(result, "content", None))


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
