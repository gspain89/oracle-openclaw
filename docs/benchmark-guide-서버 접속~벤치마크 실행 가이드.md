# OpenClaw 벤치마크 실행 가이드

이 문서는 Oracle ARM 서버에서 PinchBench와 ClawBench-KO를 실행하는 방법을 설명한다.

## 1. 서버 접속

```bash
ssh -i ~/Coding/oracle-openclaw/key/ssh-key-2026-04-03.key ubuntu@168.107.51.82
```

접속 후 NVM을 활성화해야 `openclaw` CLI를 쓸 수 있다:

```bash
source ~/.nvm/nvm.sh
```

> 서버: Oracle ARM 4 OCPU / 24GB RAM, Ubuntu, OpenClaw 2026.4.2

## 2. 등록된 모델 목록

```bash
openclaw models list
```

벤치마크 대상 모델 (`server/config/models.json` 기준):

| 모델 ID | 프로바이더 | 무료 | 비고 |
|---------|-----------|------|------|
| `modelstudio/qwen3.5-27b` | DashScope | - | 27B |
| `modelstudio/qwen3.5-plus` | DashScope | - | 72B, 응답 속도 빠름 |
| `modelstudio/qwen3.5-122b-a10b` | DashScope | 무료 | 122B MoE (10B active) |
| `modelstudio/qwen3-8b` | DashScope | 무료 | 8B, 베이스라인 |
| `modelstudio/glm-5` | DashScope (Z.AI) | - | 400B |
| `modelstudio/glm-5.1` | DashScope (Z.AI) | - | 600B |
| `openrouter/nvidia/nemotron-3-super-120b-a12b:free` | OpenRouter | 무료 | 120B, TTFT 변동 주의 |
| `upstage/solar-pro3` | Upstage | - | 102B MoE (12B active), reasoning_effort: high |

Judge 모델:

| 모델 ID | 용도 |
|---------|------|
| `azure-openai/gpt-5.3-chat` | LLM judge 채점용 (Azure) |

## 3. 새 모델 등록

DashScope 모델을 추가하려면 서버에서:

```bash
python3 << 'PYEOF'
import json

MODEL_ID = "새모델-id"           # DashScope 모델 이름
CONTEXT_WINDOW = 131072          # 컨텍스트 크기 (토큰)

with open("/home/ubuntu/.openclaw/openclaw.json") as f:
    d = json.load(f)

# 모델 등록
d["agents"]["defaults"]["models"][f"modelstudio/{MODEL_ID}"] = {}

# 프로바이더에 모델 정의 추가
d["models"]["providers"]["modelstudio"]["models"].append({
    "id": MODEL_ID,
    "name": MODEL_ID,
    "reasoning": False,
    "input": ["text"],
    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    "contextWindow": CONTEXT_WINDOW,
    "maxTokens": 65536,
    "api": "openai-completions",
})

with open("/home/ubuntu/.openclaw/openclaw.json", "w") as f:
    json.dump(d, f, indent=2, ensure_ascii=False)

print(f"OK - modelstudio/{MODEL_ID} 등록 완료")
PYEOF
```

등록 확인:

```bash
openclaw models list | grep 새모델
```

API 동작 테스트:

```bash
openclaw agents add test-agent --model modelstudio/새모델-id --workspace /tmp/test-ws --non-interactive
openclaw agent --agent test-agent --session-id test1 --timeout 30 --message "Say hello"
openclaw agents delete test-agent --force
```

### Upstage 등 비-DashScope 프로바이더 등록

DashScope 외 프로바이더(Upstage, OpenRouter 등)는 별도 프로바이더를 생성해야 한다:

