# [수정 기획안] Unity 2D 기반 지능형 에이전트 MVP 구축

**부제:** RAG 기반 세계지식 검색과 MCP Tool 호출 구조를 활용한 자율 행동 제어 PoC  
**개발 기간:** 약 1주  
**작성:** 프로젝트 TF팀  
**수정 방향:** 전체 씬 상태 전송 방식 제거, 백엔드는 command JSON만 반환, Unity가 응답 command를 직접 실행  
**목표:** 자연어 명령을 게임 내 실제 행동으로 변환하는 Unity 2D 지능형 NPC 프로토타입 구축

---

## 1. 프로젝트 개요

본 프로젝트는 Unity 2D 환경에서 사용자의 자연어 명령을 이해하고, 게임 세계에 대한 배경지식 검색과 현재 월드 상태 조회를 통해 NPC가 실제 행동을 수행하는 지능형 에이전트 MVP를 구축하는 것을 목표로 한다.

사용자는 텍스트로 NPC에게 명령을 내리고, Unity는 해당 명령을 FastAPI 백엔드로 전달한다. 현재 구현 단계에서 백엔드는 LLM 구조화 응답을 통해 `action`, `destination`, `item`, `message` 형태의 command JSON을 생성하고 Unity에 그대로 반환한다. Unity는 백엔드가 다시 Unity local HTTP server를 호출하기를 기다리지 않고, 받은 command를 `NpcActController`에서 직접 실행한다.

본 MVP의 현재 핵심은 단순 대화형 챗봇이 아니라, **자연어 명령 → 백엔드 command 추출 → Unity command 수신 → NPC 행동 실행**으로 이어지는 end-to-end 행동 루프를 먼저 검증하는 것이다. 이후 확장 단계에서 RAG 검색, MCP Tool 호출, Planner 기반 Action Queue 생성을 붙인다.

기존처럼 명령을 내릴 때마다 현재 씬의 모든 오브젝트 정보를 백엔드로 전달하지 않는다. 또한 백엔드가 OpenAI 응답 후 Unity의 `/npc/act/...` 로컬 HTTP 서버를 다시 호출하지 않는다. 명령 요청의 왕복 경로는 Unity → FastAPI → Unity 응답으로 단순화한다.

---

## 2. 핵심 목표

### 2.1 기능 목표

- Unity 2D 환경에서 단일 NPC 에이전트 구현
- 사용자의 자연어 명령 입력 UI 구현
- FastAPI 기반 AI 백엔드 구축
- VectorDB 기반 게임 세계 배경지식 검색 구현
- MCP Tool 호출 구조를 통한 현재 월드 상태 조회 구현
- Planner 기반 Action 순서 생성 구현
- NPC 이동, 아이템 습득, 복귀 Action 실행 구현
- 명령 처리 결과를 Unity UI에 텍스트로 출력

### 2.2 시연 목표

사용자가 다음과 같은 명령을 입력하면 NPC가 대상 아이템을 찾고, 해당 위치로 이동한 뒤 아이템을 습득하고, 필요한 경우 명령 위치 또는 사용자 위치로 돌아온다.

```text
창고 옆에 있는 포션 좀 가져와
```

처리 흐름은 다음과 같다.

```text
사용자 명령 입력
→ Unity가 FastAPI /command API 호출
→ FastAPI가 OpenAI 구조화 응답으로 action, destination, item, message 추출
→ FastAPI가 command JSON을 Unity에 응답
→ Unity가 응답 command를 파싱
→ Unity NpcActController가 action 값에 따라 move 또는 fetch 실행
→ 결과 메시지 출력
```

---

## 3. 시스템 아키텍처

### 3.1 전체 구조

```text
[Unity 2D Client]
  - 사용자 입력 UI
  - NPC 이동 및 상태 제어
  - 아이템 오브젝트 관리
  - 현재 월드 상태 관리
  - command 응답 파싱
  - NpcActController 직접 실행
        |
        | 1) HTTP JSON: 사용자 명령 전달 (/command)
        v
[FastAPI Backend]
  - 자연어 명령 수신
  - OpenAI 구조화 응답 호출
  - action, destination, item, message 추출
  - command JSON 응답 생성
        |
        +--> [확장 예정: Knowledge Store / VectorDB]
        |      - 게임 세계 배경지식
        |      - 아이템 의미 정보
        |      - 장소 설명
        |      - 행동 규칙
        |
        +--> [확장 예정: MCP Tool Layer]
        |      - search_world_knowledge
        |      - find_object
        |      - get_object_state
        |      - get_agent_state
        |      - get_requester_state
        |      - check_reachability
        |
        | 2) HTTP JSON: command 응답
        v
[Unity 2D Client]
  - action == move 이면 이동 실행
  - action == fetch 이면 가져오기 실행
  - action == null 이면 message 출력
```

### 3.2 핵심 변경 사항

기존 설계에서는 Unity가 `/agent/command` 요청 시 `scene_state` 전체를 백엔드로 전달했고, 일부 구현에서는 백엔드가 OpenAI 응답 후 Unity local HTTP server의 `/npc/act/...` 엔드포인트를 다시 호출했다. 수정된 설계에서는 전체 씬 상태를 매 요청마다 전송하지 않고, 백엔드가 Unity를 재호출하지도 않는다.

수정된 방식은 다음과 같다.

```text
Unity가 사용자 명령만 FastAPI /command로 전달
→ FastAPI가 OpenAI 구조화 응답으로 command JSON 생성
→ FastAPI가 Unity에 command JSON 반환
→ Unity가 받은 command를 직접 실행
```

현재 구현된 `/command` 요청에는 전체 오브젝트 배열을 포함하지 않고, 다음 필드만 포함한다.

- `message`

향후 `/agent/command`로 확장할 경우에도 전체 오브젝트 배열은 포함하지 않고, 다음과 같은 최소 정보만 포함한다.

