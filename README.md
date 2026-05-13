# ActNPC - 자연어 기반 Unity NPC 제어 시스템

ActNPC는 플레이어의 자연어 입력을 LLM이 Unity 실행 명령으로 변환하고, Unity NPC가 해당 명령을 실제 게임 월드 액션으로 실행하는 프로토타입입니다. 백엔드는 자연어 해석, 명령 계획, Unity 상태 조회 요청을 담당하고, Unity 클라이언트는 상태 조회 응답과 최종 액션 실행을 담당합니다.

## Unity Project

- [ActNPC Unity Project](https://github.com/Veduy/ActNPC.git)

## Core Idea

- 자연어 입력을 바로 실행하지 않고, 먼저 대화와 실행 명령으로 분류합니다.
- 실행 명령은 LLM이 정해진 JSON 명령 스키마로 변환합니다.
- LLM이 임의로 대상을 추측하지 않도록 Unity 상태 조회 결과와 허용 오브젝트 목록을 사용합니다.
- Unity는 백엔드가 보낸 최종 명령만 받아 NPC 액션 큐에서 순차 실행합니다.

## Architecture

```text
Unity Input
  -> WebSocket
  -> FastAPI
  -> Input Router
  -> Planner Agent
  -> Unity Tool Call
  -> Command JSON
  -> NPC Action Queue
```

백엔드는 플레이어 입력을 받은 뒤 먼저 대화인지 명령인지 분류합니다. 명령으로 판단되면 LLM 플래너가 Unity에 필요한 상태 조회를 요청하고, 그 결과를 바탕으로 실행 가능한 명령 JSON을 생성합니다. Unity 클라이언트는 최종 명령을 받아 이동, 아이템 획득, 아이템 내려놓기, 정지 액션을 처리합니다.

## Command Flow

1. Unity 입력창에서 플레이어가 자연어를 입력합니다.
2. Unity 클라이언트가 WebSocket으로 백엔드에 입력을 전송합니다.
3. 백엔드는 입력을 `dialogue` 또는 `command`로 라우팅합니다.
4. `command`인 경우 LLM 기반 플래너를 실행합니다.
5. 플래너는 필요한 경우 Unity 상태 조회 tool call을 요청합니다.
6. Unity는 씬 오브젝트, NPC 상태, 보유 아이템 정보를 반환합니다.
7. 백엔드는 최종 `final_command` 메시지를 Unity로 전송합니다.
8. Unity NPC는 명령의 `actions`를 액션 큐에 넣고 순차 실행합니다.

## Command Schema

LLM 응답은 자유 텍스트가 아니라 Unity가 실행할 수 있는 구조화된 명령으로 제한합니다.

```json
{
  "actions": [
    {
      "command": "MOVE_TO",
      "object_name": "apple",
      "object_id": 1,
      "position": {0,0,0}
    },
    {
      "command": "GET_ITEM",
      "object_name": "apple",
      "object_id": 1,
      "position": {0,0,0}
    }
  ],
  "message": "사과 가지러 갈게냥."
}
```

`actions`는 NPC가 순서대로 실행할 액션 목록입니다. `object_name`은 허용 오브젝트 목록에 있는 이름만 사용할 수 있고, `object_id`는 Unity 상태 조회 결과로 실제 씬 인스턴스가 선택된 경우에만 사용합니다.

## Supported Actions

| Command | Description |
| --- | --- |
| `MOVE_TO` | 대상 오브젝트 또는 좌표로 이동 |
| `GET_ITEM` | 대상 아이템 획득 |
| `PUT_ITEM` | 보유 중인 아이템을 월드에 내려놓기 |
| `STOP` | 현재 실행 중이거나 대기 중인 액션 정지 |

## Example Commands

| Player Input | Generated Actions |
| --- | --- |
| `사과 가져와` | `MOVE_TO apple` -> `GET_ITEM apple` |
| `상자로 가` | `MOVE_TO box` |
| `사과 내려놔` | `PUT_ITEM apple` |
| `멈춰` | `STOP` |

현재 `box`는 별도 장소 시스템이 아니라 허용 오브젝트 목록에 등록된 아이템 대상입니다. 따라서 `상자로 가`는 상자 오브젝트의 위치로 이동하는 예시입니다.

## Backend Responsibilities

- FastAPI 기반 WebSocket 서버 제공
- 플레이어 입력을 대화와 실행 명령으로 라우팅
- LangChain 기반 LLM 플래너 실행
- Unity 상태 조회 tool call 요청
- 허용 오브젝트 목록과 실행 가능 capability manifest 제공
- 최종 명령을 `final_command` 메시지로 Unity에 전달
- LLM tool call 흐름을 확인할 수 있는 디버그 이벤트 스트리밍

## Unity Responsibilities

- 입력 UI에서 자연어 명령을 받아 WebSocket으로 전송
- 백엔드 메시지를 수신하고 타입별로 처리
- Unity 상태 조회 요청에 씬 오브젝트, NPC 상태, 보유 아이템 정보로 응답
- 최종 명령의 `actions`를 NPC 액션 큐로 실행
- 이동, 아이템 획득, 아이템 배치, 정지 처리
- NPC 말풍선으로 대화 또는 명령 결과 메시지 표시

## Object Constraints

현재 `object_database.json` 기준으로 허용된 대상은 `apple`, `box`입니다. SystemPrompt에는 `action.object_name`에 object database 안의 이름만 사용하도록 명시되어 있어, LLM이 임의의 오브젝트를 대상으로 명령을 생성하지 않도록 제한합니다.


## WebSocket Message Types

| Type | Direction | Purpose |
| --- | --- | --- |
| `client_function_call` | Backend -> Unity | Unity 상태 조회 요청 |
| `client_function_result` | Unity -> Backend | 상태 조회 결과 반환 |
| `final_command` | Backend -> Unity | NPC가 실행할 최종 명령 전달 |
| `error` | Backend -> Unity | 명령 처리 실패 전달 |

## Debugging

LLM 플래너가 Unity에 어떤 상태 조회 요청을 보냈고 Unity가 어떤 결과를 반환했는지는 다음 디버그 뷰에서 확인할 수 있습니다.

```text
/debug/tool-events/view
```

이 뷰는 tool call과 tool result를 시간순으로 보여주기 때문에, 자연어 입력이 최종 액션으로 변환되는 과정을 추적할 때 사용할 수 있습니다.