```bash
python3 << 'PYEOF'
import json

PROVIDER_NAME = "upstage"                            # 프로바이더 ID
BASE_URL = "https://api.upstage.ai/v1"               # API 엔드포인트
MODEL_ID = "solar-pro3"                              # API 모델명
API_KEY = "up_..."                                   # API 키
CONTEXT_WINDOW = 131072

with open("/home/ubuntu/.openclaw/openclaw.json") as f:
    d = json.load(f)

# 프로바이더 생성
d["models"]["providers"][PROVIDER_NAME] = {
    "baseUrl": BASE_URL,
    "api": "openai-completions",
    "models": [{
        "id": MODEL_ID,
        "name": MODEL_ID,
        "reasoning": True,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": CONTEXT_WINDOW,
        "maxTokens": 65536,
        "compat": {"supportsReasoningEffort": True, "thinkingFormat": "openai"}
    }]
}

# 허용 모델 등록
d["agents"]["defaults"]["models"][f"{PROVIDER_NAME}/{MODEL_ID}"] = {}

with open("/home/ubuntu/.openclaw/openclaw.json", "w") as f:
    json.dump(d, f, indent=2, ensure_ascii=False)

print(f"OK - {PROVIDER_NAME}/{MODEL_ID} 프로바이더 등록 완료")
PYEOF

# API 키 등록 (auth-profiles.json)
python3 << 'PYEOF'
import json
with open("/home/ubuntu/.openclaw/agents/main/agent/auth-profiles.json") as f:
    auth = json.load(f)
auth["profiles"]["upstage:default"] = {
    "type": "api_key", "provider": "upstage", "key": "up_..."
}
with open("/home/ubuntu/.openclaw/agents/main/agent/auth-profiles.json", "w") as f:
    json.dump(auth, f, indent=2, ensure_ascii=False)
print("OK - API 키 등록 완료")
PYEOF
```

### 모델 파라미터 설정 (예: reasoning_effort)

모델에 추가 API 파라미터가 필요하면 `agents.defaults.models`에서 `params`로 설정한다:

```bash
python3 << 'PYEOF'
import json
with open("/home/ubuntu/.openclaw/openclaw.json") as f:
    d = json.load(f)

d["agents"]["defaults"]["models"]["upstage/solar-pro3"] = {
    "params": {"reasoning_effort": "high"}
}

with open("/home/ubuntu/.openclaw/openclaw.json", "w") as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
print("OK - params 설정 완료")
PYEOF
```

### models.json에도 등록

`run-all.sh` → `normalize.py` 파이프라인이 모델을 인식하려면 `server/config/models.json`에도 추가해야 한다:

```json
{
  "id": "새모델-id",
  "provider": "dashscope",
  "name": "표시 이름",
  "provider_label": "DashScope (제조사)",
  "free": true,
  "input_price_per_1m": 0,
  "output_price_per_1m": 0,
  "params_b": 8,
  "context_window_tokens": 131072,
  "notes": "메모"
}
```

> models.json에 없는 모델의 벤치마크 결과는 normalize.py가 WARN 로그를 출력하고 리더보드에서 제외된다.

## 4. ClawBench-KO 실행

한국어 에이전트 벤치마크, 10개 태스크.

### 위치

```bash
cd ~/oracle-openclaw/server/claw-bench-ko
```

### 기본 실행 (1회)

```bash
python3 runner.py --model modelstudio/qwen3-8b
```

### 3회 실행 (best/average 산출)

```bash
python3 runner.py --model modelstudio/qwen3-8b --runs 3
```

### 전체 옵션

```
python3 runner.py \
  --model <모델ID>           # 필수. OpenClaw 모델 ID
  --judge <judge모델ID>      # 기본: azure-openai/gpt-5.3-chat
  --task <태스크들>           # 특정 태스크만 실행 (쉼표 구분)
  --runs <횟수>              # 반복 횟수 (기본: 1)
  --output-dir <경로>        # 결과 저장 경로
  --verbose                  # 상세 로그 (워크스페이스 파일, stdout)
  --no-fail-fast             # 첫 태스크 0점이어도 계속
  --dry-run                  # 실행 없이 태스크 목록만 확인
```

### 실행 예시

```bash
# 태스크 목록 확인
python3 runner.py --model modelstudio/qwen3-8b --dry-run

# 특정 태스크만 테스트
python3 runner.py --model modelstudio/qwen3-8b --task invoice_gen,addr_parse --verbose

# 프로덕션 3회 실행 (백그라운드)
export PYTHONUNBUFFERED=1
nohup python3 runner.py \
  --model modelstudio/qwen3-8b \
  --runs 3 \
  --no-fail-fast \
  > /tmp/clawbench-ko.log 2>&1 &

# 실시간 로그 확인
tail -f /tmp/clawbench-ko.log
```

### 태스크 목록