- `request_id`
- `agent_id`
- `scene_id`
- `user_text`
- `requester_id` 또는 `requester_position`

현재 구현에서는 `action`, `destination`, `item`, `message`만 응답한다. 현재 씬의 오브젝트 목록, 아이템 좌표, 아이템 상태, NPC 상태 등은 향후 Planner/RAG 단계에서 필요할 때 MCP Tool을 통해 조회한다.

### 3.3 구성 요소별 역할

#### Unity 2D Client

Unity는 실제 게임 월드를 관리하고, 백엔드에서 전달받은 command JSON을 직접 실행한다. 현재 구현에서는 `action` 값이 `move`이면 이동 처리, `fetch`이면 가져오기 처리를 수행한다. MCP Tool Provider와 Action Queue Executor는 이후 확장 단계에서 구현한다.

주요 역할은 다음과 같다.

- 사용자 텍스트 명령 입력
- FastAPI 백엔드로 명령 전송
- 현재 NPC 위치, 아이템 상태, 인벤토리 상태 관리
- 백엔드 응답의 command JSON 파싱
- `action`, `destination`, `item`, `message` 기반 직접 실행
- NPC 이동 처리
- 아이템 습득 처리
- 실행 결과 UI 출력

#### FastAPI Backend

FastAPI 백엔드는 AI 처리 허브이며, 현재 구현에서는 자연어 입력을 Unity가 실행할 수 있는 단일 command JSON으로 변환한다.

주요 역할은 다음과 같다.

- Unity로부터 사용자 명령 수신
- 자연어 명령에서 행동 의도와 대상 추출
- OpenAI 구조화 응답으로 `action`, `destination`, `item`, `message` 생성
- Unity가 직접 실행 가능한 command JSON 반환
- Unity local HTTP server를 재호출하지 않음

#### Knowledge Store / VectorDB

Knowledge Store는 게임 세계에 대한 배경지식과 규칙을 저장한다. 특정 아이템의 현재 좌표나 현재 상태는 저장하지 않는다.

저장 대상은 다음과 같다.

- 아이템의 의미 정보
- 아이템 분류 정보
- 장소 설명
- 게임 규칙
- 행동 수행 조건
- 자연어 표현과 게임 개념 간 관계

예시는 다음과 같다.

```text
포션은 체력을 회복하는 소비 아이템이다.
빨간 포션은 일반적인 회복 아이템으로 분류된다.
사과는 먹을 수 있는 소비 아이템이며 item으로 분류된다.
창고는 아이템이 보관되는 장소다.
아이템을 습득하려면 NPC가 대상 오브젝트 근처까지 이동해야 한다.
available 상태의 아이템만 습득할 수 있다.
가져오기 요청은 대상 아이템을 습득한 뒤 명령 기준 위치로 복귀하는 행동으로 해석할 수 있다.
```

#### MCP Tool Layer

MCP Tool Layer는 Planner 확장 단계에서 백엔드가 Unity 게임 월드 및 지식 검색 기능을 함수 호출 방식으로 사용할 수 있게 하는 계층이다.

본 기획서에서는 별도의 상태 조회 계층을 두지 않고, 현재 월드 상태 조회 기능을 모두 MCP Tool로 통합한다.

MCP Tool은 다음 두 종류의 정보를 제공한다.

1. **세계지식 검색**
   - VectorDB 기반 RAG 검색
   - 아이템 의미, 장소 설명, 행동 규칙 검색

2. **현재 월드 상태 조회**
   - 현재 씬에서 대상 오브젝트 검색
   - 대상 오브젝트 좌표, 상태, 접근 가능 여부 조회
   - NPC의 현재 위치, 이동 상태, 인벤토리 조회
   - 명령 기준 위치 또는 사용자 위치 조회

예를 들어 `Apple_01`의 현재 좌표는 VectorDB에서 검색하지 않고, `get_object_state` MCP Tool을 호출해 확인한다.

---

## 4. 데이터 책임 분리

본 시스템에서는 세계지식과 현재 게임 상태를 명확히 분리하되, 조회 인터페이스는 MCP Tool Layer로 통합한다.

| 구분 | 담당 영역 | 저장 위치 | 조회 방식 |
|---|---|---|---|
| 게임 세계 배경지식 | 아이템 의미, 장소 설명, 게임 규칙 | VectorDB | `search_world_knowledge` MCP Tool |
| 현재 아이템 좌표 | 씬 내 오브젝트의 현재 위치 | Unity Runtime | `get_object_state` MCP Tool |
| 현재 아이템 상태 | available, collected, disabled 등 | Unity Runtime | `get_object_state` MCP Tool |
| NPC 상태 | 현재 위치, 이동 상태, 인벤토리 | Unity Runtime | `get_agent_state` MCP Tool |
| 명령 기준 위치 | 사용자 또는 명령 발생 지점 | Unity Runtime | `get_requester_state` MCP Tool |
| 현재 명령 변환 | `move`, `fetch`, `null` command 생성 | FastAPI Backend | OpenAI 구조화 응답 |
| 향후 행동 계획 | MOVE_TO, GET_ITEM 등 실행 순서 | FastAPI Planner | Planner 내부 로직 |
| 실제 행동 실행 | 이동, 습득, UI 출력 | Unity `NpcActController` | command 직접 실행, 향후 Action Queue 실행 |

---

## 5. 핵심 처리 흐름

### 5.1 사용자 명령 예시

```text
사과를 가져와
```

### 5.2 FastAPI 요청 흐름

Unity는 사용자 명령을 JSON 형태로 `/command` API에 전달한다.

```json
{
  "message": "사과를 가져와"
}
```

백엔드는 Unity 로컬 HTTP 서버를 다시 호출하지 않고, 다음 형태의 command JSON만 응답한다.

```json
{
  "status": "ok",
  "input": "사과를 가져와",
  "command": {
    "action": "fetch",
    "destination": null,
    "item": "사과",
    "message": "사과를 가져올게."
  }
}
```

