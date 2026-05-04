# Unity 2D 지능형 NPC Agent MVP 기획서

**문서 목적:** Unity 2D 클라이언트와 FastAPI 백엔드를 WebSocket으로 연결하여, 자연어 명령을 NPC 행동으로 변환하는 MVP 구조를 정의한다.  
**핵심 변경:** 기존 `HTTP POST /command` 단일 요청/응답 구조에서, WebSocket 기반 양방향 메시지 구조로 전환한다.  
**목표:** 백엔드가 최종 command JSON을 만들기 전에 Unity 클라이언트의 런타임 상태 조회 함수를 요청하고, 그 결과를 반영해 더 정확한 NPC 행동 명령을 생성한다.

---

## 1. 프로젝트 개요

본 프로젝트는 Unity 환경에서 사용자의 자연어 명령을 이해하고, 게임 월드 상태를 참고하여 NPC가 실제 행동을 수행하는 지능형 에이전트 MVP를 구현하는 것을 목표로 한다.

기존 구조는 Unity 클라이언트가 사용자 메시지를 FastAPI의 `/command` API로 한 번 전송하고, 백엔드가 모든 처리를 끝낸 뒤 command JSON을 반환하는 방식이었다.

수정된 구조에서는 Unity와 FastAPI가 WebSocket으로 연결된다. Unity는 사용자 명령을 WebSocket 메시지로 전송하고, FastAPI는 명령 처리 중 필요한 경우 Unity에 특정 함수 실행을 요청한다. Unity는 요청받은 함수를 실행해 현재 월드 상태, NPC 상태, 오브젝트 상태 등을 다시 백엔드에 반환한다. 백엔드는 이 값을 반영해 최종 command JSON을 생성하고 Unity에 전송한다.

이 구조의 핵심은 다음과 같다.

- Unity Runtime이 현재 월드 상태의 source of truth가 된다.
- 백엔드는 매 요청마다 전체 월드 상태를 받지 않는다.
- 백엔드는 필요한 시점에 필요한 Unity 함수만 호출한다.
- 최종 행동 실행은 Unity의 `NpcActController`가 담당한다.
- RAG, MCP Tool, Planner는 이후 확장 단계에서 같은 메시지 흐름 위에 붙인다.

---

## 2. 통신 구조

### 2.1 전체 구조

```text
[Unity Client]
  - 사용자 메시지 입력 UI
  - 아이템 오브젝트 관리
  - 현재 월드 상태 관리
  - WebSocket 연결 유지
  - 서버 요청 메시지 파싱
  - 허용된 클라이언트 함수 실행
  - 최종 command 응답 파싱
  - NpcActController 직접 실행
        |
        | 1) WebSocket: user_command
        v
[FastAPI Backend]
  - WebSocket 연결 관리
  - 자연어 명령 수신
  - OpenAI 구조화 응답 호출
  - 필요 시 Unity 함수 호출 요청
  - Unity 함수 실행 결과 수신
  - Action, Destination, Object, AIMessage 추출
  - 최종 command JSON 생성
        |
        +--> [확장 예정: RAG / VectorDB]
        |      - 가상 세계 배경지식
        |      - 아이템 의미 정보
        |      - 장소 설명
        |      - 행동 규칙
        |
        +--> [확장 예정: MCP Tool Layer]
        |      - Unity Runtime 상태 조회
        |      - Knowledge Store(vector) 검색
        |      - Planner 보조 도구 호출
        |
        | 2) WebSocket: client_function_call
        v
[Unity Client]
  - GetNearbyObjects()
  - GetObjectState()
  - GetNpcState()
  - GetRequesterState()
  - CheckReachability()
        |
        | 3) WebSocket: client_function_result
        v
[FastAPI Backend]
  - Unity 함수 결과 반영
  - 최종 command JSON 생성
        |
        | 4) WebSocket: final_command
        v
[Unity Client]
  - action == move / 이동 실행
  - action == fetch / 아이템 가져오기 실행
  - action == null / message 출력
```

### 2.2 기존 HTTP 구조와 차이

기존 HTTP 구조:

```text
Unity -> FastAPI: 사용자 명령
FastAPI -> Unity: 최종 command JSON
```

