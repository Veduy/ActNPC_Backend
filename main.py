from fastapi import Body, FastAPI, HTTPException, Query

import os
import asyncio
import json
import uuid
from pathlib import Path
from fastapi import WebSocket, WebSocketDisconnect
from langchain.chat_models import init_chat_model
from dotenv import load_dotenv
from typing_extensions import Annotated, TypedDict

load_dotenv()

# model setting
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
base_model = init_chat_model("gpt-4.1")
CAPABILITIES_PATH = Path(__file__).with_name("unity_capabilities.json")
OBJECT_DATABASE_PATH = Path(__file__).with_name("object_database.json")


class CommandStep(TypedDict):
    """One ordered intent step extracted from the user's command."""

    action: Annotated[
        str | None,
        ...,
        "Step action. Use an intent_action from the Unity capabilities manifest, or null.",
    ]
    target: Annotated[
        str | None,
        ...,
        "Target object or place name for this step in English. Use null if the step has no target.",
    ]
    object: Annotated[
        str | None,
        ...,
        "Resolved Unity object id for this step. Use null until Unity returns a concrete object_id.",
    ]


class CommandDict(TypedDict):
    """User natural language command converted into a command for one NPC."""

    action: Annotated[
        str | None,
        ...,
        "Action to perform. Use an intent_action from the Unity capabilities manifest, or null.",
    ]
    destination: Annotated[
        str | None,
        ...,
        "Destination to move to. Use coordinates like (5, 5) or an object location like apple. Use null unless action requires a destination.",
    ]
    item: Annotated[
        str | None,
        ...,
        "Object to fetch or interact with. Use null unless action requires an item.",
    ]
    object: Annotated[
        str | None,
        ...,
        "Resolved Unity object id to execute against. Use null until Unity returns a concrete object_id.",
    ]
    steps: Annotated[
        list[CommandStep],
        ...,
        "Ordered executable intent steps extracted from the user input. Use an empty list for questions or chat.",
    ]
    message: Annotated[str, ..., "AI response message for the user."]


model = base_model.with_structured_output(CommandDict)

BASE_SYSTEM_PROMPT = """
You convert a user's natural language input into an NPC command.
Use the Unity capabilities manifest below as the source of truth for what the NPC can currently execute.

Rules:
- Return English values for action, destination, item, object, message, and all step fields.
- Use only intent_action values listed in executable_actions for physical NPC actions.
- General conversation, greetings, questions, and small talk do not require a Unity executable action. For those, return action=null, destination=null, item=null, object=null, steps=[], and answer naturally in message.
- If the user asks for a physical world action that cannot be completed with executable_actions, return no steps and explain that the required Unity capability is not available yet.
- Break executable compound requests into ordered steps. Include one step per executable user request.
- Do not reject count/all item requests. Represent them as the requested item action; the final normalization pass will expand them into repeated minimum-unit steps after Unity context is available.
- Keep step.target concise: use only the object or place name, without generic words such as location, place, position, near, or around.
- Set object=null until Unity resolves a concrete object_id.
- Keep legacy top-level fields aligned with the first executable step: move -> destination, item-targeting actions -> item, stop -> action only.

Examples:
- "사과 위치로 이동해" -> action="move", destination="apple", item=null, object=null, steps=[{"action":"move","target":"apple","object":null}]
- "사과를 가져오고 박스로 이동해" -> action="fetch", destination=null, item="apple", object=null, steps=[{"action":"fetch","target":"apple","object":null},{"action":"move","target":"box","object":null}]
- "사과를 주워" -> action="get_item", destination=null, item="apple", object=null, steps=[{"action":"get_item","target":"apple","object":null}]
- "너랑 평범한 대화가 가능한가?" -> action=null, destination=null, item=null, object=null, steps=[], message answers conversationally.
- "사다리를 만들어" -> action=null, destination=null, item=null, object=null, steps=[], message explains that Unity does not expose the required capability yet.
""".strip()