### 5.3 백엔드 처리 순서

1. 사용자 명령 수신
  - 사과를 가져와 줄래?
2. OpenAI 구조화 응답 호출
3. `CommandDict` 스키마에 맞춰 핵심 필드 추출
   - `action`: `move`, `fetch`, 또는 `null`
   - `destination`: 이동 대상 또는 `null`
   - `item`: 가져올 대상 또는 `null`
   - `message`: 사용자에게 보여줄 응답 메시지
4. command JSON 생성
5. Unity에 command JSON 반환

현재 구현에서는 이 단계에서 Python 서버가 Unity local HTTP server의 `/npc/act/...`를 호출하지 않는다. 따라서 `async_request_npc_act()` 기반 왕복 호출은 기본 명령 처리 경로에서 제외된다.

### 5.4 Unity 실행 순서

1. 백엔드 응답 수신
2. 응답의 `command` 객체 파싱
3. `action`이 `fetch`이면 `item` 값을 사용해 가져오기 실행
4. `action`이 `move`이면 `destination` 값을 사용해 이동 실행
5. `action`이 `null`이면 행동 없이 `message` 출력
6. 실행 결과 UI 또는 Unity Console에 출력

향후 Planner 확장 단계에서는 이 command 구조를 Action Queue로 확장하고, `MOVE_TO`, `GET_ITEM`, `DELIVER_ITEM`을 순차 실행한다.

---

## 6. MCP Tool 설계

MCP Tool은 현재 `/command` 기반 1차 구현에는 포함하지 않는다. Planner 기반 Action Queue로 확장할 때 현재 월드 상태 조회와 지식 검색을 MCP Tool Layer로 통합한다. 단, 실제 데이터의 저장 위치는 구분한다.

### 6.1 `search_world_knowledge`

게임 세계 배경지식을 VectorDB에서 검색한다.

#### 요청 예시

```json
{
  "tool": "search_world_knowledge",
  "params": {
    "query": "사과 아이템 가져오기 습득 규칙"
  }
}
```

#### 응답 예시

```json
{
  "results": [
    {
      "doc_id": "item_knowledge_apple",
      "text": "사과는 먹을 수 있는 소비 아이템이며 item으로 분류된다.",
      "score": 0.91
    },
    {
      "doc_id": "rule_fetch_item",
      "text": "가져오기 요청은 대상 아이템을 습득한 뒤 명령 기준 위치로 복귀하는 행동으로 해석한다.",
      "score": 0.88
    },
    {
      "doc_id": "rule_pickup_item",
      "text": "아이템을 습득하려면 NPC가 대상 오브젝트 근처까지 이동해야 한다. 대상이 available 상태일 때만 습득할 수 있다.",
      "score": 0.86
    }
  ]
}
```

### 6.2 `find_object`

현재 씬에서 사용자 명령과 일치하는 오브젝트 후보를 찾는다.

#### 요청 예시

```json
{
  "tool": "find_object",
  "params": {
    "scene_id": "demo_scene_01",
    "query": "사과",
    "object_type": "item",
    "area_hint": null,
    "max_results": 5
  }
}
```

#### 응답 예시

```json
{
  "objects": [
    {
      "object_id": "Apple_01",
      "name": "빨간 사과",
      "type": "item",
      "confidence": 0.94,
      "reason": "display_name과 aliases가 사과와 일치함"
    }
  ]
}
```

### 6.3 `get_object_state`

특정 오브젝트의 현재 좌표, 상태, 접근 가능 여부를 조회한다.

#### 요청 예시

```json
{
  "tool": "get_object_state",
  "params": {
    "scene_id": "demo_scene_01",
    "object_id": "Apple_01"
  }
}
```

#### 응답 예시

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

### 6.4 `get_agent_state`

NPC의 현재 위치, 이동 상태, 인벤토리 정보를 조회한다.

#### 요청 예시

```json
{
  "tool": "get_agent_state",
  "params": {
    "scene_id": "demo_scene_01",
    "agent_id": "NPC_01"
  }
}
```

#### 응답 예시

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

### 6.5 `get_requester_state`

명령을 내린 사용자 또는 명령 발생 지점의 위치를 조회한다. “가져와”처럼 대상 습득 후 복귀가 필요한 명령에서 사용한다.

#### 요청 예시

```json
{
  "tool": "get_requester_state",
  "params": {
    "scene_id": "demo_scene_01",
    "requester_id": "Player_01"
  }
}
```

#### 응답 예시

```json
{
  "requester_id": "Player_01",
  "position": {
    "x": 0.0,
    "y": 0.0
  }
}
```

### 6.6 `check_reachability`

NPC가 특정 좌표 또는 오브젝트까지 이동 가능한지 확인한다. MVP에서는 `get_object_state.reachable` 값으로 대체할 수 있으며, 장애물이나 경로 탐색이 복잡해질 경우 별도 Tool로 분리한다.

#### 요청 예시

```json
{
  "tool": "check_reachability",
  "params": {
    "scene_id": "demo_scene_01",
    "agent_id": "NPC_01",
    "target_position": {
      "x": 3.0,
      "y": 5.0
    }
  }
}
```

#### 응답 예시

```json
{
  "reachable": true,
  "estimated_distance": 6.2
}
```

---

## 7. Planner 설계

Planner는 사용자 명령, RAG 검색 결과, MCP Tool 조회 결과를 바탕으로 Unity가 실행 가능한 Action 순서를 생성하는 백엔드 내부 로직이다.

Planner는 MCP Tool 자체가 아니다. MCP Tool은 필요한 정보를 조회하는 수단이고, Planner는 어떤 정보를 조회할지 결정하고, 조회 결과를 바탕으로 어떤 Action을 어떤 순서로 실행할지 결정하는 판단 로직이다.

### 7.1 Planner 입력

Planner는 다음 정보를 입력으로 받는다.

