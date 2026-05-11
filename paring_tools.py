import json
import os
import re
from pathlib import Path
from string import Template

from dotenv import load_dotenv
from fastapi import HTTPException
from langchain.chat_models import init_chat_model

from command_schema import CommandDict
from unity_tools import (
    ensure_command_actions,
    load_object_database_text,
    load_unity_capabilities_text,
)


load_dotenv()
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

MODEL_NAME = "gpt-4.1-nano"
MODEL_PRICING_PER_1M_TOKENS = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
}
PROMPTS_DIR = Path(__file__).with_name("prompts")
COMMAND_PARSER_PROMPT_PATH = PROMPTS_DIR / "command_parser_system.md"
COMMAND_NORMALIZER_PROMPT_PATH = PROMPTS_DIR / "command_normalizer.md"

base_model = init_chat_model(MODEL_NAME)
model = base_model.with_structured_output(CommandDict, include_raw=True)


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
        "```\n\n"
        "Object database. Use these object_id values for known targets. Unity treats object_id as an object type id; multiple scene instances may share one object_id, and Unity will choose the nearest matching scene instance at execution time:\n"
        "```json\n"
        f"{load_object_database_text()}\n"
        "```"
    )


async def parse_command(message: str) -> dict:
    try:
        result = await model.ainvoke(
            [
                ("system", build_system_prompt()),
                ("human", message),
            ]
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OpenAI model invoke failed: {exc}") from exc

    return extract_structured_command(result, "parse_command")


async def normalize_to_minimal_command(
    user_message: str,
    command_data: dict,
    client_context: dict | None,
) -> dict:
    actions = ensure_command_actions(command_data)
    if not actions:
        return command_data
    if not needs_minimal_normalization(user_message, actions):
        return command_data

    normalization_prompt = build_normalization_prompt(user_message, command_data, client_context)

    try:
        result = await model.ainvoke(
            [
                ("system", load_prompt(COMMAND_NORMALIZER_PROMPT_PATH)),
                ("human", normalization_prompt),
            ]
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OpenAI command normalization failed: {exc}") from exc

    return extract_structured_command(result, "normalize_to_minimal_command")


def build_normalization_prompt(user_message: str, command_data: dict, client_context: dict | None) -> str:
    return Template(
        "Original:\n"
        "$user_message\n\n"
        "Parsed:\n"
        "$command_data_json\n\n"
        "Unity context:\n"
        "$client_context_json"
    ).safe_substitute(
        user_message=user_message,
        command_data_json=json.dumps(command_data, ensure_ascii=False),
        client_context_json=json.dumps(client_context, ensure_ascii=False),
    )


def needs_minimal_normalization(user_message: str, actions: list[dict]) -> bool:
    return has_all_items_request(user_message)


def has_all_items_request(message: str) -> bool:
    normalized = message.strip().lower()
    if re.search(r"\b(all|every|everything|each)\b", normalized):
        return True

    return any(keyword in normalized for keyword in ("전부", "모두", "전체", "모든", "있는", "싹"))


def extract_structured_command(result, operation: str) -> dict:
    return extract_structured_output(result, operation, MODEL_NAME)


def extract_structured_output(result, operation: str, model_name: str) -> dict:
    if isinstance(result, dict) and "parsed" in result:
        parsing_error = result.get("parsing_error")
        if parsing_error:
            raise HTTPException(status_code=503, detail=f"{operation} structured output parsing failed: {parsing_error}")

        raw_response = result.get("raw")
        usage = getattr(raw_response, "usage_metadata", None)
        if usage:
            log_model_usage_cost(operation, usage, model_name)

        parsed = result.get("parsed")
    else:
        parsed = result

    if parsed is None:
        raise HTTPException(status_code=503, detail=f"{operation} returned no parsed command.")

    return dict(parsed)


def log_model_usage_cost(operation: str, usage: dict, model_name: str) -> None:
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    total_tokens = usage.get("total_tokens", input_tokens + output_tokens)
    pricing = MODEL_PRICING_PER_1M_TOKENS.get(model_name)

    if pricing is None:
        print(
            f"{operation} usage/cost: model={model_name}, "
            f"input_tokens={input_tokens}, output_tokens={output_tokens}, "
            f"total_tokens={total_tokens}, cost_usd=price_unknown"
        )
        return

    input_cost = input_tokens / 1_000_000 * pricing["input"]
    output_cost = output_tokens / 1_000_000 * pricing["output"]
    total_cost = input_cost + output_cost

    print(
        f"{operation} usage/cost: model={model_name}, "
        f"input_tokens={input_tokens}, output_tokens={output_tokens}, "
        f"total_tokens={total_tokens}, input_cost_usd=${input_cost:.8f}, "
        f"output_cost_usd=${output_cost:.8f}, total_cost_usd=${total_cost:.8f}"
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
