from typing import Any
from urllib.parse import quote
import httpx


UNITY_BASE_URL = "http://localhost:9000"
DEFAULT_TIMEOUT_SECONDS = 10


def build_act_path(command: dict[str, Any]) -> str | None:
    action = command.get("action")
    if action is None:
        return None

    if action == "fetch":
        item = command.get("item")
        return f"fetch/{item}" if item else None

    if action == "move":
        destination = command.get("destination")
        return f"move/{destination}" if destination else None

    return str(action)


async def async_request_npc_act(
    act_path: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    if not act_path or not act_path.strip("/"):
        return {
            "status": "error",
            "success": False,
            "message": "act_path is required.",
        }

    encoded_act_path = quote(act_path.strip("/"), safe="/")
    url = f"{UNITY_BASE_URL}/npc/act/{encoded_act_path}"

    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={"Accept": "application/json", "Connection": "close"},
        ) as client:
            response = await client.get(url)
    except httpx.TimeoutException:
        return {
            "status": "error",
            "success": False,
            "message": "Unity local HTTP server request timed out.",
            "url": url,
        }
    except httpx.RequestError as exc:
        return {
            "status": "error",
            "success": False,
            "message": f"Unity local HTTP server request failed: {exc}",
            "url": url,
        }

    try:
        result = response.json()
    except ValueError:
        result = {
            "status": "error",
            "success": False,
            "message": response.text,
        }

    result["http_status"] = response.status_code
    result["url"] = url
    return result


async def async_call_action_tool(command: dict[str, Any]) -> dict[str, Any] | None:
    act_path = build_act_path(command)
    if act_path is None:
        return None

    return await async_request_npc_act(act_path)
