from fastapi import FastAPI, HTTPException

import json
import os
from pathlib import Path
from typing import Literal
from uuid import uuid4
from fastapi import Request
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from langchain.chat_models import init_chat_model
from dotenv import load_dotenv
from typing_extensions import Annotated, TypedDict

from debug_events import TOOL_EVENT_HUB, format_sse
from memory_store import MEMORY_STORE, SessionMemory
from planner_agent import plan_command
from unity_tools import UnityToolSession

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


@app.get("/debug/tool-events")
async def debug_tool_events(request: Request):
    async def event_generator():
        async for event in TOOL_EVENT_HUB.subscribe():
            if await request.is_disconnected():
                break
            yield format_sse(event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/debug/tool-events/view", response_class=HTMLResponse)
def debug_tool_events_view():
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ActNPC Tool Events</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f4f6f8;
      color: #17202a;
    }
    body { margin: 0; }
    header {
      position: sticky;
      top: 0;
      z-index: 1;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 18px;
      border-bottom: 1px solid #d9dee5;
      background: rgba(255, 255, 255, 0.94);
      backdrop-filter: blur(8px);
    }
    h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 650;
    }
    #status {
      min-width: 110px;
      border-radius: 999px;
      padding: 5px 10px;
      background: #e8eef7;
      color: #31537a;
      font-size: 13px;
      text-align: center;
    }
    main {
      max-width: 1120px;
      margin: 0 auto;
      padding: 18px;
    }
    #empty {
      padding: 40px 0;
      color: #667085;
      text-align: center;
    }
    #events {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .event {
      display: grid;
      grid-template-columns: 150px 120px 1fr;
      gap: 14px;
      align-items: start;
      border: 1px solid #d9dee5;
      border-radius: 8px;
      padding: 12px;
      background: #ffffff;
      box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
    }
    .time {
      color: #667085;
      font-size: 13px;
      white-space: nowrap;
    }
    .badge {
      width: fit-content;
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 12px;
      font-weight: 650;
      letter-spacing: 0;
    }
    .tool_call {
      background: #fff4cc;
      color: #7a5b00;
    }
    .tool_result {
      background: #dcfce7;
      color: #166534;
    }
    .summary {
      margin-bottom: 8px;
      font-weight: 650;
      overflow-wrap: anywhere;
    }
    pre {
      margin: 0;
      max-height: 260px;
      overflow: auto;
      border-radius: 6px;
      padding: 10px;
      background: #0f172a;
      color: #e5e7eb;
      font-size: 12px;
      line-height: 1.5;
    }
    @media (max-width: 760px) {
      .event { grid-template-columns: 1fr; }
      .time { white-space: normal; }
    }
  </style>
</head>
<body>
  <header>
    <h1>ActNPC Tool Events</h1>
    <div id="status">connecting</div>
  </header>
  <main>
    <div id="empty">Waiting for planner tool calls...</div>
    <div id="events"></div>
  </main>
  <script>
    const statusNode = document.getElementById("status");
    const emptyNode = document.getElementById("empty");
    const eventsNode = document.getElementById("events");
    const source = new EventSource("/debug/tool-events");

    source.onopen = () => {
      statusNode.textContent = "connected";
    };

    source.onerror = () => {
      statusNode.textContent = "reconnecting";
    };

    source.addEventListener("tool_call", appendEvent);
    source.addEventListener("tool_result", appendEvent);

    function appendEvent(message) {
      const event = JSON.parse(message.data);
      const payload = event.payload || {};
      const row = document.createElement("article");
      row.className = "event";

      const time = document.createElement("div");
      time.className = "time";
      time.textContent = new Date(event.created_at).toLocaleTimeString();

      const badge = document.createElement("div");
      badge.className = `badge ${event.type}`;
      badge.textContent = event.type;

      const detail = document.createElement("div");
      const summary = document.createElement("div");
      summary.className = "summary";
      summary.textContent = summarize(event.type, payload);

      const json = document.createElement("pre");
      json.textContent = JSON.stringify(payload, null, 2);

      detail.append(summary, json);
      row.append(time, badge, detail);
      eventsNode.prepend(row);
      emptyNode.style.display = "none";

      while (eventsNode.children.length > 200) {
        eventsNode.removeChild(eventsNode.lastChild);
      }
    }

    function summarize(type, payload) {
      if (type === "tool_call") {
        return `${payload.function || "tool"} called`;
      }
      const result = payload.result || {};
      const status = result.ok === false ? "failed" : "returned";
      const elapsed = payload.elapsed_ms == null ? "" : ` in ${payload.elapsed_ms}ms`;
      return `${payload.function || "tool"} ${status}${elapsed}`;
    }
  </script>