| # | ID | 이름 | 채점 방식 |
|---|-----|------|----------|
| 1 | addr_parse | 한국 주소 파싱 | automated |
| 2 | num_convert | 한글 숫자 변환 | automated |
| 3 | phone_normalize | 전화번호 정규화 | automated |
| 4 | csv_transform | 은행 거래 CSV 변환 | hybrid |
| 5 | meeting_minutes | 회의록 작성 | llm_judge |
| 6 | biz_email | 비즈니스 이메일 작성 | llm_judge |
| 7 | news_summary | 뉴스 브리핑 요약 | llm_judge |
| 8 | invoice_gen | 세금계산서 생성 | hybrid |
| 9 | resume_parse | 이력서 파싱 | hybrid |
| 10 | regulation_extract | 법규 요구사항 추출 | hybrid |

### 출력 형식

실행 중:
```
📋 Task 3/10 (Run 1/3)
🤖 Agent starting task: phone_normalize
   Task: 전화번호 정규화
   Category: data_processing
✅ Task phone_normalize: 1.0/1.0 (100%) - automated
```

완료 후:
```
📊 Final score: 8.50/10 (85.0%)

🦀 CLAWBENCH-KO SCORE SUMMARY
   Overall Score: 85.0% (8.5 / 10.0)
   CATEGORY                    SCORE        TASKS
   --------------------------------------------
   🟢 DATA_PROCESSING        96.3%      3 tasks
   🟡 DOCUMENT_GENERATION    72.0%      3 tasks
   🟢 KOREAN_SYSTEM          91.5%      4 tasks
```

### 결과 파일

`results/<모델슬러그>_<타임스탬프>/results.json`

주요 필드:
- `overall_score.mean` — 전체 평균 점수 (0~1)
- `tasks[].grading.mean` — 태스크별 평균 점수
- `tasks[].grading.std` — 표준편차 (runs > 1일 때)
- `tasks[].grading.min/max` — 최저/최고 점수

## 5. PinchBench 실행

영어 에이전트 벤치마크, 24개 태스크.

### 위치

```bash
cd ~/pinchbench-skill
```

### 기본 실행 (1회)

```bash
uv run scripts/benchmark.py \
  --model modelstudio/qwen3-8b \
  --judge azure-openai/gpt-5.3-chat \
  --no-upload \
  --no-fail-fast
```

### 3회 실행 (best/average 산출)

```bash
uv run scripts/benchmark.py \
  --model modelstudio/qwen3-8b \
  --judge azure-openai/gpt-5.3-chat \
  --runs 3 \
  --no-upload \
  --no-fail-fast
```

### 전체 옵션

```
uv run scripts/benchmark.py \
  --model <모델ID>               # 필수. OpenClaw 모델 ID
  --judge <judge모델ID>          # judge 모델 (기본: claude-opus-4.5, 우리는 gpt-5.3 사용)
  --suite <태스크지정>            # "all" (기본), "automated-only", 또는 쉼표 구분 태스크 ID
  --runs <횟수>                  # 반복 횟수 (기본: 1)
  --output-dir <경로>            # 결과 저장 경로 (기본: results/)
  --timeout-multiplier <배수>    # 타임아웃 배수 (기본: 1.0)
  --verbose                      # 상세 로그
  --no-upload                    # 리더보드 업로드 안 함
  --no-fail-fast                 # sanity check 실패해도 계속
```

### 실행 예시

> **참고**: `run-pinchbench.sh`는 항상 full 24 tasks를 실행한다.
> 아래는 PinchBench CLI를 직접 호출하는 경우의 예시다.

```bash
# automated 태스크만 빠르게 테스트 (judge 불필요, ~5분)
uv run scripts/benchmark.py \
  --model modelstudio/qwen3-8b \
  --suite automated-only \
  --no-upload

# 특정 태스크만 테스트
uv run scripts/benchmark.py \
  --model modelstudio/qwen3-8b \
  --suite task_00_sanity,task_01_calendar \
  --judge azure-openai/gpt-5.3-chat \
  --no-upload --verbose

# 프로덕션 3회 실행 (백그라운드, ~3시간)
nohup uv run scripts/benchmark.py \
  --model modelstudio/qwen3-8b \
  --judge azure-openai/gpt-5.3-chat \
  --runs 3 \
  --no-upload \
  --no-fail-fast \
  --verbose \
  > /tmp/pinchbench.log 2>&1 &

# 실시간 로그 확인
tail -f /tmp/pinchbench.log
```

