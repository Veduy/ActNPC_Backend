import json
from pathlib import Path


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