</body>
</html>
"""


@app.websocket("/ws/agent")
async def websocket_agent(websocket: WebSocket):
    await websocket.accept()
    session_id = f"session_{uuid4().hex}"
    memory = MEMORY_STORE.get_or_create(session_id)

    try:
        while True:
            user_message = await websocket.receive_text()
            memory.append_message("user", user_message)
            try:
                input_route, command_data = await handle_websocket_user_input(websocket, user_message, memory)
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
                await memory.summarize_if_needed(summarize_memory)
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
            memory.append_message("assistant", command_data.get("message", ""))
            memory.remember_command(command_data)
            await memory.summarize_if_needed(summarize_memory)

    except WebSocketDisconnect:
        print("Unity client disconnected")
    finally:
        MEMORY_STORE.delete(session_id)


async def handle_websocket_user_input(websocket: WebSocket, message: str, memory: SessionMemory) -> tuple[dict, dict]:
    input_route = await route_input(message)
    selected_route = input_route.get("route")

    if selected_route == "dialogue":
        return input_route, await build_dialogue_command(message, memory.build_dialogue_context())
    if selected_route == "command":
        planned_command = await plan_command(UnityToolSession(websocket), message, memory.build_planner_context())
        return input_route, planned_command

    return input_route, build_noop_command("\uc785\ub825 \uc758\ub3c4\ub97c \ubd84\ub958\ud558\uc9c0 \ubabb\ud588\uc5b4\uc694.")

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
    memory_context: dict,
) -> dict:
    system_prompt = (
        "You are a friendly Unity NPC. Answer questions and small talk in Korean. "
        "Use the conversation memory only to maintain continuity. "
        "Do not claim that you performed any physical action. "
        "Use casual Korean speech, not honorifics. "
        "End every Korean sentence with 냥."
    )
    user_payload = {
        "memory": memory_context,
        "user_message": message,
    }

    try:
        result = await input_router_base_model.ainvoke(
            [
                ("system", system_prompt),
                ("human", json.dumps(user_payload, ensure_ascii=False)),
            ]
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OpenAI dialogue invoke failed: {exc}") from exc

    return build_noop_command(getattr(result, "content", None))


async def summarize_memory(existing_summary: str, messages: list[dict[str, str]]) -> str:
    system_prompt = (
        "Summarize Unity NPC conversation memory in Korean. "
        "Keep stable facts, user preferences, unresolved references, and recent task context. "
        "Be concise and do not invent details."
    )
    user_payload = {
        "existing_summary": existing_summary,
        "messages_to_merge": messages,
    }

    try:
        result = await input_router_base_model.ainvoke(
            [
                ("system", system_prompt),
                ("human", json.dumps(user_payload, ensure_ascii=False)),
            ]
        )
    except Exception as exc:
        print(f"OpenAI memory summary invoke failed: {exc}")
        return existing_summary

    content = getattr(result, "content", "")
    if isinstance(content, str) and content.strip():
        return content.strip()

    return existing_summary


def build_noop_command(message: object) -> dict:
    use_default_message = not isinstance(message, str) or not message.strip()
    if not isinstance(message, str) or not message.strip():
        message = "지금은 실행할 명령이 없어요."

    return {
        "actions": [],
        "message": "\uc9c0\uae08\uc740 \uc2e4\ud589\ud560 \uba85\ub839\uc774 \uc5c6\uc5b4\uc694." if use_default_message else message,
    }
def main():
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