수정된 WebSocket 구조:

```text
Unity -> FastAPI: 사용자 명령
FastAPI -> Unity: 클라이언트 함수 실행 요청
Unity -> FastAPI: 클라이언트 함수 실행 결과
FastAPI -> Unity: 최종 command JSON
```

WebSocket 전환의 목적은 단순 실시간 채팅이 아니라, 백엔드가 추론 도중 Unity 런타임에 필요한 정보를 물어볼 수 있게 만드는 것이다.

---

## 3. 메시지 프로토콜

모든 WebSocket 메시지는 JSON으로 주고받는다. 공통 필드는 다음과 같다.

| 필드 | 설명 |
|---|---|
| `type` | 메시지 종류 |
| `request_id` | 하나의 사용자 명령 처리 흐름을 식별하는 ID |
| `timestamp` | 메시지 생성 시각. 선택 필드 |

### 3.1 사용자 명령 메시지

Unity가 사용자 입력을 백엔드에 전달한다.

```json
{
  "type": "user_command",
  "request_id": "req_001",
  "payload": {
    "message": "사과를 가져와",
    "agent_id": "NPC_01",
    "scene_id": "demo_scene_01",
    "requester_id": "Player_01"
  }
}
```

### 3.2 클라이언트 함수 호출 요청

FastAPI가 Unity에 특정 함수 실행을 요청한다.

```json
{
  "type": "client_function_call",
  "request_id": "req_001",
  "call_id": "call_001",
  "payload": {
    "function": "find_object",
    "args": {
      "query": "사과",
      "object_type": "item",
      "max_results": 5
    }
  }
}
```

### 3.3 클라이언트 함수 실행 결과

Unity가 함수 실행 결과를 백엔드에 반환한다.

```json
{
  "type": "client_function_result",
  "request_id": "req_001",
  "call_id": "call_001",
  "payload": {
    "ok": true,
    "result": {
      "objects": [
        {
          "object_id": "Apple_01",
          "name": "빨간 사과",
          "type": "item",
          "position": {
            "x": 3.0,
            "y": 5.0
          },
          "status": "available",
          "reachable": true
        }
      ]
    }
  }
}
```

실패한 경우:

```json
{
  "type": "client_function_result",
  "request_id": "req_001",
  "call_id": "call_001",
  "payload": {
    "ok": false,
    "error": {
      "code": "FUNCTION_NOT_ALLOWED",
      "message": "Requested function is not registered."
    }
  }
}
```

### 3.4 최종 command 메시지

FastAPI가 Unity에 최종 행동 명령을 전달한다.

```json
{
  "type": "final_command",
  "request_id": "req_001",
  "payload": {
    "status": "ok",
    "input": "사과를 가져와",
    "command": {
      "action": "fetch",
      "destination": null,
      "object": "Apple_01",
      "item": "사과",
      "message": "사과를 찾아서 가져올게요."
    }
  }
}
```

### 3.5 서버 처리 상태 메시지

처리 시간이 길어질 경우 서버가 Unity UI에 상태를 알려줄 수 있다.

```json
{
  "type": "server_status",
  "request_id": "req_001",
  "payload": {
    "state": "thinking",
    "message": "명령을 해석하는 중입니다."
  }
}
```

---

## 4. FastAPI Backend 역할

FastAPI 백엔드는 AI 처리와 명령 생성의 중심 역할을 담당한다.

주요 책임은 다음과 같다.

- Unity WebSocket 연결 수락 및 유지
- 사용자 자연어 명령 수신
- OpenAI 구조화 응답 호출
- 명령 처리 중 필요한 Unity Runtime 정보 판단
- Unity에 클라이언트 함수 호출 요청 전송
- `call_id` 기준으로 함수 요청과 응답 매칭
- Unity 함수 결과를 반영해 command JSON 생성
- 최종 command를 Unity에 전송
- timeout, 연결 끊김, 함수 실패 처리

FastAPI는 Unity의 실제 함수를 직접 실행하지 않는다. 대신 WebSocket 메시지로 실행 요청을 보내고, Unity가 허용된 함수만 실행한 뒤 결과를 반환한다.

---

## 5. Unity Client 역할