### 출력 형식

```
📋 Task 5/24 (Run 1/3)
✅ Task task_04_weather: 1.0/1.0 (100%) - automated
⚠�� Task task_03_blog: 0.6/1.0 (60%) - llm_judge
❌ Task task_13_image_gen: 0.0/1.0 (0%) - hybrid

📊 Final score: 20.88/24 (87.0%)

🦀 PINCHBENCH SCORE SUMMARY
   Overall Score: 87.0% (20.9 / 24.0)
   CATEGORY              SCORE        TASKS
   🟢 BASIC            100.0%      1 task
   🟢 CODING            95.0%      4 tasks
   ...
```

### 결과 파일

`results/<run_id>_<모델슬러그>.json`

주요 필드:
- `tasks[].grading.mean` — 태스크별 평균 점수
- `tasks[].grading.std/min/max` — 통계
- `efficiency.total_tokens` — 총 토큰 사용량
- `efficiency.total_cost_usd` — 총 비용

## 6. 실행 체크리스트

벤치마크 실행 전 확인사항:

- [ ] 모델이 OpenClaw에 등록되어 있는가 (`openclaw models list`)
- [ ] DashScope 모델의 free quota가 남아 있는가 (Model Studio 콘솔 확인)
- [ ] OpenClaw gateway가 실행 중인가 (`ps aux | grep openclaw-gateway`)
- [ ] `openclaw` CLI가 PATH에 있는가 (`source ~/.nvm/nvm.sh`)
- [ ] 디스크 여유가 있는가 (`df -h /tmp`)

## 7. 문제 해결

### "request timed out" 에러가 반복되면

OpenClaw #46049 버그 — LLM HTTP 요청 타임아웃이 30초로 하드코딩. TTFT(Time-To-First-Token)가 느린 모델(OpenRouter free-tier 등)에서 발생. DashScope 모델은 TTFT가 빠라서 이 문제가 거의 없다.

### "needs a Tavily API key" 에러

```bash
source ~/.nvm/nvm.sh
openclaw config set tools.web.search.apiKey "YOUR_TAVILY_KEY"
```

설정 후 gateway 재시작:

```bash
sudo systemctl restart openclaw-gateway
```

### 에이전트 충돌/잔여 에이전트 정리

```bash
openclaw agents list
openclaw agents delete <agent-id> --force
```

### free quota 소진 확인

DashScope Model Studio 콘솔에서 모델별 사용량 확인:
https://dashscope.console.aliyun.com/

"Stop When Free Quota Is Used Up" 기능이 켜져 있으면 쿼터 소진 시 API가 즉시 차단된다. 꺼져 있으면 종량제로 자동 전환.

## 8. 오케스트레이터로 실행 (run-all.sh)

`run-all.sh`가 PinchBench + ClawBench-KO를 순차 실행하고 `normalize.py`까지 자동 호출한다.

```bash
cd ~/oracle-openclaw

# 단일 모델 3회 실행 (두 벤치마크 모두)
bash server/scripts/run-all.sh qwen3.5-27b --runs 3

# PinchBench만 1회
bash server/scripts/run-all.sh glm-5 --runs 1 --bench pb

# ClawBench-KO만 2회
bash server/scripts/run-all.sh qwen3-8b --runs 2 --bench ko

# 무료 모델 전체 1회씩
bash server/scripts/run-all.sh --all-models --runs 1 --free-only

# dry-run (실제 실행 없이 확인)
bash server/scripts/run-all.sh qwen3.5-27b --runs 3 --dry-run
```

run-all.sh는 models.json의 모델 ID를 받는다 (프로바이더 접두어 불필요).
실행 완료 후 `normalize.py`가 자동 호출되어 `results/normalized/leaderboard.json`이 갱신된다.

```bash
# Upstage Solar Pro 3 (reasoning_effort: high)
bash server/scripts/run-all.sh solar-pro3 --runs 3
```

### 결과 배포 (리더보드 사이트 반영)

```bash
bash server/scripts/deploy-results.sh
```

이 명령은 `leaderboard.json`을 git commit → push하면 GitHub Actions가 Astro 사이트를 빌드하여 GitHub Pages에 자동 배포한다.