- 사용자 자연어 명령
- Parser 또는 LLM이 추출한 의도 정보
- RAG 검색 결과
- MCP Tool로 조회한 대상 후보 목록
- MCP Tool로 조회한 대상 오브젝트 상태
- MCP Tool로 조회한 NPC 상태
- MCP Tool로 조회한 명령 기준 위치

### 7.2 Planner 출력

Planner는 다음 정보를 출력한다.

- 사용자에게 보여줄 텍스트 응답
- Unity에서 실행할 Action 배열
- 오류 발생 시 error code와 message
- Action별 실행 조건과 실패 처리 방식

### 7.3 Planner 처리 단계

Planner는 다음 순서로 동작한다.

```text
1. 명령 해석
   - 사용자 문장에서 intent, target, location_hint를 추출한다.

2. 행동 유형 결정
   - 가져와, 가져다줘, 찾아와 → fetch_item
   - 주워, 먹어, 획득해 → pickup_item
   - 이동해, 가봐 → move_to_location

3. 필요한 지식 검색
   - target이 어떤 게임 개념인지 RAG로 확인한다.
   - 해당 intent를 수행하기 위한 규칙을 RAG로 확인한다.

4. 필요한 MCP Tool 호출 계획 수립
   - 대상 오브젝트 검색이 필요하면 find_object 호출
   - 대상 상태 확인이 필요하면 get_object_state 호출
   - NPC 상태 확인이 필요하면 get_agent_state 호출
   - 복귀가 필요하면 get_requester_state 호출

5. Tool 결과 검증
   - 대상 후보가 있는지 확인한다.
   - 후보가 여러 개인 경우 가장 적절한 대상을 선택한다.
   - 대상 상태가 available인지 확인한다.
   - 대상 위치가 reachable인지 확인한다.
   - NPC 상태가 idle인지 확인한다.

6. Action 분해
   - high-level intent를 Unity Action 단위로 분해한다.

7. Action 순서 생성
   - 각 Action의 선행 조건을 만족하는 순서로 배열을 생성한다.

8. 응답 생성
   - text_response와 actions를 포함한 JSON을 생성한다.
```

### 7.4 Intent별 Action 분해 규칙

Planner는 사용자의 자연어 명령을 high-level intent로 바꾸고, 이를 Unity Action 목록으로 분해한다.

| 사용자 표현 | Intent | 기본 Action 순서 |
|---|---|---|
| 사과를 가져와 | `fetch_item` | `MOVE_TO(target)` → `GET_ITEM(target)` → `MOVE_TO(requester)` → `DELIVER_ITEM(target)` |
| 사과를 주워 | `pickup_item` | `MOVE_TO(target)` → `GET_ITEM(target)` |
| 창고로 가 | `move_to_location` | `MOVE_TO(location)` |
| 사과 어디 있어? | `query_object` | Action 없음, 위치 정보 응답 |
| 포션 사용해 | `use_item` | `USE_ITEM(item)` |

MVP에서는 우선 `fetch_item`, `pickup_item` 두 가지 intent를 중심으로 구현한다.

### 7.5 `fetch_item` Action 생성 예시

사용자 명령이 다음과 같다고 가정한다.

```text
사과를 가져와
```

Planner는 이를 다음과 같이 해석한다.

```json
{
  "intent": "fetch_item",
  "target_name": "사과",
  "location_hint": null,
  "requires_return": true
}
```

이후 Planner는 MCP Tool 호출 결과를 바탕으로 다음 정보를 확보한다.

```json
{
  "target_object": {
    "object_id": "Apple_01",
    "position": {
      "x": 3.0,
      "y": 5.0
    },
    "status": "available",
    "reachable": true
  },
  "agent_state": {
    "agent_id": "NPC_01",
    "position": {
      "x": 0.0,
      "y": 0.0
    },
    "state": "idle"
  },
  "requester_state": {
    "requester_id": "Player_01",
    "position": {
      "x": 0.0,
      "y": 0.0
    }
  }
}
```

Planner는 다음 규칙에 따라 Action 순서를 만든다.

```text
fetch_item(target):
  1. 대상이 available 상태인지 확인한다.
  2. 대상 위치가 reachable인지 확인한다.
  3. NPC가 idle 상태인지 확인한다.
  4. 대상 위치로 이동하는 MOVE_TO를 생성한다.
  5. 대상 아이템을 습득하는 GET_ITEM을 생성한다.
  6. requires_return이 true이면 requester 위치로 이동하는 MOVE_TO를 생성한다.
  7. 전달 연출이 필요한 경우 DELIVER_ITEM을 생성한다.
```

최종 Action JSON은 다음과 같다.

```json
{
  "header": {
    "status": "success",
    "request_id": "req_001",
    "agent_id": "NPC_01"
  },
  "payload": {
    "text_response": "사과를 찾았습니다. 가져다드리겠습니다.",
    "actions": [
      {
        "action_id": "act_001",
        "command": "MOVE_TO",
        "params": {
          "target_id": "Apple_01",
          "x": 3.0,
          "y": 5.0,
          "stop_distance": 0.5
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
      },
      {
        "action_id": "act_003",
        "command": "MOVE_TO",
        "params": {
          "x": 0.0,
          "y": 0.0,
          "reason": "return_to_requester"
        },
        "timeout_ms": 5000,
        "on_fail": "abort"
      },
      {
        "action_id": "act_004",
        "command": "DELIVER_ITEM",
        "params": {
          "target_id": "Apple_01",
          "receiver_id": "Player_01"
        },
        "timeout_ms": 2000,
        "on_fail": "abort"
      }
    ]
  }
}
```

### 7.6 후보가 여러 개인 경우

`find_object` 결과가 여러 개인 경우 Planner는 다음 기준으로 대상을 선택한다.