Unity 클라이언트는 실제 게임 월드와 NPC 실행을 담당한다.

주요 책임은 다음과 같다.

- WebSocket 서버 연결 및 재연결
- 사용자 입력 UI 관리
- 사용자 명령을 `user_command` 메시지로 전송
- 서버의 `client_function_call` 메시지 수신
- 허용된 함수 목록에서 요청 함수 매칭
- 함수 실행 후 `client_function_result` 메시지 반환
- 서버의 `final_command` 메시지 수신
- command JSON 파싱
- `NpcActController`로 NPC 행동 직접 실행
- 실행 결과 및 오류 메시지 UI 출력

Unity는 서버가 요청할 수 있는 함수를 allowlist 방식으로 제한한다.

---

## 6. Unity에서 제공할 클라이언트 함수

### 6.1 `find_object`

현재 씬에서 자연어 대상과 매칭되는 오브젝트 후보를 찾는다.

입력:

```json
{
  "query": "사과",
  "object_type": "item",
  "area_hint": null,
  "max_results": 5
}
```

출력:

```json
{
  "objects": [
    {
      "object_id": "Apple_01",
      "name": "빨간 사과",
      "type": "item",
      "confidence": 0.94
    }
  ]
}
```

### 6.2 `get_object_state`

특정 오브젝트의 좌표, 상태, 접근 가능 여부를 조회한다.

입력:

```json
{
  "object_id": "Apple_01"
}
```

출력:

```json
{
  "object_id": "Apple_01",
  "position": {
    "x": 3.0,
    "y": 5.0
  },
  "status": "available",
  "reachable": true,
  "area_hint": "나무 아래"
}
```

### 6.3 `get_agent_state`

NPC의 현재 위치, 행동 상태, 인벤토리를 조회한다.

입력:

```json
{
  "agent_id": "NPC_01"
}
```

출력:

```json
{
  "agent_id": "NPC_01",
  "position": {
    "x": 0.0,
    "y": 0.0
  },
  "state": "idle",
  "inventory": []
}
```

### 6.4 `get_requester_state`

명령을 내린 플레이어 또는 요청 기준 위치를 조회한다.

입력:

```json
{
  "requester_id": "Player_01"
}
```

출력:

```json
{
  "requester_id": "Player_01",
  "position": {
    "x": 0.0,
    "y": 0.0
  }
}
```

### 6.5 `check_reachability`

NPC가 특정 좌표 또는 오브젝트까지 이동 가능한지 확인한다.

입력:

```json
{
  "agent_id": "NPC_01",
  "target_position": {
    "x": 3.0,
    "y": 5.0
  }
}
```

출력:

```json
{
  "reachable": true,
  "estimated_distance": 6.2
}
```

---

## 7. 명령 처리 흐름

### 7.1 기본 흐름

```text
1. Unity가 WebSocket으로 FastAPI에 연결한다.
2. 사용자가 Unity UI에 자연어 명령을 입력한다.
3. Unity가 user_command 메시지를 전송한다.
4. FastAPI가 명령 의도를 분석한다.
5. FastAPI가 필요한 Unity Runtime 정보를 판단한다.
6. FastAPI가 client_function_call 메시지를 보낸다.
7. Unity가 요청받은 함수를 실행한다.
8. Unity가 client_function_result 메시지를 반환한다.
9. FastAPI가 함수 결과를 반영해 최종 command JSON을 만든다.
10. FastAPI가 final_command 메시지를 보낸다.
11. Unity가 command를 파싱한다.
12. Unity의 NpcActController가 NPC 행동을 실행한다.
```

### 7.2 예시: 사과를 가져와

```text
사용자 입력:
사과를 가져와

FastAPI 의도 분석:
intent = fetch_item
target = 사과

FastAPI -> Unity:
find_object("사과")

Unity -> FastAPI:
Apple_01 후보 반환

FastAPI -> Unity:
get_object_state("Apple_01")

Unity -> FastAPI:
Apple_01 좌표, available 상태, reachable 상태 반환

FastAPI -> Unity:
get_agent_state("NPC_01")

Unity -> FastAPI:
NPC 현재 위치와 idle 상태 반환

FastAPI -> Unity:
final_command(fetch Apple_01)

Unity:
NpcActController가 사과 위치로 이동 후 아이템 가져오기 실행
```