### 백그라운드 실행

```bash
nohup bash server/scripts/run-all.sh qwen3.5-27b --runs 3 \
  > /tmp/benchmark-all.log 2>&1 &

tail -f /tmp/benchmark-all.log
```

## 9. 예상 소요 시간

| 벤치마크 | 태스크 | 1회 | 3회 |
|----------|--------|-----|-----|
| ClawBench-KO | 10 | ~15분 | ~45분 |
| PinchBench (full) | 24 | ~40분 | ~120분 |
| **합계** | 34 | ~55분 | ~165분 |

DashScope 모델 기준. OpenRouter free-tier는 2~3배 더 걸릴 수 있다.
`run-pinchbench.sh`는 항상 full 24 tasks를 실행한다 (judge 포함).

## 10. 전체 파이프라인 빠른 참조

서버 접속부터 리더보드 배포까지 전체 흐름.

### A. 기존 모델 벤치마크 실행 → 배포 (3단계)

```bash
# 1) 서버 접속
ssh -i ~/Coding/oracle-openclaw/key/ssh-key-2026-04-03.key ubuntu@168.107.51.82

# 2) 벤치마크 실행 (예: GLM-5.1을 3회)
cd ~/oracle-openclaw
source ~/.nvm/nvm.sh
bash server/scripts/run-all.sh glm-5.1 --runs 3

# 3) 결과 배포 → 사이트 자동 갱신
bash server/scripts/deploy-results.sh
```

리더보드 확인: https://gspain89.github.io/oracle-openclaw/

### B. 새 모델 추가 → 벤치마크 → 배포 (5단계)

```bash
# 1) 서버 접속
ssh -i ~/Coding/oracle-openclaw/key/ssh-key-2026-04-03.key ubuntu@168.107.51.82

# 2) OpenClaw에 모델 등록 (§3 참조)
source ~/.nvm/nvm.sh
# ... python3 스크립트로 openclaw.json에 모델 추가 ...

# 3) models.json에 모델 메타데이터 추가
cd ~/oracle-openclaw
nano server/config/models.json
# → models 배열에 새 항목 추가 (id, name, provider, free, 가격 등)

# 4) 벤치마크 실행
bash server/scripts/run-all.sh 새모델-id --runs 3

# 5) 결과 배포
bash server/scripts/deploy-results.sh
```

### C. 서버 코드 업데이트 (로컬에서 수정한 경우)

```bash
# 서버에서:
cd ~/oracle-openclaw
git pull origin main
```

### D. 파이프라인 흐름도

```
서버에서 bash run-all.sh <model> --runs N
  │
  ├── run-pinchbench.sh × N회 (순차)
  │     └── results/raw/pinchbench/{model}_{timestamp}.json
  │
  ├── run-claw-bench-ko.sh × N회 (순차)
  │     └── results/raw/korean/{model}_{timestamp}/results.json
  │
  └── normalize.py (자동 호출)
        └── results/normalized/leaderboard.json 갱신

서버에서 bash deploy-results.sh
  │
  ├── git add results/normalized/
  ├── git commit + git push origin main
  │
  └── GitHub Actions 자동 트리거
        ├── npm ci && npm run build (Astro)
        └── GitHub Pages 배포
              └── https://gspain89.github.io/oracle-openclaw/
```

## 11. 에이전트 ID와 세션 관리

### 에이전트 ID 생성 규칙

ClawBench-KO의 `runner.py`는 벤치마크 실행 시 OpenClaw 에이전트를 동적으로 생성/삭제한다. 에이전트 ID는 **결정적(deterministic)**이다:

```
cb-{model_hash}-{task_id}-{run_index}
```

- `model_hash`: 모델 슬러그(예: `upstage-solar-pro3`)의 MD5 해시 앞 6자리
- `task_id`: 태스크 ID (예: `addr_parse`)
- `run_index`: 반복 실행 인덱스 (0부터 시작)

예시: `upstage/solar-pro3`로 `addr_parse`를 실행하면 → `cb-e2c8c7-addr_parse-0`

같은 모델 + 같은 태스크 + 같은 run index는 항상 같은 에이전트 ID를 생성한다. 이 에이전트는 OpenClaw 게이트웨이에 등록되는 것과 동일한 에이전트다 (`openclaw agents list`에서 확인 가능).