1. 사용자 명령의 위치 단서와 일치하는 후보 우선
2. `confidence`가 높은 후보 우선
3. `status=available` 후보 우선
4. `reachable=true` 후보 우선
5. 후보 간 점수 차이가 작으면 `AMBIGUOUS_TARGET` 반환

예를 들어 사과가 여러 개인 경우:

```json
{
  "error": {
    "code": "AMBIGUOUS_TARGET",
    "message": "사과가 여러 개 있습니다. 나무 아래 사과인지, 창고 옆 사과인지 알려주세요."
  }
}
```

### 7.7 Planner 의사코드

```python
def plan_command(command, agent_id, scene_id, requester_id):
    parsed = parse_intent(command)
    # parsed = {"intent": "fetch_item", "target": "사과", "location_hint": None}

    knowledge = call_mcp_tool(
        "search_world_knowledge",
        query=f"{parsed.target} {parsed.intent} 규칙"
    )

    candidates = call_mcp_tool(
        "find_object",
        scene_id=scene_id,
        query=parsed.target,
        object_type="item",
        area_hint=parsed.location_hint
    )

    target = select_target(candidates, parsed.location_hint)
    if target is None:
        return error("OBJECT_NOT_FOUND")

    target_state = call_mcp_tool(
        "get_object_state",
        scene_id=scene_id,
        object_id=target.object_id
    )

    agent_state = call_mcp_tool(
        "get_agent_state",
        scene_id=scene_id,
        agent_id=agent_id
    )

    requester_state = None
    if parsed.intent == "fetch_item":
        requester_state = call_mcp_tool(
            "get_requester_state",
            scene_id=scene_id,
            requester_id=requester_id
        )

    validate_preconditions(parsed, knowledge, target_state, agent_state)

    actions = []
    if parsed.intent in ["pickup_item", "fetch_item"]:
        actions.append(move_to(target_state.position, target.object_id))
        actions.append(get_item(target.object_id))

    if parsed.intent == "fetch_item":
        actions.append(move_to(requester_state.position, reason="return_to_requester"))
        actions.append(deliver_item(target.object_id, requester_id))

    return success_response(actions)
```

---

## 8. Unity Action 설계

현재 Unity는 `/command` 응답의 `action`, `destination`, `item`, `message`를 파싱해 `NpcActController`에서 직접 실행한다. 이 장의 Action Queue 설계는 Planner 확장 단계에서 적용한다.

### 8.1 Action 목록

| Action | 목적 | 필수 파라미터 | 실행 조건 |
|---|---|---|---|
| `MOVE_TO` | NPC를 특정 좌표 또는 대상 위치로 이동 | `x`, `y` 또는 `target_id` | 대상 좌표가 유효해야 함 |
| `GET_ITEM` | 대상 아이템 습득 | `target_id` | NPC가 대상 근처에 있고 대상이 available이어야 함 |
| `DELIVER_ITEM` | 습득한 아이템을 사용자 또는 지정 대상에게 전달 | `target_id`, `receiver_id` | NPC 인벤토리에 해당 아이템이 있어야 함 |
| `SAY` | 텍스트 메시지 출력 | `text` | UI 표시 영역이 있어야 함 |
| `ERROR_RESPONSE` | 오류 메시지 출력 | `code`, `message` | 오류 발생 시 실행 |

### 8.2 Action 실행 규칙

- Action은 배열 순서대로 실행한다.
- 각 Action은 `action_id`를 가진다.
- `MOVE_TO`가 완료되기 전에는 `GET_ITEM`을 실행하지 않는다.
- `GET_ITEM`이 완료되기 전에는 `DELIVER_ITEM`을 실행하지 않는다.
- 각 Action 실행 전 Unity에서 조건을 다시 검증한다.
- 오브젝트가 존재하지 않거나 이미 습득된 경우 실행을 중단한다.
- 실패 시 남은 Action Queue를 폐기하고 오류 메시지를 출력한다.
- `timeout_ms`를 초과하면 해당 Action은 실패 처리한다.

### 8.3 Backend → Unity 최종 응답 예시

```json
{
  "header": {
    "status": "success",
    "request_id": "req_001",
    "agent_id": "NPC_01"
  },
  "payload": {
    "text_response": "창고 옆 포션을 확인했습니다. 가져다드리겠습니다.",
    "actions": [
      {
        "action_id": "act_001",
        "command": "MOVE_TO",
        "params": {
          "target_id": "Potion_Red_01",
          "x": -3.0,
          "y": 8.0,
          "stop_distance": 0.5
        },
        "timeout_ms": 5000,
        "on_fail": "abort"
      },
      {
        "action_id": "act_002",
        "command": "GET_ITEM",
        "params": {
          "target_id": "Potion_Red_01"
        },
        "timeout_ms": 2000,
        "on_fail": "abort"
      },
      {
        "action_id": "act_003",
        "command": "MOVE_TO",
        "params": {
          "x": 0.0,
          "y": 0.0,
          "reason": "return_to_requester"
        },
        "timeout_ms": 5000,
        "on_fail": "abort"
      },
      {
        "action_id": "act_004",
        "command": "DELIVER_ITEM",
        "params": {
          "target_id": "Potion_Red_01",
          "receiver_id": "Player_01"
        },
        "timeout_ms": 2000,
        "on_fail": "abort"
      }
    ]
  }
}
```

### 8.4 오류 응답 예시

```json
{
  "header": {
    "status": "error",
    "request_id": "req_002",
    "agent_id": "NPC_01"
  },
  "payload": {
    "text_response": "현재 씬에서 요청한 아이템을 찾지 못했습니다.",
    "actions": []
  },
  "error": {
    "code": "OBJECT_NOT_FOUND",
    "message": "No active object matched query: 사과"
  }
}
```

---

## 9. 데이터 설계

### 9.1 VectorDB 문서 구조

VectorDB에는 게임 세계의 지식 정보를 문서 단위로 저장한다.