---

## 8. 최종 command JSON 설계

MVP에서는 기존 단순 command 구조를 유지한다.

```json
{
  "action": "fetch",
  "destination": null,
  "object": "Apple_01",
  "item": "사과",
  "message": "사과를 찾아서 가져올게요."
}
```

필드 규칙:

| 필드 | 설명 |
|---|---|
| `action` | Unity가 실행할 행동. `move`, `fetch`, `null` 중 하나 |
| `destination` | 이동 목적지. 필요 없으면 `null` |
| `object` | 대상 오브젝트 ID. 필요 없으면 `null` |
| `item` | 사용자 표현 기준 아이템 이름. 필요 없으면 `null` |
| `message` | Unity UI에 출력할 AI 응답 |

향후 Planner 확장 단계에서는 다음과 같은 Action Queue 구조로 확장한다.

```json
{
  "header": {
    "status": "success",
    "request_id": "req_001",
    "agent_id": "NPC_01"
  },
  "payload": {
    "text_response": "사과를 찾아서 가져올게요.",
    "actions": [
      {
        "action_id": "act_001",
        "command": "MOVE_TO",
        "params": {
          "target_id": "Apple_01"
        },
        "timeout_ms": 5000,
        "on_fail": "abort"
      },
      {
        "action_id": "act_002",
        "command": "GET_ITEM",
        "params": {
          "target_id": "Apple_01"
        },
        "timeout_ms": 2000,
        "on_fail": "abort"
      }
    ]
  }
}
```

---

## 9. RAG / VectorDB 확장 계획

RAG는 현재 월드 상태가 아니라, 게임 세계의 배경지식과 규칙을 제공한다.

저장 대상:

- 아이템 의미 정보
- 아이템 분류
- 장소 설명
- 행동 규칙
- 자연어 표현과 게임 개념 간 매핑

예시 문서:

```json
{
  "doc_id": "rule_fetch_item",
  "type": "game_rule",
  "text": "가져오기 요청은 대상 아이템 위치로 이동하고, 아이템을 획득한 뒤, 요청자 위치로 돌아오는 행동으로 해석한다.",
  "tags": ["가져오기", "아이템", "복귀", "규칙"]
}
```

RAG는 다음 순서로 사용한다.

```text
1. 사용자 명령에서 intent와 target 후보 추출
2. target 또는 intent 관련 세계 지식 검색
3. 검색 결과를 LLM 또는 Planner 입력에 포함
4. 실제 위치와 상태는 Unity Runtime 함수 호출로 조회
```

---

## 10. MCP Tool Layer 확장 계획

MCP Tool Layer는 백엔드 내부에서 도구 호출 구조를 표준화하기 위한 확장 계층이다.

WebSocket 구조에서는 Unity Runtime 조회 도구가 실제로는 `client_function_call` 메시지로 변환된다.

예시 매핑:

| MCP Tool | 실제 처리 |
|---|---|
| `search_world_knowledge` | VectorDB 검색 |
| `find_object` | Unity `client_function_call` |
| `get_object_state` | Unity `client_function_call` |
| `get_agent_state` | Unity `client_function_call` |
| `get_requester_state` | Unity `client_function_call` |
| `check_reachability` | Unity `client_function_call` |

즉, Planner 입장에서는 MCP Tool을 호출하지만, Unity Runtime 상태 조회는 WebSocket 메시지로 Unity에 위임된다.

---

## 11. Planner 확장 계획

Planner는 사용자 명령, RAG 검색 결과, Unity Runtime 조회 결과를 바탕으로 Unity가 실행 가능한 Action Queue를 생성한다.

Planner 입력:

- 사용자 자연어 명령
- LLM이 추출한 intent, target, location_hint
- RAG 검색 결과
- Unity 함수 호출 결과
- NPC 상태
- 오브젝트 상태
- 요청자 위치

Planner 출력:

- 사용자에게 보여줄 응답 메시지
- Unity Action Queue
- 오류 코드와 오류 메시지

Intent별 기본 Action 분해:

| 사용자 표현 | Intent | 기본 Action 순서 |
|---|---|---|
| 사과를 가져와 | `fetch_item` | `MOVE_TO(target)` -> `GET_ITEM(target)` -> `MOVE_TO(requester)` -> `DELIVER_ITEM(target)` |
| 사과를 주워 | `pickup_item` | `MOVE_TO(target)` -> `GET_ITEM(target)` |
| 창고로 가 | `move_to_location` | `MOVE_TO(location)` |
| 사과 어디 있어? | `query_object` | Action 없음, 위치 정보 응답 |
| 포션 사용해 | `use_item` | `USE_ITEM(item)` |

MVP에서는 우선 `move`, `fetch`, `null` command를 사용하고, Planner는 이후 Action Queue 단계에서 적용한다.

---

## 12. API / Endpoint 설계

### 12.1 `GET /health`

백엔드 상태 확인용 HTTP API다.

```json
{
  "status": "ok",
  "service": "actnpc-backend",
  "version": "0.1.0"
}
```

### 12.2 `GET /health/openai`

OpenAI 연결과 구조화 응답 확인용 HTTP API다. 개발 및 점검 목적으로 유지한다.

### 12.3 `POST /command`

기존 HTTP command API는 초기 개발 호환성을 위해 남길 수 있다. 단, 최종 MVP의 기본 통신 경로는 WebSocket으로 한다.

### 12.4 `WebSocket /ws/agent`

Unity 클라이언트와 FastAPI 백엔드의 기본 통신 채널이다.

지원 메시지:

- `user_command`
- `client_function_call`
- `client_function_result`
- `server_status`
- `final_command`
- `error`

---

## 13. 예외 처리 정책

| 상황 | 처리 방식 |
|---|---|
| Unity WebSocket 연결 끊김 | 서버는 요청 처리 중단, Unity는 재연결 시도 |
| `client_function_result` timeout | `CLIENT_FUNCTION_TIMEOUT` 오류 반환 |
| 허용되지 않은 Unity 함수 요청 | Unity가 `FUNCTION_NOT_ALLOWED` 반환 |
| 대상 오브젝트 없음 | `OBJECT_NOT_FOUND` 최종 오류 응답 |
| 대상 후보가 여러 개이고 판단 불가 | `AMBIGUOUS_TARGET` 최종 오류 응답 |
| 대상이 이미 수집됨 | `OBJECT_ALREADY_COLLECTED` 최종 오류 응답 |
| 대상 위치 접근 불가 | `TARGET_UNREACHABLE` 최종 오류 응답 |
| NPC가 다른 행동 중 | `AGENT_BUSY` 최종 오류 응답 |
| LLM 응답 파싱 실패 | rule-based fallback 또는 `INTENT_NOT_UNDERSTOOD` 반환 |
| 최종 command 생성 실패 | `COMMAND_BUILD_FAILED` 오류 반환 |

오류 응답 예시:

```json
{
  "type": "final_command",
  "request_id": "req_002",
  "payload": {
    "status": "error",
    "input": "없는 아이템 가져와",
    "command": {
      "action": null,
      "destination": null,
      "object": null,
      "item": null,
      "message": "현재 씬에서 요청한 아이템을 찾지 못했어요."
    },
    "error": {
      "code": "OBJECT_NOT_FOUND",
      "message": "No active object matched query."
    }
  }
}
```

---

## 14. 구현 단계

### 1단계. WebSocket 기본 연결

- FastAPI `WebSocket /ws/agent` 구현
- Unity WebSocket 클라이언트 구현
- 연결, 연결 해제, 재연결 처리
- `user_command` 송수신 확인
- `server_status` 메시지 출력

### 2단계. 기존 command 응답 WebSocket 전환

- 기존 `/command` 처리 로직을 WebSocket 메시지 처리 흐름으로 이동
- OpenAI 구조화 응답 호출
- `final_command` 메시지 생성
- Unity에서 `final_command` 파싱
- `NpcActController` 직접 실행

### 3단계. Unity 클라이언트 함수 호출 구조 구현

- Unity 함수 allowlist 구현
- `client_function_call` 파싱
- `call_id` 기반 응답 매칭
- `client_function_result` 반환
- timeout 처리

