# Unity 지능형 NPC Agent 기획서

**문서 목적:** Unity 클라이언트와 FastAPI 백엔드를 WebSocket으로 연결하여, 자연어 명령을 NPC 행동으로 변환하는 MVP 구조를 정의한다.  

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