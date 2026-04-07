# OpenClaw 아키텍처 — 에이전트 시스템 구조와 동작 원리

최종 수정: 2026-04-04
대상 버전: OpenClaw 2026.4.2 (d74a122)
서버: Oracle ARM 168.107.51.82 (ubuntu)

---

## 1. 전체 구조

```
┌─────────────────────────────────────────────────────────────┐
│                    Oracle ARM 서버                           │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │           Gateway (systemd 서비스)                     │  │
│  │           ws://127.0.0.1:18789                        │  │
│  │                                                       │  │
│  │   ┌─────────┐  ┌─────────┐  ┌─────────┐             │  │
│  │   │ Agent:  │  │ Agent:  │  │ Agent:  │  ...         │  │
│  │   │  main   │  │ bench-  │  │ bench-  │              │  │
│  │   │(default)│  │nemotron │  │ judge   │              │  │
│  │   └────┬────┘  └────┬────┘  └────┬────┘             │  │
│  │        │             │            │                   │  │
│  └────────┼─────────────┼────────────┼───────────────────┘  │
│           │             │            │                       │
│  ┌────────▼──┐  ┌───────▼───┐  ┌────▼──────────┐           │
│  │OpenRouter │  │OpenRouter  │  │Azure OpenAI   │           │
│  │ Nemotron  │  │ Nemotron   │  │ GPT-5.3-chat  │           │
│  │  (free)   │  │  (free)    │  │               │           │
│  └───────────┘  └───────────┘  └───────────────┘           │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              Auth Profiles                             │  │
│  │  ~/.openclaw/agents/main/agent/auth-profiles.json     │  │
│  │  ├─ openrouter:default  (sk-or-v1-...)                │  │
│  │  ├─ modelstudio:default (sk-...)                      │  │
│  │  ├─ azure-openai:default (DRL0Hth...)                 │  │
│  │  └─ upstage:default     (up_kbR...)                   │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

OpenClaw은 **게이트웨이 + 에이전트** 구조로 작동한다. 게이트웨이가 WebSocket 서버로 상주하며, 에이전트들이 게이트웨이를 통해 LLM API를 호출한다.


## 2. 게이트웨이 (Gateway)

게이트웨이는 OpenClaw의 중심 프로세스다. systemd user 서비스로 백그라운드 실행된다.

**서비스 파일**: `~/.config/systemd/user/openclaw-gateway.service`

```
[Service]
ExecStart=/usr/bin/node /.../openclaw/dist/index.js gateway --port 18789
Environment=AZURE_OPENAI_API_VERSION=2025-03-01-preview
```

**주요 역할:**
- WebSocket 서버로 에이전트 요청 수신 (ws://127.0.0.1:18789)
- LLM Provider로 HTTP 요청 프록시 (auth, 헤더, URL 구성 처리)
- 세션/대화 이력 관리 (`.jsonl` 파일)
- 모델 카탈로그 관리 (config에 정의된 provider + model 목록)

**관리 명령어:**

| 명령어 | 기능 |
|--------|------|
| `openclaw gateway restart` | 서비스 재시작 (config 변경 반영) |
| `openclaw gateway status` | 서비스 상태 + 포트 프로브 |
| `openclaw gateway run` | 포그라운드 실행 (디버깅용) |
| `openclaw health` | 게이트웨이 헬스 체크 |


## 3. 에이전트 (Agent)

에이전트는 **격리된 작업 단위**다. 각 에이전트는 고유한 모델, workspace, 세션 이력을 가진다.

### 3.1 에이전트 구성 요소

```
~/.openclaw/agents/{agent-id}/
├── agent/
│   ├── auth-profiles.json     ← API 키 (글로벌 공유)
│   └── models.json            ← 에이전트별 모델 설정 (글로벌 상속)
└── sessions/
    ├── {uuid}.jsonl           ← 대화 이력 (턴별 기록)
    └── sessions.json          ← 세션 인덱스
```

**workspace** 디렉토리는 에이전트가 파일을 읽고 쓰는 작업 공간이다:

```
~/.openclaw/workspace/         ← main 에이전트의 workspace
├── AGENTS.md                  ← 에이전트 역할/행동 정의
├── BOOTSTRAP.md               ← 초기 컨텍스트 (매 대화 시작 시 주입)
├── SOUL.md                    ← 에이전트 성격/톤 정의
├── IDENTITY.md                ← 에이전트 이름/자기 인식
├── USER.md                    ← 사용자 정보
├── TOOLS.md                   ← 사용 가능한 도구 목록
└── HEARTBEAT.md               ← 헬스 체크 응답 규칙
```

### 3.2 에이전트의 모델 배정

에이전트에 모델이 배정되는 3가지 계층:

```
우선순위 (높음 → 낮음)
─────────────────────
1. 에이전트 생성 시 지정: openclaw agents add <id> --model <model>
   → agents.list[].model 에 저장
   → 해당 에이전트의 모든 요청이 이 모델로 고정

