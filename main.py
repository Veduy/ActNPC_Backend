from fastapi import Body, FastAPI, HTTPException, Query

import os
from langchain.chat_models import init_chat_model
from dotenv import load_dotenv
from typing_extensions import Annotated, TypedDict
from mcp_tools import async_call_action_tool, build_act_path

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
    message: Annotated[str, ..., "AI response message for the user."]


model = base_model.with_structured_output(CommandDict)

SYSTEM_PROMPT = """
You convert a user's natural language input into an NPC command.
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
    try:
        command = await model.ainvoke(
            [
                ("system", SYSTEM_PROMPT),
                ("human", message),
            ]
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OpenAI model invoke failed: {exc}") from exc

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
    try:
        command_dict = await model.ainvoke(
            [
                ("system", SYSTEM_PROMPT),
                ("human", message),
            ]
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OpenAI model invoke failed: {exc}") from exc

    command_data = dict(command_dict)
    act_path = build_act_path(command_data)
    unity_result = await async_call_action_tool(command_data)

    return {
        "status": "ok",
        "input": message,
        "command": command_data,
        "act_path": act_path,
        "unity_result": unity_result,
    }


def main():
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