### 4단계. Unity Runtime 조회 함수 구현

- `find_object`
- `get_object_state`
- `get_agent_state`
- `get_requester_state`
- `check_reachability`

### 5단계. 백엔드 함수 호출 오케스트레이션

- 명령 의도에 따라 필요한 Unity 함수 결정
- Unity 함수 결과 수집
- 결과를 OpenAI 또는 command builder에 반영
- 실패 시 fallback command 생성

### 6단계. RAG / VectorDB 확장

- 게임 세계 배경지식 문서 작성
- 아이템 의미 정보 문서 작성
- 장소 설명 문서 작성
- 행동 규칙 문서 작성
- `search_world_knowledge` 도구 추가

### 7단계. MCP Tool Layer 확장

- MCP Tool 인터페이스 정의
- Unity Runtime 조회 도구를 WebSocket client function call로 연결
- Knowledge Store 검색 도구 연결
- timeout, retry, error 표준화

### 8단계. Planner / Action Queue 확장

- intent별 Action 분해 규칙 구현
- `MOVE_TO`, `GET_ITEM`, `DELIVER_ITEM` Action Queue 생성
- Unity Action Executor 구현
- Action 실행 결과를 서버로 보고하는 구조 추가

---

## 15. MVP 범위

### 15.1 포함 범위

- 단일 Unity 클라이언트
- 단일 NPC
- 단일 2D 씬
- 사용자 자연어 명령 입력
- FastAPI WebSocket 서버
- OpenAI 구조화 응답 기반 command 생성
- Unity 클라이언트 함수 호출 요청/응답
- `move`, `fetch`, `null` command 실행
- Unity UI 메시지 출력

### 15.2 제외 범위

- 다중 Unity 클라이언트 세션 관리
- 다중 NPC 협업
- 복잡한 장기 기억
- 대규모 월드 동기화
- 완전 자율 행동 계획
- 실시간 스트리밍 대화
- 복잡한 전투 시스템
- 프로덕션 인증/권한 시스템

---

## 16. 완료 기준

MVP 완료 기준은 다음과 같다.

- Unity가 FastAPI WebSocket 서버에 연결할 수 있다.
- Unity가 사용자 명령을 `user_command`로 전송할 수 있다.
- FastAPI가 사용자 명령을 수신하고 처리할 수 있다.
- FastAPI가 필요 시 Unity에 `client_function_call`을 보낼 수 있다.
- Unity가 허용된 함수를 실행하고 `client_function_result`를 반환할 수 있다.
- FastAPI가 Unity 함수 결과를 반영해 `final_command`를 생성할 수 있다.
- Unity가 `final_command`를 파싱해 `NpcActController`로 실행할 수 있다.
- `사과를 가져와` 같은 명령에서 Unity Runtime의 실제 오브젝트 상태를 참고할 수 있다.
- 오류 상황에서 Unity UI에 적절한 메시지를 출력할 수 있다.

---

## 17. 최종 요약

수정된 MVP 구조는 단순한 HTTP 요청/응답 방식이 아니라 WebSocket 기반 양방향 명령 처리 구조다.

```text
Unity 사용자 명령
-> FastAPI WebSocket 수신
-> OpenAI 명령 해석
-> 필요한 Unity 함수 호출 요청
-> Unity Runtime 상태 반환
-> FastAPI 최종 command JSON 생성
-> Unity final_command 수신
-> NpcActController 직접 실행
```

이 구조를 사용하면 백엔드가 최종 JSON을 반환하기 전에 Unity 클라이언트의 특정 함수를 호출해 값을 받을 수 있다. 따라서 오브젝트 위치, NPC 상태, 아이템 사용 가능 여부, 이동 가능 여부처럼 Unity Runtime만 정확히 알 수 있는 정보를 반영한 NPC 행동 생성이 가능하다.

향후 RAG는 세계 지식과 행동 규칙을 제공하고, MCP Tool Layer는 지식 검색과 Unity Runtime 조회를 표준화하며, Planner는 최종적으로 `MOVE_TO`, `GET_ITEM`, `DELIVER_ITEM` 같은 Action Queue를 생성하는 방향으로 확장한다.
