from copy import deepcopy
from dataclasses import dataclass, field
from typing import Awaitable, Callable


SummarizeCallback = Callable[[str, list[dict[str, str]]], Awaitable[str]]


@dataclass
class SessionMemory:
    summary: str = ""
    recent_messages: list[dict[str, str]] = field(default_factory=list)
    last_command: dict | None = None
    max_recent_messages: int = 5

    def append_message(self, role: str, content: object) -> None:
        if not isinstance(content, str) or not content.strip():
            return

        self.recent_messages.append(
            {
                "role": role,
                "content": content.strip(),
            }
        )

    def remember_command(self, command: dict) -> None:
        self.last_command = deepcopy(command)

    async def summarize_if_needed(self, summarize: SummarizeCallback) -> None:
        overflow_count = len(self.recent_messages) - self.max_recent_messages
        if overflow_count <= 0:
            return

        messages_to_summarize = self.recent_messages[:overflow_count]
        self.recent_messages = self.recent_messages[overflow_count:]
        self.summary = await summarize(self.summary, messages_to_summarize)

    def build_dialogue_context(self) -> dict:
        return {
            "summary": self.summary,
            "recent_messages": deepcopy(self.recent_messages),
        }

    def build_planner_context(self) -> dict:
        return {
            "summary": self.summary,
            "recent_messages": deepcopy(self.recent_messages),
            "last_command": deepcopy(self.last_command),
        }


class MemoryStore:
    def __init__(self):
        self.sessions: dict[str, SessionMemory] = {}

    def get_or_create(self, session_id: str) -> SessionMemory:
        memory = self.sessions.get(session_id)
        if memory is None:
            memory = SessionMemory()
            self.sessions[session_id] = memory
        return memory

    def delete(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)


MEMORY_STORE = MemoryStore()
