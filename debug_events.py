import asyncio
import json
from collections import deque
from datetime import UTC, datetime
from typing import Any


class ToolEventHub:
    def __init__(self, history_limit: int = 100):
        self.history = deque(maxlen=history_limit)
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.next_event_id = 1

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "id": self.next_event_id,
            "type": event_type,
            "created_at": datetime.now(UTC).isoformat(),
            "payload": payload,
        }
        self.next_event_id += 1
        self.history.append(event)

        for queue in list(self.subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                queue.put_nowait(event)

    async def subscribe(self):
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        for event in self.history:
            queue.put_nowait(event)

        self.subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self.subscribers.discard(queue)


def format_sse(event: dict[str, Any]) -> str:
    data = json.dumps(event, ensure_ascii=False)
    return f"id: {event['id']}\nevent: {event['type']}\ndata: {data}\n\n"


TOOL_EVENT_HUB = ToolEventHub()
