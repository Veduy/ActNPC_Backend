from fastapi import Body, FastAPI, HTTPException, Query

import os
import json
import re
from pathlib import Path
from string import Template
from typing import Literal
from fastapi import WebSocket, WebSocketDisconnect
from langchain.chat_models import init_chat_model
from dotenv import load_dotenv
from typing_extensions import Annotated, TypedDict

from unity_tools import (
    apply_resolved_object_ids,
    collect_unity_context_if_needed,
    ensure_command_steps,
    finalize_unity_command,
    handle_action_result,
    is_action_result,
    is_client_function_result,
    load_object_database_text,
    load_unity_capabilities,
    load_unity_capabilities_text,
    parse_json_text,
    steps_need_object_resolution,
)

load_dotenv()

# model setting
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
MODEL_NAME = "gpt-4.1-nano"
INPUT_ROUTER_MODEL_NAME = "gpt-4.1-nano"
MODEL_PRICING_PER_1M_TOKENS = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
}
base_model = init_chat_model(MODEL_NAME)
input_router_base_model = init_chat_model(INPUT_ROUTER_MODEL_NAME)
PROMPTS_DIR = Path(__file__).with_name("prompts")
INPUT_ROUTER_PROMPT_PATH = PROMPTS_DIR / "input_router_system.md"
COMMAND_PARSER_PROMPT_PATH = PROMPTS_DIR / "command_parser_system.md"
COMMAND_NORMALIZER_PROMPT_PATH = PROMPTS_DIR / "command_normalizer.md"


class Vector3Dict(TypedDict):
    """3D world position."""

    x: Annotated[float, ..., "World x coordinate."]
    y: Annotated[float, ..., "World y coordinate."]
    z: Annotated[float, ..., "World z coordinate."]


class CommandStep(TypedDict):
    """One ordered intent step extracted from the user's command."""

    action: Annotated[
        str | None,
        ...,
        "Step action. Use an intent_action from the Unity capabilities manifest, or null.",
    ]
    object_name: Annotated[
        str | None,
        ...,
        "Target object or place name in English. Use null if the step has no named target.",
    ]
    object_id: Annotated[
        str | None,
        ...,
        "Resolved Unity object id for this step. Use null until Unity resolves a concrete object id.",
    ]
    position: Annotated[
        Vector3Dict | None,
        ...,
        "Target world position for coordinate movement. Use null when moving to a named object.",
    ]
    count: Annotated[
        int | None,
        ...,
        "Requested item instance count for this step. Use null when the user did not provide a count.",
    ]


class CommandDict(TypedDict):
    """User natural language command converted into a command for one NPC."""

    action: Annotated[
        str | None,
        ...,
        "Action to perform. Use an intent_action from the Unity capabilities manifest, or null.",
    ]
    object_name: Annotated[
        str | None,
        ...,
        "Primary target object or place name in English.",
    ]
    object_id: Annotated[
        str | None,
        ...,
        "Resolved Unity object id to execute against. Use null until Unity resolves it.",
    ]
    position: Annotated[
        Vector3Dict | None,
        ...,
        "Target world position for coordinate movement. Use null for named object targets.",
    ]
    steps: Annotated[
        list[CommandStep],
        ...,
        "Ordered executable intent steps extracted from the user input. Use an empty list for questions or chat.",
    ]
    message: Annotated[str, ..., "AI response message for the user."]


class UserInputRoute(TypedDict):
    """Single-pass route for user input before loading heavier context."""

    route: Annotated[
        Literal[
            "general_dialogue",
            "capability_question",
            "immediate_command",
            "goal_command",
            "unsupported_or_unknown",
        ],
        ...,
        "Single route for the user input.",
    ]
    goal: Annotated[
        str | None,
        ...,
        "Concise English goal when route is goal_command, otherwise null.",
    ]
    confidence: Annotated[float, ..., "Classifier confidence from 0.0 to 1.0."]
    reason: Annotated[str, ..., "Short English reason for the route."]


class DialogueResponse(TypedDict):
    """Non-executable NPC response for conversation input."""

    message: Annotated[str, ..., "Natural Korean response for the user."]


input_router_model = input_router_base_model.with_structured_output(UserInputRoute, include_raw=True)
dialogue_model = input_router_base_model.with_structured_output(DialogueResponse, include_raw=True)
model = base_model.with_structured_output(CommandDict, include_raw=True)

def load_prompt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt file was not found: {path.name}") from exc