2. 글로벌 기본 모델: openclaw models set <model>
   → agents.defaults.model 에 저장
   → 에이전트에 모델이 명시되지 않은 경우 사용

3. fallback 목록: openclaw models fallbacks set <model1>,<model2>
   → 1, 2순위 모델 호출 실패 시 순차 시도
```

**자동 라우팅(작업 유형에 따른 모델 자동 선택)은 없다.** 모든 모델 배정은 수동이다.

### 3.3 에이전트 생성과 삭제

```bash
# 생성
openclaw agents add bench-nemotron \
  --model openrouter/nvidia/nemotron-3-super-120b-a12b:free \
  --workspace /tmp/pinchbench/0015/agent_workspace \
  --non-interactive

# 목록 확인
openclaw agents list

# 삭제
openclaw agents delete bench-nemotron --force
```

에이전트는 사전에 생성해 둘 수도 있고, 스크립트(PinchBench 등)가 실행 시점에 동적으로 생성할 수도 있다. 삭제하지 않는 한 영구적으로 남는다.

### 3.4 에이전트에 메시지 보내기

```bash
# 단일 메시지 전송 (에이전트의 모델이 응답)
openclaw agent --agent bench-nemotron \
  --session-id "task_00_12345" \
  --message "Say hello"

# --local 플래그: 게이트웨이 경유 없이 임베디드 모드로 직접 실행
openclaw agent --agent main --local -m "테스트"
```

`openclaw agent` (단수)는 실행 명령, `openclaw agents` (복수)는 관리 명령이다.


## 4. 모델과 Provider

### 4.1 Provider 구조

```
openclaw.json → models.providers
├── openrouter     (api: openai-completions)
│   └── nemotron-3-super-120b-a12b:free, auto, arcee-ai/..., qwen/...
├── modelstudio    (api: openai-completions)
│   └── qwen3.5-plus, glm-5, glm-4.7, kimi-k2.5, MiniMax-M2.5, ...
├── azure-openai   (api: azure-openai-responses)
│   └── gpt-5.3-chat
└── upstage        (api: openai-completions, baseUrl: api.upstage.ai/v1)
    └── solar-pro3 (reasoning: true, compat.supportsReasoningEffort: true)
```

**모델 레퍼런스 형식**: `{provider}/{model-id}`
- `openrouter/nvidia/nemotron-3-super-120b-a12b:free`
- `modelstudio/glm-5`
- `azure-openai/gpt-5.3-chat`
- `upstage/solar-pro3`

### 4.2 모델이 models list에 표시되려면

두 곳에 모두 등록이 필요하다:

1. **Provider 정의**: `models.providers.{provider}.models[]` — 모델 메타데이터 (contextWindow, maxTokens 등)
2. **Allowed 목록**: `agents.defaults.models["{provider}/{model-id}"]` — 에이전트가 사용할 수 있는 모델 화이트리스트

둘 중 하나라도 빠지면 `openclaw models list`에 나타나지 않는다.

### 4.2a 모델 Alias와 Params

모델별 추가 파라미터가 필요할 때 `agents.defaults.models`에서 `params`를 사용한다:

```json
{
  "agents": {
    "defaults": {
      "models": {
        "upstage/solar-pro3": { "params": { "reasoning_effort": "high" } }
      }
    }
  }
}
```

- `params`: API 요청 body에 병합되는 추가 파라미터 (예: `reasoning_effort`)

### 4.3 인증 (Auth Profiles)

API 키는 `auth-profiles.json`에 provider별로 저장된다:

```json
{
  "profiles": {
    "openrouter:default":   { "type": "api_key", "provider": "openrouter",   "key": "sk-or-..." },
    "modelstudio:default":  { "type": "api_key", "provider": "modelstudio",  "key": "sk-..." },
    "azure-openai:default": { "type": "api_key", "provider": "azure-openai", "key": "DRL0..." },
    "upstage:default":      { "type": "api_key", "provider": "upstage",      "key": "up_..." }
  }
}
```

Azure OpenAI는 특수 처리된다:
- `authHeader: false` — 표준 `Authorization: Bearer` 헤더 비활성화
- 내부적으로 `AzureOpenAI` 클래스가 `api-key` 헤더를 자체 구성
- `AZURE_OPENAI_API_VERSION` 환경변수로 API 버전 지정 (현재 `2025-03-01-preview`)

### 4.4 API 타입

| api 값 | 용도 |
|--------|------|
| `openai-completions` | OpenAI 호환 Chat Completions API (DashScope, OpenRouter 등) |
| `openai-responses` | OpenAI Responses API (직접 OpenAI 사용 시) |
| `azure-openai-responses` | Azure OpenAI Responses API |
| `anthropic-messages` | Anthropic Messages API |
| `google-generative-ai` | Google Gemini |
| `ollama` | 로컬 Ollama |


## 5. 설정 파일 구조

```
~/.openclaw/
├── openclaw.json              ← 메인 설정 파일 (모든 config의 근원)
│   ├── agents.defaults.model       ← 기본 모델
│   ├── agents.defaults.models      ← 허용 모델 목록 + alias
│   ├── agents.list                 ← 에이전트 정의
│   ├── models.providers            ← Provider + 모델 메타데이터
│   ├── gateway                     ← 게이트웨이 포트/바인딩/인증
│   └── tools/plugins/session       ← 기타 설정
├── openclaw.json.bak          ← 설정 변경 시 자동 백업
├── workspace/                 ← main 에이전트 workspace
├── agents/                    ← 에이전트별 디렉토리
│   ├── main/
│   │   ├── agent/
│   │   │   ├── auth-profiles.json
│   │   │   └── models.json
│   │   └── sessions/
│   ├── bench-openrouter-nvidia-.../
│   └── ...
└── credentials/               ← OAuth 인증 정보 (미사용)
```

### 5.1 주요 설정 명령어

```bash
# 값 읽기
openclaw config get models.providers.azure-openai

