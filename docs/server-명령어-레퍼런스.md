# 서버 명령어 레퍼런스

Oracle ARM 서버(168.107.51.82)에서 사용하는 모든 명령어 정리.
중요도: **필수** = 거의 매번 사용, **일반** = 가끔 사용, **1회** = 초기 설정 시만

---

## 서버 접속

```bash
# [필수] SSH 접속
ssh -i ~/Coding/oracle-openclaw/key/ssh-key-2026-04-03.key ubuntu@168.107.51.82

# [필수] 접속 후 NVM 활성화 (openclaw CLI를 직접 실행할 때만 필요)
# 벤치마크 스크립트(run-all.sh 등)는 내부에서 자동 로드하므로 생략 가능
source ~/.nvm/nvm.sh
```

---

## 벤치마크 실행

```bash
# [필수] 단일 모델 전체 벤치마크 (PinchBench + ClawBench-KO + normalize)
bash server/scripts/run-all.sh <model_id>

# [필수] 결과 배포 (git push → GitHub Pages 자동 빌드)
bash server/scripts/deploy-results.sh

# [일반] PinchBench만 실행
bash server/scripts/run-pinchbench.sh <model_id>

# [일반] ClawBench-KO만 실행
bash server/scripts/run-claw-bench-ko.sh <model_id>

# [일반] ClawBench-KO 특정 태스크만 (테스트용, 리더보드 미반영)
bash server/scripts/run-claw-bench-ko.sh <model_id> --runs 1 --task addr_parse

# [일반] 전체 모델 배치 실행
bash server/scripts/run-all.sh --all-models --runs 1
bash server/scripts/run-all.sh --all-models --runs 1 --free-only  # 무료 모델만

# [일반] 벤치마크 선택 실행
bash server/scripts/run-all.sh <model_id> --bench pb   # PinchBench만
bash server/scripts/run-all.sh <model_id> --bench ko   # ClawBench-KO만

# [필수] 백그라운드 실행 (SSH 끊겨도 계속 실행)
nohup bash server/scripts/run-all.sh <model_id> > /tmp/<model_id>-run.log 2>&1 &

# [필수] 백그라운드 실행 로그 실시간 확인 (Ctrl+C로 빠져나와도 벤치마크 무관)
tail -f /tmp/<model_id>-run.log

# [필수] 백그라운드 프로세스 생존 확인
ps aux | grep run-all

# [일반] Dry run (실제 실행 없이 명령어 확인)
bash server/scripts/run-all.sh <model_id> --dry-run

# [일반] normalize만 단독 실행
python3 server/python/normalize.py --repo-root ~/oracle-openclaw
```

### 모델 ID 지정 방법

```bash
# short ID (권장) — resolve-model.sh가 자동 매칭
bash server/scripts/run-all.sh glm-5
bash server/scripts/run-all.sh solar-pro3
bash server/scripts/run-all.sh deepseek-reasoner

# full ID — 슬래시 포함 모델
bash server/scripts/run-all.sh nvidia/nemotron-3-super-120b-a12b:free
```

---

## OpenClaw 관리

```bash
# [필수] 모델 목록 확인
openclaw models list
openclaw models list --all              # 전체 카탈로그

# [필수] 게이트웨이 상태 확인
openclaw gateway status

# [일반] 게이트웨이 재시작 (config 변경 후)
openclaw gateway restart

# [일반] 헬스 체크
openclaw health

# [일반] 기본 모델 변경
openclaw models set <provider/model-id>

# [일반] 현재 기본 모델 확인
openclaw config get agents.defaults.model

# [일반] 에이전트 목록
openclaw agents list

# [일반] 에이전트 생성 (테스트용)
openclaw agents add test-agent \
  --model <provider/model-id> \
  --workspace /tmp/test-ws \
  --non-interactive

# [일반] 에이전트에 메시지 전송 (테스트용)
openclaw agent --agent test-agent --session-id test1 --timeout 30 --message "Say hello"

# [일반] 에이전트 삭제
openclaw agents delete test-agent --force

# [일반] 설정값 읽기
openclaw config get <key>
# 예: openclaw config get models.providers.azure-openai

# [일반] 모델 상세 상태
openclaw models status --json
```

---

## 새 모델 추가