def build_system_prompt() -> str:
    return (
        f"{load_prompt(COMMAND_PARSER_PROMPT_PATH)}\n\n"
        "Unity capabilities manifest:\n"
        "```json\n"
        f"{load_unity_capabilities_text()}\n"
        "```\n\n"
        "Object database. Use these object_id values for known targets. Unity treats object_id as an object type id; multiple scene instances may share one object_id, and Unity will choose the nearest matching scene instance at execution time:\n"
        "```json\n"
        f"{load_object_database_text()}\n"
        "```"
    )


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
    input_route, route, dialogue_type_route, command_type_route, command = await handle_user_input(message)

    return {
        "status": "ok",
        "input": message,
        "input_route": input_route,
        "intent_route": route,
        "dialogue_type_route": dialogue_type_route,
        "command_type_route": command_type_route,
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
    input_route, route, dialogue_type_route, command_type_route, command_data = await handle_user_input(message)

    return {
        "status": "ok",
        "input": message,
        "input_route": input_route,
        "intent_route": route,
        "dialogue_type_route": dialogue_type_route,
        "command_type_route": command_type_route,
        "command": command_data,
    }

@app.post("/command/test")
async def command_test():
    return {
        "status": "ok",
        "input": "사과로 이동해",
        "command": {
            "action": "move",
            "destination": "apple",
            "item": None,
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
                input_route, route, dialogue_type_route, command_type_route, command_data = await handle_user_input(user_message)
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

            if route.get("intent") == "conversation":
                await websocket.send_json(
                    {
                        "type": "final_command",
                        "status": "ok",
                        "input": user_message,
                        "input_route": input_route,
                        "intent_route": route,
                        "dialogue_type_route": dialogue_type_route,
                        "command_type_route": command_type_route,
                        "command": command_data,
                        "client_context": None,
                    }
                )
                continue

            if command_type_route and command_type_route.get("command_type") != "immediate_command":
                await websocket.send_json(
                    {
                        "type": "final_command",
                        "status": "ok",
                        "input": user_message,
                        "input_route": input_route,
                        "intent_route": route,
                        "dialogue_type_route": dialogue_type_route,
                        "command_type_route": command_type_route,
                        "command": command_data,
                        "client_context": None,
                    }
                )
                continue

            client_context = await collect_unity_context_if_needed(websocket, command_data)
            apply_resolved_object_ids(command_data, client_context)
            command_data = await normalize_to_minimal_command(user_message, command_data, client_context)
            if steps_need_object_resolution(command_data):
                normalized_context = await collect_unity_context_if_needed(websocket, command_data)
                apply_resolved_object_ids(command_data, normalized_context)
            finalize_unity_command(command_data)

            await websocket.send_json(
                {
                    "type": "final_command",
                    "status": "ok",
                    "input": user_message,
                    "input_route": input_route,
                    "intent_route": route,
                    "dialogue_type_route": dialogue_type_route,
                    "command_type_route": command_type_route,
                    "command": command_data,
                    "client_context": client_context,
                }
            )

    except WebSocketDisconnect:
        print("Unity client disconnected")


async def handle_user_input(message: str) -> tuple[dict, dict, dict | None, dict | None, dict]:
    input_route = await route_input(message)
    route = build_legacy_intent_route(input_route)
    dialogue_type_route = build_legacy_dialogue_type_route(input_route)
    command_type_route = build_legacy_command_type_route(input_route)
    selected_route = input_route.get("route")

    if selected_route in {"general_dialogue", "capability_question"}:
        include_capabilities = selected_route == "capability_question"
        return input_route, route, dialogue_type_route, None, await build_dialogue_command(
            message,
            include_capabilities,
            selected_route,
        )
    if selected_route == "immediate_command":
        return input_route, route, None, command_type_route, await parse_command(message)
    if selected_route == "goal_command":
        return input_route, route, None, command_type_route, build_noop_command("목표형 명령으로 이해했지만, 아직 Planner가 연결되지 않았어요.")

    return input_route, route, None, command_type_route, build_noop_command("명령으로 이해했지만, 아직 실행 가능한 형태로 분류하지 못했어요.")


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
        "general_dialogue",
        "capability_question",
        "immediate_command",
        "goal_command",
        "unsupported_or_unknown",
    }:
        raise HTTPException(status_code=503, detail=f"route_input returned invalid route: {route.get('route')}")

    return route


def build_legacy_intent_route(input_route: dict) -> dict:
    route = input_route.get("route")
    intent = "conversation" if route in {"general_dialogue", "capability_question"} else "command"
    return {
        "intent": intent,
        "confidence": input_route.get("confidence"),
        "reason": input_route.get("reason"),
    }


def build_legacy_dialogue_type_route(input_route: dict) -> dict | None:
    route = input_route.get("route")
    if route not in {"general_dialogue", "capability_question"}:
        return None

    return {
        "dialogue_type": route,
        "confidence": input_route.get("confidence"),
        "reason": input_route.get("reason"),
    }


def build_legacy_command_type_route(input_route: dict) -> dict | None:
    route = input_route.get("route")
    if route in {"general_dialogue", "capability_question"}:
        return None

    return {
        "command_type": route,
        "goal": input_route.get("goal") if route == "goal_command" else None,
        "confidence": input_route.get("confidence"),
        "reason": input_route.get("reason"),
    }


async def build_dialogue_command(
    message: str,
    include_capabilities: bool = False,
    route_name: str | None = None,
) -> dict:
    system_prompt = (
        "You are a friendly Unity NPC. Answer questions and small talk in Korean. "
        "Do not claim that you performed any physical action."
    )
    if include_capabilities:
        system_prompt = (
            f"{system_prompt}\n\n"
            "Unity capabilities manifest:\n"
            "```json\n"
            f"{load_unity_capabilities_text()}\n"
            "```\n\n"
            "If the user asks whether an action is possible, answer based on the manifest."
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

    operation = f"build_dialogue_command[{route_name}]" if route_name else "build_dialogue_command"
    response = extract_structured_output(result, operation, INPUT_ROUTER_MODEL_NAME)
    return build_noop_command(response.get("message"))


def build_noop_command(message: object) -> dict:
    return {
        "action": None,
        "destination": None,
        "item": None,
        "object": None,
        "steps": [],
        "message": message if isinstance(message, str) and message.strip() else "지금은 실행할 명령이 없어요.",
    }


async def parse_command(message: str) -> dict:
    try:
        result = await model.ainvoke(
            [
                ("system", build_system_prompt()),
                ("human", message),
            ]
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OpenAI model invoke failed: {exc}") from exc

    return extract_structured_command(result, "parse_command")


async def normalize_to_minimal_command(
    user_message: str,
    command_data: dict,
    client_context: dict | None,
) -> dict:
    steps = ensure_command_steps(command_data)
    if not steps:
        return command_data
    if not needs_minimal_normalization(user_message, steps):
        return command_data

    normalization_prompt = build_normalization_prompt(user_message, command_data, client_context)

    try:
        result = await model.ainvoke(
            [
                ("system", load_prompt(COMMAND_NORMALIZER_PROMPT_PATH)),
                ("human", normalization_prompt),
            ]
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OpenAI command normalization failed: {exc}") from exc

    return extract_structured_command(result, "normalize_to_minimal_command")


def build_normalization_prompt(user_message: str, command_data: dict, client_context: dict | None) -> str:
    return Template(
        "Original:\n"
        "$user_message\n\n"
        "Parsed:\n"
        "$command_data_json\n\n"
        "Unity context:\n"
        "$client_context_json"
    ).safe_substitute(
        user_message=user_message,
        command_data_json=json.dumps(command_data, ensure_ascii=False),
        client_context_json=json.dumps(client_context, ensure_ascii=False),
    )


def needs_minimal_normalization(user_message: str, steps: list[dict]) -> bool:
    return has_all_items_request(user_message)


def has_all_items_request(message: str) -> bool:
    normalized = message.strip().lower()
    if re.search(r"\b(all|every|everything|each)\b", normalized):
        return True

    return any(keyword in normalized for keyword in ("전부", "모두", "전체", "모든", "있는", "싹"))


def extract_structured_command(result, operation: str) -> dict:
    return extract_structured_output(result, operation, MODEL_NAME)


def extract_structured_output(result, operation: str, model_name: str) -> dict:
    if isinstance(result, dict) and "parsed" in result:
        parsing_error = result.get("parsing_error")
        if parsing_error:
            raise HTTPException(status_code=503, detail=f"{operation} structured output parsing failed: {parsing_error}")

        raw_response = result.get("raw")
        usage = getattr(raw_response, "usage_metadata", None)
        if usage:
            log_model_usage_cost(operation, usage, model_name)

        parsed = result.get("parsed")
    else:
        parsed = result

    if parsed is None:
        raise HTTPException(status_code=503, detail=f"{operation} returned no parsed command.")

    return dict(parsed)


def log_model_usage_cost(operation: str, usage: dict, model_name: str) -> None:
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    total_tokens = usage.get("total_tokens", input_tokens + output_tokens)
    pricing = MODEL_PRICING_PER_1M_TOKENS.get(model_name)

    if pricing is None:
        print(
            f"{operation} usage/cost: model={model_name}, "
            f"input_tokens={input_tokens}, output_tokens={output_tokens}, "
            f"total_tokens={total_tokens}, cost_usd=price_unknown"
        )
        return

    input_cost = input_tokens / 1_000_000 * pricing["input"]
    output_cost = output_tokens / 1_000_000 * pricing["output"]
    total_cost = input_cost + output_cost

    print(
        f"{operation} usage/cost: model={model_name}, "
        f"input_tokens={input_tokens}, output_tokens={output_tokens}, "
        f"total_tokens={total_tokens}, input_cost_usd=${input_cost:.8f}, "
        f"output_cost_usd=${output_cost:.8f}, total_cost_usd=${total_cost:.8f}"
    )


async def replan_after_action_failure(action_result: dict) -> dict:
    failed_action = action_result.get("action") if isinstance(action_result.get("action"), dict) else {}
    failure_prompt = f"""
Unity failed while executing an NPC action.

Failed action:
{json.dumps(failed_action, ensure_ascii=False)}

Failure reason:
{action_result.get("message")}

Use the Unity capabilities manifest to make a new executable recovery plan.
If GET_ITEM failed because the target is not within pickup range, the NPC should usually move to that target first and then get the item.
Return only actions that should be attempted after this failure.
""".strip()

    return await parse_command(failure_prompt)


def main():
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
