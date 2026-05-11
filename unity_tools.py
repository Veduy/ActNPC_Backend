import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import WebSocket


CAPABILITIES_PATH = Path(__file__).with_name("unity_capabilities.json")
OBJECT_DATABASE_PATH = Path(__file__).with_name("object_database.json")


def load_unity_capabilities() -> dict:
    return json.loads(CAPABILITIES_PATH.read_text(encoding="utf-8"))


def load_unity_capabilities_text() -> str:
    try:
        capabilities = load_unity_capabilities()
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


async def handle_action_result(
    websocket: WebSocket,
    action_result: dict,
    replan_action_failure: Callable[[dict], Awaitable[dict]],
) -> None:
    if action_result.get("status") != "failed":
        return

    command_data = await replan_action_failure(action_result)
    client_context = await collect_unity_context_if_needed(websocket, command_data)
    apply_resolved_object_ids(command_data, client_context)
    finalize_unity_command(command_data)

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


def finalize_unity_command(command_data: dict) -> dict:
    command_data["intent_action"] = command_data.get("action")
    command_data["actions"] = build_actions(command_data)
    command_data["action"] = None
    command_data["destination"] = None
    command_data["item"] = None
    command_data["object"] = None
    return command_data


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

            object_id = extract_context_target_id(step_context.get("context"), step_context.get("target"))
            if not object_id:
                continue

            steps[step_index]["object_id"] = object_id
            steps[step_index]["object"] = object_id
            if first_object_id is None:
                first_object_id = object_id

        command_data["steps"] = steps
        if first_object_id:
            command_data["object_id"] = first_object_id
            command_data["object"] = first_object_id

        return

    object_id = extract_context_target_id(client_context, get_command_target_name(command_data))
    if object_id:
        command_data["object_id"] = object_id
        command_data["object"] = object_id


def extract_context_target_id(context: dict | None, target: object = None) -> str | None:
    object_id = extract_first_object_id(context)
    if object_id:
        return object_id

    return extract_inventory_item_id(context, target)


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


def extract_inventory_item_id(context: dict | None, target: object = None) -> str | None:
    if not context:
        return None

    inventory = context.get("inventory")
    if not isinstance(inventory, list) or not inventory:
        return None

    normalized_target = str(target).strip().lower() if target is not None else ""
    first_item_id = None

    for item in inventory:
        if not isinstance(item, dict):
            continue

        item_id = item.get("itemId")
        item_name = item.get("itemName")
        item_id_text = str(item_id).strip() if item_id is not None else ""
        if first_item_id is None and item_id_text:
            first_item_id = item_id_text

        if not normalized_target:
            continue

        if item_id_text.lower() == normalized_target:
            return item_id_text
        if isinstance(item_name, str) and item_name.strip().lower() == normalized_target:
            return item_id_text

    return first_item_id if not normalized_target else None


def build_actions(command_data: dict) -> list[dict]:
    steps = ensure_command_steps(command_data)
    if steps:
        actions = []

        for step in steps:
            action = normalize_action(step.get("action"))
            object_id = get_step_object_id(step)
            target = get_step_target(step)

            if action == "stop":
                actions.append(build_action("STOP", None, len(actions) + 1))
                continue

            if action == "put_item" and not object_id:
                object_id = target

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
            elif action == "put_item":
                actions.append(build_action("PUT_ITEM", object_id, len(actions) + 1))
            elif action == "move":
                actions.append(build_action("MOVE_TO", object_id, len(actions) + 1))

        return actions

    action = normalize_action(command_data.get("action"))
    object_id = get_command_object_id(command_data)
    target = get_command_target_name(command_data)
    if action == "put_item" and not object_id:
        object_id = target

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

    if action == "put_item" and object_id:
        return [
            build_action("PUT_ITEM", object_id, 1),
        ]

    if action == "move" and object_id:
        return [
            build_action("MOVE_TO", object_id, 1),
        ]

    return []


def build_action(command: str, target_id: str | None, index: int) -> dict:
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
            if action == "put_item":
                continue
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
    item = first_non_empty(command_data.get("object_name"), command_data.get("item"))
    destination = first_non_empty(command_data.get("object_name"), command_data.get("destination"))

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
        return expand_counted_steps([step for step in raw_steps if isinstance(step, dict)])

    action = normalize_action(command_data.get("action"))
    target = get_command_target_name(command_data)
    if action in {"move", "fetch", "get_item", "put_item"} and target:
        return [
            {
                "action": action,
                "target": target,
                "object": get_command_object_id(command_data),
                "object_name": target,
                "object_id": get_command_object_id(command_data),
                "position": command_data.get("position"),
                "count": None,
            }
        ]

    if action == "stop":
        return [
            {
                "action": action,
                "target": None,
                "object": None,
                "object_name": None,
                "object_id": None,
                "position": None,
                "count": None,
            }
        ]

    return []


def expand_counted_steps(steps: list[dict]) -> list[dict]:
    expanded_steps = []

    for step in steps:
        action = normalize_action(step.get("action"))
        repeat_count = get_step_count(step) if action in {"fetch", "get_item", "put_item"} else 1

        for _ in range(repeat_count):
            expanded_step = dict(step)
            if repeat_count > 1:
                expanded_step["count"] = 1
            expanded_steps.append(expanded_step)

    return expanded_steps


def get_step_count(step: dict) -> int:
    count = step.get("count")
    if isinstance(count, int) and count > 0:
        return min(count, 100)

    return 1


def steps_need_object_resolution(command_data: dict) -> bool:
    for step in ensure_command_steps(command_data):
        action = normalize_action(step.get("action"))
        if action == "put_item":
            continue
        if action in {"move", "fetch", "get_item"} and get_step_target(step) and not get_step_object_id(step):
            return True

    return False


def get_step_target(step: dict) -> str | None:
    return first_non_empty(step.get("object_name"), step.get("target"), step.get("item"), step.get("destination"))


def get_step_object_id(step: dict) -> str | None:
    return first_non_empty(step.get("object_id"), step.get("object"))


def get_command_target_name(command_data: dict) -> str | None:
    return first_non_empty(command_data.get("object_name"), command_data.get("item"), command_data.get("destination"))


def get_command_object_id(command_data: dict) -> str | None:
    return first_non_empty(command_data.get("object_id"), command_data.get("object"))


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
