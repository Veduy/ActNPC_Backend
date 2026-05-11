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
    command_data["actions"] = build_actions(command_data)
    return command_data


def apply_resolved_object_ids(command_data: dict, client_context: dict | None) -> None:
    if not client_context:
        return

    action_contexts = client_context.get("actions")
    if isinstance(action_contexts, list):
        actions = ensure_command_actions(command_data)

        for action_context in action_contexts:
            if not isinstance(action_context, dict):
                continue

            action_index = action_context.get("action_index")
            if not isinstance(action_index, int) or action_index < 0 or action_index >= len(actions):
                continue

            object_id = extract_context_target_id(action_context.get("context"), action_context.get("target"))
            if not object_id:
                continue

            actions[action_index]["object_id"] = object_id

        command_data["actions"] = actions


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
    return ensure_command_actions(command_data)


def build_action(
    command: str,
    object_name: str | None,
    object_id: str | None,
    position: dict | None,
    index: int,
) -> dict:
    return {
        "action_id": f"act_{index:03d}",
        "command": command,
        "object_name": object_name,
        "object_id": object_id,
        "position": position,
    }


async def collect_unity_context_if_needed(websocket: WebSocket, command_data: dict) -> dict | None:
    actions = ensure_command_actions(command_data)
    if actions:
        action_contexts = []

        for action_index, action_data in enumerate(actions):
            command = normalize_queue_command(action_data.get("command"))
            target = get_action_target(action_data)
            if command == "PUT_ITEM":
                continue
            if command not in {"MOVE_TO", "GET_ITEM"} or not target:
                continue

            context = await request_unity_function(
                websocket=websocket,
                function_name="find_object",
                args={
                    "query": target,
                    "object_type": "location" if command == "MOVE_TO" else "item",
                    "max_results": 100 if command == "GET_ITEM" else 5,
                },
            )

            action_contexts.append(
                {
                    "action_index": action_index,
                    "command": command,
                    "target": target,
                    "context": context,
                }
            )

        command_data["actions"] = actions
        return {"actions": action_contexts} if action_contexts else None

    return None


def ensure_command_actions(command_data: dict) -> list[dict]:
    raw_actions = command_data.get("actions")
    if not isinstance(raw_actions, list):
        return []

    actions = []
    for raw_action in raw_actions:
        if not isinstance(raw_action, dict):
            continue

        command = normalize_action_command(raw_action.get("command"))
        if command == "FETCH":
            object_name = get_action_target(raw_action)
            object_id = get_action_object_id(raw_action)
            position = raw_action.get("position") if isinstance(raw_action.get("position"), dict) else None
            actions.append(build_action("MOVE_TO", object_name, object_id, position, len(actions) + 1))
            actions.append(build_action("GET_ITEM", object_name, object_id, position, len(actions) + 1))
            continue
        if not command:
            continue

        object_name = get_action_target(raw_action)
        object_id = get_action_object_id(raw_action)
        position = raw_action.get("position") if isinstance(raw_action.get("position"), dict) else None
        actions.append(build_action(command, object_name, object_id, position, len(actions) + 1))

    return actions


def actions_need_object_resolution(command_data: dict) -> bool:
    for action_data in ensure_command_actions(command_data):
        command = normalize_queue_command(action_data.get("command"))
        if command == "PUT_ITEM":
            continue
        if command in {"MOVE_TO", "GET_ITEM"} and get_action_target(action_data) and not get_action_object_id(action_data):
            return True

    return False


def get_action_target(action_data: dict) -> str | None:
    return first_non_empty(action_data.get("object_name"))


def get_action_object_id(action_data: dict) -> str | None:
    return first_non_empty(action_data.get("object_id"))


def normalize_action_command(command: object) -> str | None:
    normalized = normalize_queue_command(command)
    if normalized in {"MOVE", "MOVE_TO"}:
        return "MOVE_TO"
    if normalized in {"FETCH", "BRING", "RETRIEVE"}:
        return "FETCH"
    if normalized in {"GET_ITEM", "GET", "PICK_UP", "PICKUP", "COLLECT", "TAKE"}:
        return "GET_ITEM"
    if normalized in {"PUT_ITEM", "PUT_DOWN", "DROP", "PLACE"}:
        return "PUT_ITEM"
    if normalized == "STOP":
        return "STOP"

    return None


def normalize_queue_command(command: object) -> str | None:
    if not isinstance(command, str):
        return None

    normalized = command.strip().upper()
    if normalized in {"", "NULL", "NONE", "NO_ACTION"}:
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