```json
[
  {
    "doc_id": "item_knowledge_potion",
    "type": "item_knowledge",
    "text": "포션은 체력을 회복하는 소비 아이템이다. 빨간 포션은 일반 회복 아이템으로 분류된다.",
    "tags": ["포션", "물약", "회복", "소비아이템"]
  },
  {
    "doc_id": "item_knowledge_apple",
    "type": "item_knowledge",
    "text": "사과는 먹을 수 있는 소비 아이템이며 item으로 분류된다.",
    "tags": ["사과", "과일", "음식", "소비아이템"]
  },
  {
    "doc_id": "area_knowledge_warehouse",
    "type": "area_knowledge",
    "text": "창고는 아이템이 보관되는 장소이며, 창고 주변에는 소모품이나 열쇠류가 배치될 수 있다.",
    "tags": ["창고", "보관", "아이템"]
  },
  {
    "doc_id": "rule_pickup_item",
    "type": "game_rule",
    "text": "아이템을 습득하려면 NPC가 대상 아이템 근처까지 이동해야 한다. 대상이 available 상태일 때만 습득할 수 있다.",
    "tags": ["아이템", "습득", "이동", "규칙"]
  },
  {
    "doc_id": "rule_fetch_item",
    "type": "game_rule",
    "text": "가져오기 요청은 대상 아이템 위치로 이동해 아이템을 습득한 뒤 명령 기준 위치로 복귀하는 행동으로 해석한다.",
    "tags": ["가져오기", "복귀", "전달", "규칙"]
  }
]
```

### 9.2 Unity Runtime State 구조

Unity는 현재 씬의 실제 오브젝트 정보를 내부적으로 관리한다. 이 데이터는 매 요청마다 FastAPI로 전체 전송하지 않고, MCP Tool 호출에 대한 응답으로 필요한 부분만 반환한다.

```json
{
  "scene_id": "demo_scene_01",
  "agent": {
    "agent_id": "NPC_01",
    "position": {
      "x": 0.0,
      "y": 0.0
    },
    "state": "idle",
    "inventory": []
  },
  "requesters": [
    {
      "requester_id": "Player_01",
      "position": {
        "x": 0.0,
        "y": 0.0
      }
    }
  ],
  "objects": [
    {
      "object_id": "Apple_01",
      "type": "item",
      "display_name": "빨간 사과",
      "aliases": ["사과", "애플", "과일"],
      "position": {
        "x": 3.0,
        "y": 5.0
      },
      "area_hint": "나무 아래",
      "status": "available"
    },
    {
      "object_id": "Potion_Red_01",
      "type": "item",
      "display_name": "빨간 포션",
      "aliases": ["포션", "물약", "회복약"],
      "position": {
        "x": -3.0,
        "y": 8.0
      },
      "area_hint": "창고 옆",
      "status": "available"
    }
  ]
}
```

### 9.3 오브젝트 상태값

| 상태값 | 의미 |
|---|---|
| `available` | 씬에 존재하며 습득 가능 |
| `collected` | 이미 습득됨 |
| `disabled` | 현재 비활성화됨 |
| `blocked` | 접근 불가능한 위치에 있음 |

---

## 10. API 설계

### 10.1 `POST /command`

Unity에서 사용자 자연어 명령을 백엔드로 전달하는 현재 구현 API이다.

이 API는 현재 씬 전체 상태를 전달하지 않는다. 백엔드는 OpenAI 구조화 응답으로 command JSON만 생성해서 반환하며, Unity local HTTP server를 다시 호출하지 않는다.

#### 요청 예시

```json
{
  "message": "사과를 가져와"
}
```

#### 응답 예시

```json
{
  "status": "ok",
  "input": "사과를 가져와",
  "command": {
    "action": "fetch",
    "destination": null,
    "item": "사과",
    "message": "사과를 가져올게."
  }
}
```

#### command 필드 규칙

| 필드 | 의미 |
|---|---|
| `action` | 실행할 행동. 현재는 `move`, `fetch`, `null`을 사용한다. |
| `destination` | `move` 행동의 목적지. 필요 없으면 `null`이다. |
| `item` | `fetch` 행동의 대상 아이템. 필요 없으면 `null`이다. |
| `message` | Unity UI 또는 Console에 표시할 응답 메시지이다. |

질문, 설명 요청, 잡담처럼 실제 NPC 행동이 필요 없는 입력은 `action`, `destination`, `item`을 `null`로 반환하고 `message`만 채운다.

### 10.2 `GET /health/openai`

OpenAI 모델 연결과 command 구조화 응답을 확인하는 API이다. `/command`와 동일한 `parse_command()` 흐름을 사용한다.

#### 요청 예시

```text
GET /health/openai?message=사과나무에는 뭐가 열리지?
```

#### 응답 예시

```json
{
  "status": "ok",
  "input": "사과나무에는 뭐가 열리지?",
  "command": {
    "action": null,
    "destination": null,
    "item": null,
    "message": "사과나무에는 사과가 열립니다."
  }
}
```

### 10.3 `GET /health`

백엔드 서버 상태를 확인하는 API이다.

#### 응답 예시

```json
{
  "status": "ok",
  "service": "actnpc-backend",
  "version": "0.1.0"
}
```

### 10.4 향후 확장 API

Planner 기반 Action Queue가 도입되면 `/agent/command`와 `/agent/action-result`를 추가한다. 이 확장 API에서도 전체 씬 상태를 매 요청마다 보내지 않고, 필요한 월드 상태만 MCP Tool로 조회한다.

확장된 `/agent/command` 응답은 다음과 같은 Action Queue 형태를 사용할 수 있다.

```json
{
  "header": {
    "status": "success",
    "request_id": "req_001",
    "agent_id": "NPC_01"
  },
  "payload": {
    "text_response": "사과를 찾았습니다. 가져다드리겠습니다.",
    "actions": [
      {
        "action_id": "act_001",
        "command": "MOVE_TO",
        "params": {
          "target_id": "Apple_01"
        }
      },
      {
        "action_id": "act_002",
        "command": "GET_ITEM",
        "params": {
          "target_id": "Apple_01"
        }
      }
    ]
  }
}
```

