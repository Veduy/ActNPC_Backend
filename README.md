# ActNPC Backend

Unity 2D 지능형 NPC 에이전트 MVP를 위한 FastAPI 백엔드입니다.

현재 구현은 전체 Planner/API 완성 전 단계이며, 서버 상태 확인과 OpenAI 구조화 응답 확인 기능까지만 포함합니다.

## 현재 구현된 내용

### FastAPI 서버

- `FastAPI` 앱 생성
- 서비스 이름: `actnpc-backend`
- 버전: `0.1.0`
- `uvicorn`으로 `main.py` 직접 실행 가능

### 환경 변수 로드

- `python-dotenv`의 `load_dotenv()` 사용
- `.env`의 `OPENAI_API_KEY`를 `os.environ["OPENAI_API_KEY"]`에 설정

### OpenAI / LangChain 연결

- `langchain.chat_models.init_chat_model("gpt-4.1")` 사용
- `with_structured_output(CommandDict)`로 자연어 입력을 구조화된 명령 형태로 변환

### 구조화 응답 스키마

`CommandDict`는 다음 필드를 가진다.

```json
{
  "action": "move 또는 fetch 또는 null",
  "destination": "목적지 또는 null",
  "item": "아이템 또는 null",
  "message": "사용자에게 보여줄 응답 메시지"
}
```

규칙:

- 사용자가 NPC에게 명확히 행동을 지시한 경우에만 `action`, `destination`, `item`을 채운다.
- 질문, 정보 요청, 잡담처럼 NPC가 실제 행동할 필요가 없는 입력은 `action`, `destination`, `item`을 모두 `null`로 반환한다.
- 예: `사과나무에는 뭐가 열리지?`는 행동 명령이 아니므로 `action: null`로 처리한다.

## API

### `GET /health`

백엔드 서버 상태를 확인한다.

응답 예시:

```json
{
  "status": "ok",
  "service": "actnpc-backend",
  "version": "0.1.0"
}
```

### `GET /health/openai`

OpenAI 모델 호출과 구조화 응답을 확인한다.

Query Parameter:

- `message`: 자연어 입력 문자열

요청 예시:

```text
GET /health/openai?message=사과나무에는 뭐가 열리지?
```

응답 예시:

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

OpenAI 호출 실패 시 `503` 상태 코드와 오류 메시지를 반환한다.

## 실행

의존성이 이미 설치되어 있다는 전제에서 다음 명령으로 실행한다.

```bash
uvicorn main:app --reload
```

또는:

```bash
python main.py
```

## 아직 구현되지 않은 내용

- `/agent/command` API
- `/agent/action-result` API
- RAG / VectorDB 기반 세계지식 검색
- MCP Tool 호출 Adapter
- Unity Runtime State 조회
- Planner 기반 Action 배열 생성
- Unity Action Executor 연동

자세한 MVP 설계는 `unity_2d_intelligent_agent_mvp_plan.md`를 기준으로 한다.