# 값 쓰기 (키에 . 이나 / 포함 시 config set이 실패할 수 있음 — python으로 JSON 직접 편집)
openclaw config set agents.defaults.model "openrouter/nvidia/nemotron-3-super-120b-a12b:free"

# 모델 기본값 변경
openclaw models set azure-openai/gpt-5.3-chat

# 모델 목록 확인
openclaw models list          # 허용된 모델만
openclaw models list --all    # 전체 카탈로그
openclaw models status --json # 상세 상태 (auth, allowed 포함)
```


## 6. 현재 서버 에이전트 현황 (2026-04-04)

| Agent ID | 모델 | Workspace | 용도 |
|----------|------|-----------|------|
| **main** (default) | Nemotron 120B (free) | `~/.openclaw/workspace` | 일반 대화/작업 |
| bench-arcee-ai-trinity-large-preview-free | arcee-ai/trinity-large-preview:free | `/tmp/pinchbench/0001/` | PinchBench 잔여 (제외 대상) |
| bench-openrouter-arcee-ai-trinity-large-preview-free | openrouter/arcee-ai/trinity-large-preview:free | `/tmp/pinchbench/0012/` | PinchBench 잔여 (제외 대상) |
| bench-openrouter-qwen-qwen3-coder-free | openrouter/qwen/qwen3-coder:free | `/tmp/pinchbench/0014/` | PinchBench 잔여 (제외 대상) |
| bench-openrouter-nvidia-nemotron-3-super-120b-a12b-free | openrouter/nvidia/nemotron-3-super-120b-a12b:free | `/tmp/pinchbench/0015/` | PinchBench Nemotron 테스트 |

`bench-arcee-*`와 `bench-openrouter-qwen-*`은 모델 제외 결정(2026-04-04) 이전의 잔여물이다. 정리 가능하지만 방치해도 리소스 소모는 없다.


## 7. 데이터 흐름 요약

```
사용자/스크립트
    │
    ▼
openclaw agent --agent <id> --message "..."
    │
    ▼
Gateway (ws://127.0.0.1:18789)
    │
    ├─ 에이전트 ID로 모델 결정
    ├─ auth-profiles.json에서 API 키 조회
    ├─ Provider 어댑터가 HTTP 요청 구성
    │   ├─ openai-completions → POST {baseUrl}/chat/completions
    │   ├─ openai-responses   → POST {baseUrl}/responses
    │   └─ azure-openai-responses → AzureOpenAI SDK 사용
    │       (api-version 자동 추가, api-key 헤더 자동 처리)
    │
    ▼
LLM Provider (OpenRouter / DashScope / Azure / Upstage)
    │
    ▼
응답 스트리밍 → 세션 기록 (.jsonl) → 사용자에게 반환
```