---

## 11. 기술 스택

| 구분 | 기술 요소 | 적용 방식 |
|---|---|---|
| Game Engine | Unity 2D, C# | NPC, 아이템, UI, Action 실행 구현 |
| Backend | FastAPI, Python | 현재는 OpenAI 구조화 응답 기반 command JSON 생성, 향후 MCP Tool 호출과 Planner 실행 |
| VectorDB | ChromaDB 또는 FAISS | 게임 세계 배경지식 검색 |
| LLM | Local LLM 또는 API 교체 가능 구조 | 의도 분석 및 응답 생성 보조 |
| Tool Protocol | MCP Tool 호출 구조 | 필요한 지식 및 현재 월드 상태 조회 |
| Communication | HTTP JSON | Unity → FastAPI `/command` 요청, FastAPI → Unity command 응답. 백엔드의 Unity local HTTP 재호출은 기본 경로에서 제거 |
| Movement | NavMeshPlus 또는 좌표 기반 이동 | NPC 이동 구현 |

---

## 12. 구현 단계

### 1단계. Unity 기본 씬 및 NPC 구성

- Unity 2D 프로젝트 생성
- 데모용 단일 씬 구성
- NPC 오브젝트 생성
- 아이템 오브젝트 배치
- 사용자 입력 UI 구성
- 결과 메시지 UI 구성

### 2단계. Unity Runtime State 및 MCP Tool Provider 구현

- NPC 현재 위치 관리
- 아이템 오브젝트 ID 관리
- 아이템 좌표 및 상태 관리
- 인벤토리 데이터 구조 구현
- 현재 단계에서는 `NpcActController`가 command를 직접 실행
- 향후 Planner 확장 단계에서 `find_object` Tool 구현
- 향후 Planner 확장 단계에서 `get_object_state` Tool 구현
- 향후 Planner 확장 단계에서 `get_agent_state` Tool 구현
- 향후 Planner 확장 단계에서 `get_requester_state` Tool 구현
- 필요한 상태만 반환하도록 Tool 응답 최적화

### 3단계. FastAPI 백엔드 구축

- `/health` API 구현
- `/health/openai` API 구현
- `/command` API 구현
- Unity 요청 `message` 수신
- `action`, `destination`, `item`, `message` command JSON 스키마 정의
- 백엔드에서 Unity local HTTP server를 재호출하지 않도록 명령 처리 경로 단순화
- 요청/응답 로그 출력

### 4단계. VectorDB 기반 세계지식 검색 구현

- 게임 세계 배경지식 문서 작성
- 아이템 의미 정보 문서 작성
- 장소 설명 문서 작성
- 행동 규칙 문서 작성
- 향후 Planner 확장 단계에서 `search_world_knowledge` MCP Tool 구현

### 5단계. MCP Tool 호출 제어 구현

- 향후 Planner 확장 단계에서 FastAPI MCP Tool 호출 Adapter 구현
- Tool 호출 결과 표준화
- Tool 실패 응답 처리
- Tool timeout 처리
- 필요한 정보만 조회하는 호출 흐름 구현

### 6단계. Planner 구현

- 향후 확장 단계에서 사용자 명령의 대상/장소/행동 의도와 월드 상태 결합
- Intent별 Action 분해 규칙 구현
- RAG 검색 결과와 MCP Tool 조회 결과 결합
- `fetch_item`: `MOVE_TO` → `GET_ITEM` → `MOVE_TO` → `DELIVER_ITEM`
- `pickup_item`: `MOVE_TO` → `GET_ITEM`
- JSON Schema 검증 및 fallback 처리

### 7단계. Unity Action Executor 구현

- `/command` 응답 JSON 파싱 구현
- `action == move` 처리 구현
- `action == fetch` 처리 구현
- `action == null`일 때 message 출력 구현
- 향후 확장을 위한 Action Queue 구현
- 향후 확장을 위한 `MOVE_TO`, `GET_ITEM`, `DELIVER_ITEM` 실행 구현
- Action 실행 성공/실패 로그 출력
- `/agent/action-result` 결과 전송은 Planner 기반 Action Queue 도입 후 구현

### 8단계. 통합 테스트 및 데모 정리

- Unity와 FastAPI 통신 테스트
- MCP Tool 조회 테스트
- 자연어 명령 처리 테스트
- 아이템 검색 및 상태 조회 테스트
- NPC 이동, 아이템 습득, 복귀 테스트
- 오류 케이스 테스트
- 최종 시연 시나리오 정리

---

## 13. 완료 기준

### 13.1 기능 완료 기준

- Unity에서 사용자 자연어 명령을 입력할 수 있다.
- Unity가 FastAPI 백엔드의 `/command` API로 명령을 전송할 수 있다.
- 백엔드가 OpenAI 구조화 응답으로 `action`, `destination`, `item`, `message` command JSON을 생성할 수 있다.
- 백엔드가 Unity local HTTP server를 다시 호출하지 않고 command JSON만 반환할 수 있다.
- Unity가 백엔드 응답의 command를 파싱할 수 있다.
- Unity가 `move`, `fetch`, `null` action을 분기 처리할 수 있다.
- 실행 결과 또는 응답 메시지가 Unity 화면 또는 Console에 출력된다.

향후 확장 완료 기준은 다음과 같다.

- 백엔드가 VectorDB에서 관련 세계지식을 검색할 수 있다.
- 백엔드가 MCP Tool을 통해 필요한 현재 오브젝트 좌표와 상태만 조회할 수 있다.
- 백엔드가 Planner를 통해 Unity 실행용 Action Queue JSON을 생성할 수 있다.
- Unity가 `MOVE_TO`, `GET_ITEM`, `DELIVER_ITEM` Action을 순차적으로 실행할 수 있다.
- Unity가 Action 실행 결과를 백엔드에 전달할 수 있다.