def load_unity_capabilities_text() -> str:
    try:
        capabilities = json.loads(CAPABILITIES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return '{"error":"unity_capabilities.json was not found."}'
    except json.JSONDecodeError as exc:
        return json.dumps(
            {
                "error": "unity_capabilities.json is invalid JSON.",
                "detail": str(exc),
            },
            ensure_ascii=False,
        )

    return json.dumps(capabilities, ensure_ascii=False, indent=2)


def load_object_database_text() -> str:
    try:
        object_database = json.loads(OBJECT_DATABASE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return '{"error":"object_database.json was not found."}'
    except json.JSONDecodeError as exc:
        return json.dumps(
            {
                "error": "object_database.json is invalid JSON.",
                "detail": str(exc),
            },
            ensure_ascii=False,
        )

    return json.dumps(object_database, ensure_ascii=False, indent=2)


def build_system_prompt() -> str:
    return (
        f"{BASE_SYSTEM_PROMPT}\n\n"
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
    description="FastAPI backend for the Unity 2D intelligent NPC agent MVP.",
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
    command = await parse_command(message)

    return {
        "status": "ok",
        "input": message,
        "command": command,
    }


@app.get("/unity/capabilities")
def unity_capabilities():
    try:
        return json.loads(CAPABILITIES_PATH.read_text(encoding="utf-8"))
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
    command_data = await parse_command(message)

    return {
        "status": "ok",
        "input": message,
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
                await handle_action_result(websocket, parsed_message)
                continue

            user_message = raw_message
            try:
                command_data = await parse_command(user_message)
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

            client_context = await collect_unity_context_if_needed(websocket, command_data)
            apply_resolved_object_ids(command_data, client_context)
            command_data = await normalize_to_minimal_command(user_message, command_data, client_context)
            if steps_need_object_resolution(command_data):
                normalized_context = await collect_unity_context_if_needed(websocket, command_data)
                apply_resolved_object_ids(command_data, normalized_context)
            command_data["intent_action"] = command_data.get("action")
            command_data["actions"] = build_actions(command_data)
            command_data["action"] = None
            command_data["destination"] = None
            command_data["item"] = None
            command_data["object"] = None

            await websocket.send_json(
                {
                    "type": "final_command",
                    "status": "ok",
                    "input": user_message,
                    "command": command_data,
                    "client_context": client_context,
                }
            )

    except WebSocketDisconnect:
        print("Unity client disconnected")


async def parse_command(message: str) -> dict:
    try:
        command = await model.ainvoke(
            [
                ("system", build_system_prompt()),
                ("human", message),
            ]
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OpenAI model invoke failed: {exc}") from exc

    return dict(command)


async def normalize_to_minimal_command(
    user_message: str,
    command_data: dict,
    client_context: dict | None,
) -> dict:
    steps = ensure_command_steps(command_data)
    if not steps:
        return command_data

    normalization_prompt = f"""
Rewrite the parsed NPC command into the final minimal executable step list.

Rules:
- Each step must be one minimum executable unit.
- For get_item, one step means picking up one item instance.
- For fetch, one step means one fetch request and will become MOVE_TO + GET_ITEM for one item instance.
- If the user asks for all/every matching item, repeat get_item/fetch once per matching object in Unity context.
- If the user asks for a specific count, repeat get_item/fetch min(requested_count, matching_object_count) times.
- If fewer matching objects exist than requested, only emit steps for the objects that exist.
- Preserve later user requests in order. For example, "pick up 2 apples then move to tree" becomes get_item, get_item, move.
- Use object ids from Unity context. object_id is a type id, so repeated item steps may use the same object id.
- Do not add any field outside the schema.
- Keep legacy top-level fields aligned with the first final step.

Original user message:
{user_message}

Parsed command:
{json.dumps(command_data, ensure_ascii=False)}

Unity context:
{json.dumps(client_context, ensure_ascii=False)}
""".strip()

    try:
        normalized_command = await model.ainvoke(
            [
                ("system", build_system_prompt()),
                ("human", normalization_prompt),
            ]
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OpenAI command normalization failed: {exc}") from exc

    return dict(normalized_command)


def parse_json_text(raw_message: str) -> dict | None:
    try:
        data = json.loads(raw_message)
    except json.JSONDecodeError:
        return None

    if isinstance(data, dict):
        return data

    return None


def is_client_function_result(data: dict | None) -> bool:
    return data is not None and data.get("type") == "client_function_result"


def is_action_result(data: dict | None) -> bool:
    return data is not None and data.get("type") == "action_result"


async def handle_action_result(websocket: WebSocket, action_result: dict) -> None:
    if action_result.get("status") != "failed":
        return

    command_data = await replan_after_action_failure(action_result)
    client_context = await collect_unity_context_if_needed(websocket, command_data)
    apply_resolved_object_ids(command_data, client_context)
    command_data["intent_action"] = command_data.get("action")
    command_data["actions"] = build_actions(command_data)
    command_data["action"] = None
    command_data["destination"] = None
    command_data["item"] = None
    command_data["object"] = None

    await websocket.send_json(
        {
            "type": "final_command",
            "status": "ok",
            "input": "action_result",
            "command": command_data,
            "client_context": client_context,
            "replanned_from": action_result,
        }
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


def apply_resolved_object_ids(command_data: dict, client_context: dict | None) -> None:
    if not client_context:
        return

    step_contexts = client_context.get("steps")
    if isinstance(step_contexts, list):
        steps = ensure_command_steps(command_data)
        first_object_id = None

        for step_context in step_contexts:
            if not isinstance(step_context, dict):
                continue

            step_index = step_context.get("step_index")
            if not isinstance(step_index, int) or step_index < 0 or step_index >= len(steps):
                continue

            object_id = extract_first_object_id(step_context.get("context"))
            if not object_id:
                continue

            steps[step_index]["object"] = object_id
            if first_object_id is None:
                first_object_id = object_id

        command_data["steps"] = steps
        if first_object_id:
            command_data["object"] = first_object_id

        return

    object_id = extract_first_object_id(client_context)
    if object_id:
        command_data["object"] = object_id


def extract_first_object_id(context: dict | None) -> str | None:
    if not context:
        return None

    objects = context.get("objects")
    if not isinstance(objects, list) or not objects:
        return None

    first_object = objects[0]
    if not isinstance(first_object, dict):
        return None

    object_id = first_object.get("object_id")
    if isinstance(object_id, str) and object_id.strip():
        return object_id.strip()
    if isinstance(object_id, int):
        return str(object_id)

    return None


def build_actions(command_data: dict) -> list[dict]:
    steps = ensure_command_steps(command_data)
    if steps:
        actions = []

        for step in steps:
            action = normalize_action(step.get("action"))
            object_id = step.get("object")

            if action == "stop":
                actions.append(build_action("STOP", None, len(actions) + 1))
                continue

            if not object_id:
                continue

            if action == "fetch":
                actions.extend(
                    [
                        build_action("MOVE_TO", object_id, len(actions) + 1),
                        build_action("GET_ITEM", object_id, len(actions) + 2),
                    ]
                )
            elif action == "get_item":
                actions.append(build_action("GET_ITEM", object_id, len(actions) + 1))
            elif action == "move":
                actions.append(build_action("MOVE_TO", object_id, len(actions) + 1))

        return actions

    action = normalize_action(command_data.get("action"))
    object_id = command_data.get("object")

    if action == "stop":
        return [
            build_action("STOP", None, 1),
        ]

    if action == "fetch" and object_id:
        return [
            build_action("MOVE_TO", object_id, 1),
            build_action("GET_ITEM", object_id, 2),
        ]

    if action == "get_item" and object_id:
        return [
            build_action("GET_ITEM", object_id, 1),
        ]

    if action == "move" and object_id:
        return [
            build_action("MOVE_TO", object_id, 1),
        ]

    return []


def build_action(command: str, target_id: str, index: int) -> dict:
    action = {
        "action_id": f"act_{index:03d}",
        "command": command,
    }
    if target_id is not None:
        action["target_id"] = target_id

    return action


async def collect_unity_context_if_needed(websocket: WebSocket, command_data: dict) -> dict | None:
    steps = ensure_command_steps(command_data)
    if steps:
        step_contexts = []

        for step_index, step in enumerate(steps):
            action = normalize_action(step.get("action"))
            target = get_step_target(step)
            if action not in {"move", "fetch", "get_item"} or not target:
                continue

            context = await request_unity_function(
                websocket=websocket,
                function_name="find_object",
                args={
                    "query": target,
                    "object_type": "location" if action == "move" else "item",
                    "max_results": 100 if action in {"fetch", "get_item"} else 5,
                },
            )

            step_contexts.append(
                {
                    "step_index": step_index,
                    "action": action,
                    "target": target,
                    "context": context,
                }
            )

        command_data["steps"] = steps
        return {"steps": step_contexts} if step_contexts else None

    action = normalize_action(command_data.get("action"))
    item = command_data.get("item")
    destination = command_data.get("destination")

    if action in {"fetch", "get_item"} and item:
        return await request_unity_function(
            websocket=websocket,
            function_name="find_object",
            args={
                "query": item,
                "object_type": "item",
                "max_results": 5,
            },
        )

    if action == "move" and destination:
        return await request_unity_function(
            websocket=websocket,
            function_name="find_object",
            args={
                "query": destination,
                "object_type": "location",
                "max_results": 5,
            },
        )

    return None


def ensure_command_steps(command_data: dict) -> list[dict]:
    raw_steps = command_data.get("steps")
    if isinstance(raw_steps, list) and raw_steps:
        return [step for step in raw_steps if isinstance(step, dict)]

    action = normalize_action(command_data.get("action"))
    target = first_non_empty(command_data.get("item"), command_data.get("destination"))
    if action in {"move", "fetch", "get_item"} and target:
        return [
            {
                "action": action,
                "target": target,
                "object": command_data.get("object"),
            }
        ]

    if action == "stop":
        return [
            {
                "action": action,
                "target": None,
                "object": None,
            }
        ]

    return []


def steps_need_object_resolution(command_data: dict) -> bool:
    for step in ensure_command_steps(command_data):
        action = normalize_action(step.get("action"))
        if action in {"move", "fetch", "get_item"} and get_step_target(step) and not step.get("object"):
            return True

    return False


def get_step_target(step: dict) -> str | None:
    return first_non_empty(step.get("target"), step.get("item"), step.get("destination"))


def normalize_action(action: object) -> str | None:
    if not isinstance(action, str):
        return None

    normalized = action.strip().lower()
    if normalized in {"", "null", "none", "no_action"}:
        return None

    return normalized


def first_non_empty(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None


async def request_unity_function(
    websocket: WebSocket,
    function_name: str,
    args: dict,
    timeout_seconds: float = 5.0,
) -> dict | None:
    call_id = f"call_{uuid.uuid4().hex}"

    await websocket.send_json(
        {
            "type": "client_function_call",
            "call_id": call_id,
            "function": function_name,
            "args": args,
        }
    )

    try:
        raw_response = await asyncio.wait_for(websocket.receive_text(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return {
            "ok": False,
            "error": {
                "code": "CLIENT_FUNCTION_TIMEOUT",
                "message": f"Unity did not respond to {function_name} within {timeout_seconds} seconds.",
            },
        }

    response = parse_json_text(raw_response)
    if not is_client_function_result(response):
        return {
            "ok": False,
            "error": {
                "code": "INVALID_CLIENT_FUNCTION_RESULT",
                "message": "Unity response was not a client_function_result JSON message.",
            },
        }

    if response.get("call_id") != call_id:
        return {
            "ok": False,
            "error": {
                "code": "CLIENT_FUNCTION_CALL_ID_MISMATCH",
                "message": "Unity response call_id did not match the pending request.",
            },
        }

    payload = response.get("payload")
    if isinstance(payload, dict):
        if payload.get("ok") is False:
            return {
                "ok": False,
                "error": payload.get("error"),
            }

        return payload.get("result")

    return response.get("result")


def main():
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