```bash
# [일반] 1단계: OpenClaw에 등록 (onboard 또는 수동)
# onboard 사용 시:
openclaw onboard

# 수동 등록 시 (DashScope 예시):
python3 << 'PYEOF'
import json
MODEL_ID = "새모델-id"
CONTEXT_WINDOW = 131072
with open("/home/ubuntu/.openclaw/openclaw.json") as f:
    d = json.load(f)
d["agents"]["defaults"]["models"][f"modelstudio/{MODEL_ID}"] = {}
d["models"]["providers"]["modelstudio"]["models"].append({
    "id": MODEL_ID, "name": MODEL_ID, "input": ["text"],
    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    "contextWindow": CONTEXT_WINDOW, "maxTokens": 65536,
    "api": "openai-completions",
})
with open("/home/ubuntu/.openclaw/openclaw.json", "w") as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
print(f"OK - modelstudio/{MODEL_ID}")
PYEOF

# 등록 확인
openclaw models list | grep 새모델

# [일반] 2단계: 벤치마크 실행 (models.json 등록 불필요)
bash server/scripts/run-all.sh 새모델-id

# [일반] 3단계: 배포
bash server/scripts/deploy-results.sh

# [선택] models.json에 등록 (표시명/제공자 라벨 커스텀)
# server/config/models.json에 항목 추가 후 git commit + push
```

---

## 서버/코드 관리

```bash
# [필수] 로컬에서 수정한 코드 서버에 반영
cd ~/oracle-openclaw && git pull origin main

# [일반] 디스크 여유 확인
df -h /home

# [일반] OpenClaw 버전 업데이트
npm update -g openclaw
openclaw gateway restart

# [일반] OpenClaw 프로세스 확인
ps aux | grep openclaw-gateway

# [일반] 게이트웨이 포그라운드 실행 (디버깅)
openclaw gateway run

# [일반] 에이전트 세션 초기화 (문제 발생 시)
rm -rf ~/.openclaw/agents/main/sessions/*
```

---

## 초기 설정 (1회)

```bash
# [1회] 서버 초기화 (PinchBench clone, 디렉토리 생성)
bash server/scripts/setup-server.sh

# [1회] uv 설치 (PinchBench 실행에 필요)
curl -LsSf https://astral.sh/uv/install.sh | sh

# [1회] 비-DashScope 프로바이더 등록 (Upstage 예시)
python3 << 'PYEOF'
import json
PROVIDER_NAME = "upstage"
BASE_URL = "https://api.upstage.ai/v1"
MODEL_ID = "solar-pro3"
CONTEXT_WINDOW = 131072
with open("/home/ubuntu/.openclaw/openclaw.json") as f:
    d = json.load(f)
d["models"]["providers"][PROVIDER_NAME] = {
    "baseUrl": BASE_URL, "api": "openai-completions",
    "models": [{"id": MODEL_ID, "name": MODEL_ID, "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": CONTEXT_WINDOW, "maxTokens": 65536}]
}
d["agents"]["defaults"]["models"][f"{PROVIDER_NAME}/{MODEL_ID}"] = {}
with open("/home/ubuntu/.openclaw/openclaw.json", "w") as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
print(f"OK - {PROVIDER_NAME}/{MODEL_ID}")
PYEOF

# [1회] API 키 등록
python3 << 'PYEOF'
import json
with open("/home/ubuntu/.openclaw/agents/main/agent/auth-profiles.json") as f:
    auth = json.load(f)
auth["profiles"]["upstage:default"] = {
    "type": "api_key", "provider": "upstage", "key": "up_..."
}
with open("/home/ubuntu/.openclaw/agents/main/agent/auth-profiles.json", "w") as f:
    json.dump(auth, f, indent=2, ensure_ascii=False)
print("OK")
PYEOF
```

---

## 빠른 참조 — 가장 자주 쓰는 명령어

| # | 명령어 | 용도 |
|---|--------|------|
| 1 | `nohup bash server/scripts/run-all.sh <model_id> > /tmp/<id>-run.log 2>&1 &` | 벤치마크 백그라운드 실행 |
| 2 | `tail -f /tmp/<id>-run.log` | 실시간 로그 확인 |
| 3 | `bash server/scripts/deploy-results.sh` | 결과 배포 |
| 4 | `openclaw models list` | 등록 모델 확인 |
| 5 | `git pull origin main` | 코드 동기화 |
