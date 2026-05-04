from fastapi import Body, FastAPI, HTTPException, Query

import os
import asyncio
import json
import uuid
from fastapi import WebSocket, WebSocketDisconnect
from langchain.chat_models import init_chat_model
from dotenv import load_dotenv
from typing_extensions import Annotated, TypedDict

load_dotenv()

# model setting
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
base_model = init_chat_model("gpt-4.1")


class CommandDict(TypedDict):
    """User natural language command converted into a command for one NPC."""

    action: Annotated[
        str | None,
        ...,
        "Action to perform. Use move or fetch only when the user clearly asks the NPC to act. Use null for questions, chat, explanations, or information requests.",
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
    message: Annotated[str, ..., "AI response message for the user."]


model = base_model.with_structured_output(CommandDict)

SYSTEM_PROMPT = """
You convert a user's natural language input into an NPC command.
Always translate the user's input and all command field values into English, regardless of the input language.

Rules:
- action must be one of: move, fetch, null.
- For movement commands, destination must be the target object or place name only.
- Do not include generic words like "location", "place", "position", "area", "near", "around", or "spot" in destination unless they are part of an actual proper noun.
- If the user says "the location of X", "X location", "near X", or "go to X's position", set destination to X only.
- Example: "사과 위치로 이동해" -> action="move", destination="apple", item=null, object=null, message="I will move to the apple."
- Example: "go to the apple location" -> action="move", destination="apple", item=null, object=null, message="I will move to the apple."
- Use object=null until Unity returns a concrete Unity object_id.
- Return English values for action, destination, object, item, and message.
""".strip()


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
            apply_first_object_id(command_data, client_context)

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
                ("system", SYSTEM_PROMPT),
                ("human", message),
            ]
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OpenAI model invoke failed: {exc}") from exc

    return dict(command)


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


def apply_first_object_id(command_data: dict, client_context: dict | None) -> None:
    if not client_context:
        return

    objects = client_context.get("objects")
    if not isinstance(objects, list) or not objects:
        return

    first_object = objects[0]
    if not isinstance(first_object, dict):
        return

    object_id = first_object.get("object_id")
    if isinstance(object_id, str) and object_id.strip():
        command_data["object"] = object_id.strip()


async def collect_unity_context_if_needed(websocket: WebSocket, command_data: dict) -> dict | None:
    action = command_data.get("action")
    item = command_data.get("item")
    destination = command_data.get("destination")

    if action == "fetch" and item:
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
