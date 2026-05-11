import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import HTTPException
from langchain.chat_models import init_chat_model

from command_schema import CommandDict
from unity_tools import load_unity_capabilities_text


load_dotenv()
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

MODEL_NAME = "gpt-4.1-nano"
PROMPTS_DIR = Path(__file__).with_name("prompts")
COMMAND_PARSER_PROMPT_PATH = PROMPTS_DIR / "command_parser_system.md"

base_model = init_chat_model(MODEL_NAME)
command_dict_model = base_model.with_structured_output(CommandDict)


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
        "```"
    )


async def parse_command(message: str) -> dict:
    try:
        result = await command_dict_model.ainvoke(
            [
                ("system", build_system_prompt()),
                ("human", message),
            ]
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OpenAI model invoke failed: {exc}") from exc

    return dict(result)