### 13.2 데모 성공 기준

다음 명령을 입력했을 때 NPC가 정상적으로 행동해야 한다.

```text
사과 가져와
포션 가져와
창고 옆 포션 가져와
빨간 물약 찾아서 가져와
우물 근처 열쇠 가져와
없는 아이템 가져와
```

현재 구현의 성공 케이스에서는 백엔드가 `fetch` 또는 `move` command를 반환하고, Unity가 해당 action 분기를 실행한다. Planner 확장 후에는 NPC가 대상 위치로 이동한 뒤 아이템을 습득하고, “가져와” 명령인 경우 명령 기준 위치로 복귀해 전달한다. 실패 케이스에서는 적절한 오류 메시지를 출력한다.

---

## 14. 예외 처리 정책

| 상황 | 처리 방식 |
|---|---|
| 대상 오브젝트를 찾지 못함 | `OBJECT_NOT_FOUND` 반환 |
| 대상 후보가 여러 개이고 판단 불가 | `AMBIGUOUS_TARGET` 반환 |
| 대상이 이미 습득됨 | `OBJECT_ALREADY_COLLECTED` 반환 |
| 대상 좌표를 조회할 수 없음 | `OBJECT_STATE_UNAVAILABLE` 반환 |
| 대상 위치로 이동할 수 없음 | `TARGET_UNREACHABLE` 반환 |
| NPC가 이미 다른 행동 수행 중 | `AGENT_BUSY` 반환 |
| 명령 의도를 파악하지 못함 | `INTENT_NOT_UNDERSTOOD` 반환 |
| MCP Tool 호출 실패 | `TOOL_CALL_FAILED` 반환 |
| MCP Tool 응답 timeout | `TOOL_TIMEOUT` 반환 |
| LLM 응답 파싱 실패 | Rule-based Planner로 fallback |
| 허용되지 않은 Action 생성 | Action 제거 후 오류 반환 |
| 백엔드 통신 실패 | Unity UI에 서버 연결 오류 표시 |

---

## 15. MVP 범위와 제외 범위

### 15.1 MVP 포함

- 단일 NPC
- 단일 씬
- 아이템 2~3개
- 자연어 명령 입력
- FastAPI 명령 처리 API
- VectorDB 또는 Mock RAG
- MCP Tool 기반 필요한 정보 조회
- Rule-based Planner
- `MOVE_TO`, `GET_ITEM`, `DELIVER_ITEM` 실행
- Action 실행 결과 로그

### 15.2 MVP 제외

- 다중 NPC 협업
- 전투
- 장기 기억
- 복합 퀘스트
- 실시간 스트리밍 제어
- 완전한 LLM 자율 계획
- 대규모 씬 전체 상태 동기화
- 복잡한 장애물 기반 경로 탐색

---

## 16. 기대 효과

### 16.1 기술 검증 효과

본 MVP를 통해 자연어 명령이 실제 게임 내 행동으로 변환되는 전체 흐름을 검증할 수 있다.

검증 항목은 다음과 같다.

- RAG 기반 세계지식 검색 가능성
- MCP Tool 호출 기반 필요한 월드 상태 조회 가능성
- Planner 기반 행동 계획 생성 가능성
- Unity Action Executor 기반 실제 행동 실행 가능성
- 전체 씬 상태 전송 없이 필요한 정보만 조회하는 구조의 실현 가능성

### 16.2 확장 효과

본 구조는 향후 다양한 행동으로 확장 가능하다.

예상 확장 Action은 다음과 같다.

- `OPEN_DOOR`
- `TALK_TO_NPC`
- `ATTACK_TARGET`
- `USE_ITEM`
- `FOLLOW_TARGET`
- `RETURN_TO_BASE`
- `DROP_ITEM`
- `EQUIP_ITEM`

또한 MCP Tool을 확장하면 NPC가 단순 아이템 습득을 넘어 현재 월드 상태를 필요한 시점에 조회하고, 상황에 따라 행동을 선택하는 자율 에이전트로 발전할 수 있다.

---

## 17. 최종 요약

본 프로젝트는 Unity 2D 환경에서 지능형 NPC 에이전트의 핵심 행동 루프를 구현하는 1주 MVP이다.

수정된 핵심 구조는 다음과 같다.

```text
자연어 명령
→ FastAPI 명령 수신
→ OpenAI 구조화 응답 기반 command JSON 생성
→ Unity에 command JSON 반환
→ Unity가 command.action을 직접 실행
→ Unity NPC 행동 또는 메시지 출력
```

현재 구현에서는 백엔드가 OpenAI API 호출 후 Unity local HTTP server를 다시 호출하지 않는다. 이로써 `Unity → FastAPI → Unity 응답` 구조가 되고, 불필요한 `FastAPI → Unity local HTTP server` 왕복을 제거한다.

VectorDB는 향후 게임 세계에 대한 배경지식과 규칙을 담당하고, 실제 아이템 좌표와 상태는 MCP Tool을 통해 Unity Runtime에서 조회한다. 명령마다 현재 씬의 전체 정보를 백엔드로 전송하지 않고, 사용자 명령에 필요한 정보만 MCP Tool로 가져온다.

Planner 확장 단계에서는 MCP Tool 호출 결과를 바탕으로 high-level intent를 Unity Action 단위로 분해한다. 예를 들어 “사과를 가져와”는 `fetch_item` intent로 해석되고, `MOVE_TO(target)` → `GET_ITEM(target)` → `MOVE_TO(requester)` → `DELIVER_ITEM(target)` 순서의 Action으로 변환된다.

이를 통해 현재 단계에서는 통신 왕복과 연결 생성 비용을 줄이고, 확장 단계에서는 지식 검색과 현재 상태 조회를 명확히 분리하면서 MCP Tool Layer로 일관된 호출 구조를 유지할 수 있다.