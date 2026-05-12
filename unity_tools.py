import asyncio
import json
import time
import uuid
from pathlib import Path

from fastapi import WebSocket

from debug_events import TOOL_EVENT_HUB


CAPABILITIES_PATH = Path(__file__).with_name("unity_capabilities.json")
OBJECT_DATABASE_PATH = Path(__file__).with_name("object_database.json")


class UnityToolSession:
    def __init__(self, websocket: WebSocket, timeout_seconds: float = 5.0):
        self.websocket = websocket
        self.timeout_seconds = timeout_seconds
        self.request_lock = asyncio.Lock()

    async def request(self, function_name: str, args: dict) -> dict:
        async with self.request_lock:
            call_id = f"call_{uuid.uuid4().hex}"
            started_at = time.perf_counter()
            await TOOL_EVENT_HUB.publish(
                "tool_call",
                {
                    "call_id": call_id,
                    "function": function_name,
                    "args": args,
                },
            )

            await self.websocket.send_json(
                {
                    "type": "client_function_call",
                    "call_id": call_id,
                    "function": function_name,
                    "args": args,
                }
            )

            response = await self._receive_matching_response(call_id)
            result = response.get("result")
            if isinstance(result, dict):
                await TOOL_EVENT_HUB.publish(
                    "tool_result",
                    {
                        "call_id": call_id,
                        "function": function_name,
                        "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                        "result": result,
                    },
                )
                return result

            error_result = {
                "ok": False,
                "error": {
                    "code": "INVALID_CLIENT_FUNCTION_RESULT",
                    "message": f"Unity returned no result for {function_name}.",
                },
            }
            await TOOL_EVENT_HUB.publish(
                "tool_result",
                {
                    "call_id": call_id,
                    "function": function_name,
                    "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "result": error_result,
                },
            )
            return error_result

    async def _receive_matching_response(self, call_id: str) -> dict:
        deadline = asyncio.get_running_loop().time() + self.timeout_seconds

        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return {
                    "type": "client_function_result",
                    "call_id": call_id,
                    "result": {
                        "ok": False,
                        "error": {
                            "code": "CLIENT_FUNCTION_TIMEOUT",
                            "message": f"Unity did not respond to {call_id} within {self.timeout_seconds} seconds.",
                        },
                    },
                }

            try:
                raw_response = await asyncio.wait_for(self.websocket.receive_text(), timeout=remaining)
            except asyncio.TimeoutError:
                return {
                    "type": "client_function_result",
                    "call_id": call_id,
                    "result": {
                        "ok": False,
                        "error": {
                            "code": "CLIENT_FUNCTION_TIMEOUT",
                            "message": f"Unity did not respond to {call_id} within {self.timeout_seconds} seconds.",
                        },
                    },
                }

            try:
                response = json.loads(raw_response)
            except json.JSONDecodeError:
                continue

            if (
                isinstance(response, dict)
                and response.get("type") == "client_function_result"
                and response.get("call_id") == call_id
            ):
                return response


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