### 세션 정리 (OpenClaw 버그 workaround)

OpenClaw의 `agents delete --force`가 세션 파일을 완전히 삭제하지 못하는 버그가 있다 (`Failed to move to Trash` 메시지). 에이전트 ID가 재사용되면 이전 대화 히스토리가 누적되어 모델이 혼란에 빠진다.

runner.py의 `delete_agent()`가 `shutil.rmtree()`로 `~/.openclaw/agents/cb-*/` 디렉토리를 직접 삭제하여 이 문제를 우회한다. 수동 정리가 필요하면:

```bash
# 벤치마크 에이전트 세션 전체 정리
rm -rf ~/.openclaw/agents/cb-*/sessions/*
rm -rf ~/.openclaw/agents/cb-*/agent/*
```

### Upstage 프로바이더 필수 설정

Upstage API는 OpenAI의 `store` 파라미터를 지원하지 않는다. OpenClaw이 이 파라미터를 기본으로 전송하면 `400 Unrecognized request arguments supplied: store` 에러가 발생한다. 모델 정의에 반드시 `compat.supportsStore: false`를 설정해야 한다:

```json
{
  "id": "solar-pro3",
  "reasoning": false,
  "compat": { "supportsStore": false }
}
```

## 12. 결과 관리

### 개별 실행(run) 결과 파일

각 벤치마크 실행은 타임스탬프가 포함된 디렉토리/파일로 저장된다:

```
results/raw/korean/solar-pro3_20260407-020857/results.json    ← 디렉토리 형태
results/raw/korean/solar-pro3_20260407-020857.json            ← 플랫 파일 복사본
```

### normalize.py의 집계 방식

`normalize.py`는 `results/raw/` 하위의 **모든** results.json을 수집하여 모델별로 그룹핑한 뒤 집계한다:

- `best`: 전체 실행 중 최고 점수
- `average`: 전체 실행의 평균
- `std`: 표준편차

예를 들어 solar-pro3 결과 파일이 4개면 4개 전부 평균/best/std로 집계된다. 16개여도 동일하다. **results/raw/ 에 있는 모든 파일이 리더보드에 포함된다.**

### 특정 실행 결과 삭제

잘못된 결과를 리더보드에서 제외하려면:

```bash
# 1) 해당 결과 파일 삭제
rm -rf results/raw/korean/solar-pro3_20260407-020857*

# 2) normalize.py 재실행 → leaderboard.json 갱신
python3 server/python/normalize.py

# 3) 배포 (사이트 반영)
bash server/scripts/deploy-results.sh
```

### 리더보드 미포함 조건

다음 경우 결과가 리더보드에 포함되지 않는다:

- results.json이 없는 빈 디렉토리 (FAIL FAST 종료, 중간 중단 등)
- `server/config/models.json`에 해당 모델 ID가 없는 경우 (WARN 로그 출력 후 제외)
- normalize.py가 아직 실행되지 않은 경우 (leaderboard.json 미갱신)

### E. 주요 경로 정리

| 항목 | 경로 |
|------|------|
| 벤치마크 스크립트 | `~/oracle-openclaw/server/scripts/` |
| 모델 레지스트리 | `~/oracle-openclaw/server/config/models.json` |
| PinchBench raw 결과 | `~/oracle-openclaw/results/raw/pinchbench/` |
| ClawBench-KO raw 결과 | `~/oracle-openclaw/results/raw/korean/` |
| 정규화된 리더보드 | `~/oracle-openclaw/results/normalized/leaderboard.json` |
| normalize.py | `~/oracle-openclaw/server/python/normalize.py` |
| ClawBench-KO runner | `~/oracle-openclaw/server/claw-bench-ko/runner.py` |
| PinchBench 소스 | `~/pinchbench-skill/` |
| OpenClaw 설정 | `~/.openclaw/openclaw.json` |
| SSH deploy key | `~/.ssh/oracle-deploy-key` (GitHub push용) |
| 사이트 소스 | `~/oracle-openclaw/site/` |
| GitHub Actions | `.github/workflows/deploy-pages.yml` |
| 라이브 사이트 | https://gspain89.github.io/oracle-openclaw/ |
