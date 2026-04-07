# OpenClaw 벤치마크 자동화 + 리더보드 시스템

> 작성일: 2026-04-03
> 최종 수정: 2026-04-07
> 상태: Phase 0~3 완료. PinchBench full 24 tasks 전환, 사이트 메뉴 개편 (PinchBench/ClawBench-KO 상세 페이지)

## 1. 배경 및 목표

Oracle Cloud ARM 서버(VM.Standard.A1.Flex, 4 OCPU / 24GB RAM, 춘천 리전)에서 OpenClaw v2026.4.5가 구동 중이다. 다양한 LLM(Large Language Model) 모델의 에이전트 성능을 체계적으로 비교하고, 결과를 공개 리더보드로 운영한다.

**핵심 가치**: GLM-5의 PinchBench 점수는 아직 세상에 없는 데이터이므로, 최초 측정이라는 독자적 의미가 있다. 한국어 커스텀 벤치마크 역시 어떤 벤치마크에도 존재하지 않는 유일한 평가 체계가 된다.

## 2. 아키텍처

```
[Oracle ARM 서버 (4 OCPU / 24GB)]
  bash 스크립트: 모델 순회 → 벤치마크 실행
  python 스크립트: 결과 파싱 → 통합 JSON 생성
  git push → GitHub Actions 트리거

[GitHub Pages (무료 호스팅)]
  Astro 정적 사이트: 리더보드/차트/비교 뷰
  자동 빌드 + 배포
```

데이터 흐름:
1. 서버에서 벤치마크 실행 → `results/raw/`에 원본 JSON 저장
2. `normalize.py`가 원본 → `results/normalized/leaderboard.json` 통합
3. `deploy-results.sh`가 normalized 결과를 git push
4. GitHub Actions(GitHub Actions)가 Astro 빌드 → Pages 배포

## 3. 기술 스택

| 구성 요소 | 선택 | 이유 |
|----------|------|------|
| 프론트엔드 | **Astro** (정적 사이트) | Next.js 대비 서버 불필요, GitHub Pages 무료 배포, 빌드 시 JSON 로딩 |
| 데이터 저장 | **JSON 파일** | 벤치마크가 이미 JSON 출력. SQLite는 불필요한 복잡도 |
| 차트 | **Chart.js** v4 (CDN) | 범용적이고 가벼운 차트 라이브러리. 레이더/산점도/바 차트 지원 |
| 자동화 스크립트 | **Bash + Python** (표준 라이브러리만) | 벤치마크 CLI(Command Line Interface) 호출은 bash, 데이터 가공은 python. pip 의존성 0 |
| CI/CD | **GitHub Actions → Pages** | `results/normalized/` 변경 시 자동 빌드+배포 |
| 프론트엔드 디자인 | **Warm parchment 컨셉** | 크림/베이지 라이트 테마, DM Serif Display 제목, 붉은(#8c2416) 악센트 |

## 4. 프로젝트 구조

```
oracle-openclaw/
├── .github/workflows/deploy-pages.yml   # Pages 자동 배포
├── docs/                                 # 연구 문서 + 이 계획서
│   ├── openclaw-architecture-분석.md
│   ├── pinchbench-내부 동작 분석.md
│   ├── claw-bench-ko-테스크 전체구조.md
│   ├── benchmark-guide-서버 접속~벤치마크 실행 가이드.md
│   └── benchmark-리더보드+자동화 전체 설계 계획.md  # ← 이 문서
├── server/                               # 서버에서 실행되는 코드
│   ├── config/
│   │   ├── models.json                   # 모델 레지스트리 (8개 모델, ID/가격/설정)
│   │   └── benchmarks.json               # 벤치마크 정의 (2종: PinchBench, ClawBench-KO)
│   ├── scripts/
│   │   ├── setup-server.sh               # 1회 서버 초기화 (PinchBench clone 등)
│   │   ├── run-pinchbench.sh             # 단일 모델 PinchBench 실행
│   │   ├── run-claw-bench-ko.sh          # 단일 모델 ClawBench-KO 실행
│   │   ├── run-all.sh                    # 전체 오케스트레이터 (모델 순회)
│   │   └── deploy-results.sh             # git push → Pages 트리거
│   ├── python/
│   │   └── normalize.py                  # raw 결과 → leaderboard.json 통합
│   └── claw-bench-ko/                    # 한국어 벤치마크
│       ├── tasks/                         # 태스크 정의 (10개)
│       ├── manifest.json
│       ├── runner.py                      # 실행 + 채점 통합
│       └── grader.py                      # 채점 로직
├── results/
│   ├── raw/                               # 벤치마크 원본 출력 (gitignored)
│   │   ├── pinchbench/
│   │   └── korean/
│   └── normalized/
│       └── leaderboard.json               # 리더보드 데이터 (normalize.py 출력)
├── site/                                  # Astro 정적 사이트
│   ├── package.json
│   ├── astro.config.mjs
│   └── src/
│       ├── layouts/Layout.astro           # 공통 레이아웃 + 디자인 시스템
│       └── pages/
│           ├── index.astro                # 메인 리더보드 (종합 테이블+바차트)
│           ├── compare.astro              # A/B 모델 비교 (레이더 차트)
│           ├── cost.astro                 # 비용 효율 (산점도)
│           ├── pinchbench.astro           # PinchBench 상세 (모델 순위+실행 상세+개요)
│           └── korean.astro               # ClawBench-KO 상세 (카테고리별 비교+채점 방식)
├── key/                                   # SSH 키 (gitignored)
└── .gitignore
```

## 5. 테스트 대상 모델

### 현재 활성 모델

| 모델 | 제공자 | 무료 | PinchBench | 비고 |
|------|--------|------|-----------|------|
| **Nemotron 3 Super 120B** | OpenRouter `:free` | O | **97.7%** | 무료 모델 중 최고 성적 |
| Qwen 3.5 27B | DashScope | △ | 미측정 | 무료 크레딧 1M tokens |
| Qwen 3.5 Plus | DashScope | X | 미측정 | Plus 변형, 응답 속도 빠름 |
| GLM-5 | Z.AI / DashScope | X | 미측정 | **세계 최초 PinchBench 측정 목표** |
| GLM-5.1 | Z.AI / DashScope | X | 미측정 | GLM-5 후속 |
| **Solar Pro 3** | Upstage | X | 미측정 | 102B MoE (12B active) |

### 제외된 모델 (2026-04-04 확정)

| 모델 | PinchBench | 제외 사유 |
|------|-----------|----------|
| Arcee Trinity Large Preview | 55.4% | file_ops/comprehension 0%, 재시도해도 개선 없음 |
| Qwen3 Coder | 0.0% | OpenClaw tool_calls 형식 호환 불가. sanity check조차 실패 |

## 6. 구현 Phase

### Phase 0: 프로젝트 스캐폴드 — 완료 (2026-04-03)

- [x] 디렉토리 구조 생성 (server/, results/, site/)
- [x] .gitignore 확장 (node_modules, dist, results/raw)
- [x] `models.json` 모델 레지스트리 (9개 모델)
- [x] `benchmarks.json` 벤치마크 정의 (PinchBench, Korean, WildClaw)
- [x] Astro 프로젝트 초기화 + 5개 페이지 구현
- [x] GitHub Actions 워크플로우
- [x] 빌드 테스트 통과

**산출물**: `npm run build` 성공, 5페이지 정적 사이트 생성 (1.33초)

### Phase 1: PinchBench 자동화 스크립트 — 완료 (2026-04-03)

- [x] `setup-server.sh`: PinchBench repo clone, 결과 디렉토리 생성, OpenClaw 설정 확인
- [x] `run-pinchbench.sh`: 모델 전환(`openclaw config set`) → PinchBench 실행 → JSON 저장. 24시간 중복 실행 방지, 3가지 CLI 실행 방식(run.sh / npx / openclaw eval) 자동 탐색
- [x] `run-all.sh`: `models.json`에서 모델 목록 읽어 무료→유료 순서로 순회. `--dry-run`, `--free-only` 옵션 지원
- [x] `normalize.py`: PinchBench 원본 JSON → `leaderboard.json` 통합. 3가지 출력 형식 자동 파싱, 0-1 vs 0-100 스케일 자동 감지. 표준 라이브러리만 사용 (pip 의존성 0)
- [x] `deploy-results.sh`: `results/normalized/` 변경 감지 → git commit + push → Pages 자동 빌드 트리거. `--dry-run` 지원
- [x] 로컬 테스트 완료: `normalize.py` 실행 → 7개 모델 leaderboard.json 정상 생성 (2,124 bytes)

**산출물**: 서버 배포 준비 완료된 5개 자동화 스크립트

#### Phase 1 서버 실행 기록

**1차 실행 (2026-04-03)**: OpenRouter rate limit(50 req/day)으로 인해 3개 모델 모두 불완전한 결과. $10 크레딧 충전(→ 1000 req/day) 및 하트비트 비활성화 후 재실행.

**최종 실행 (2026-04-04)**: automated-only 9개 태스크, 0% 재시도 로직 적용. 환경 개선: Tavily 웹 검색(DuckDuckGo 교체), pdftotext 설치(poppler-utils).

| 태스크 | Arcee Trinity | Qwen3 Coder | Nemotron 120B |
|--------|:---:|:---:|:---:|
| task_00 sanity | 100% | 0% | 100% |
| task_01 calendar | 100% | 0% | 100% |
| task_02 stock | 100% | 0% | 100% |
| task_04 weather | 14% | 0% | 100% |
| task_08 memory | 70% | 0% | 90% |
| task_09 files | 86% | 0% | 100% |
| task_11 clawdhub | 29% | 0% | 100% |
| task_12 skill_search | 0% | 0% | 100% |
| task_21 comprehension | 0% | 0% | 89% |
| **종합** | **55.4%** | **0.0%** | **97.7%** |
| 소요 시간 | 25분 21초 | 18분 57초 | 14분 38초 |

Qwen3 Coder는 1차 + 재시도(전체 18 tasks) 모두 0%. OpenClaw tool_calls 형식과 근본적으로 비호환.
Arcee Trinity는 task_12/task_21이 재시도 후에도 0%. 고급 태스크에서 한계.
Nemotron은 0% 태스크 없이 재시도 불필요. 최저 89%(comprehension).

#### 서버 배포 시 해결한 이슈

1. **OpenClaw Gateway 인증**: `devices/paired.json`의 scopes가 `operator.read`만 포함 → `operator.admin,operator.approvals,operator.pairing,operator.read,operator.write` 전체 추가. `gateway.auth.mode`를 `token` → `none`(loopback 전용이라 안전).

2. **모델 ID 프리픽스**: OpenClaw 모델 ID에 프로바이더 접두어 필수. `arcee-ai/xxx` → `openrouter/arcee-ai/xxx`, `qwen3.5-plus` → `modelstudio/qwen3.5-plus`. `run-pinchbench.sh`에 `models.json`의 provider 필드 기반 자동 접두어 해결 로직 추가.

3. **Nemotron 모델 ID 불일치**: `models.json`에 `nvidia/nemotron-3-super:free`로 등록 → 실제 OpenClaw ID `nvidia/nemotron-3-super-120b-a12b:free`로 수정.

#### OpenRouter Rate Limit 정책

OpenRouter 무료 모델(`:free` 접미사) rate limit:

| 조건 | 일일 한도 | 분당 한도 |
|------|----------|----------|
| 크레딧 < $10 | 50 requests/day | 20 requests/min |
| 크레딧 >= $10 | 1,000 requests/day | 20 requests/min |

- 한도는 **계정 단위** (모델별이 아님). 실패 요청도 카운트.
- 일일 카운터 리셋: **00:00 UTC** (KST 09:00).
- 출처: https://openrouter.ai/docs/api/reference/limits

#### OpenClaw 하트비트와 API 소비

OpenClaw gateway 데몬은 **30분 주기로 LLM을 호출**하는 하트비트 기능이 기본 활성화되어 있다. 벤치마크 전용 서버에서는 이것이 무료 API quota를 불필요하게 소비한다.

**하트비트 동작 원리**: Gateway가 에이전트의 워크스페이스 파일(AGENTS.md, SOUL.md, IDENTITY.md, USER.md, HEARTBEAT.md 등)을 기본 모델에 전송하고, LLM이 처리할 이벤트나 태스크가 있는지 확인한다. 본래 목적은 메시징 자동화(WhatsApp/Telegram) 환경에서 리마인더 확인, 받은 메시지 트리아지, 시스템 이벤트 처리 등이다. HEARTBEAT.md에 주기적 체크 태스크를 기록하면 그것을 수행한다.

**API 소비량**: 매 30분마다 2 requests (input ~9,200 tokens + output ~36 tokens). 일일 최대 96 requests.

**조치 (2026-04-03)**: `openclaw system heartbeat disable`로 비활성화. 설정은 영구 저장됨. 대안으로 `agents.defaults.heartbeat.every`를 `"0m"`으로 설정해도 동일.

### Phase 2: 한국어 커스텀 벤치마크 — 완료

- 10개 태스크 구현 (초기 15개 계획에서 축소. §7은 원래 계획, 실제 구현은 `claw-bench-ko-테스크 전체구조.md` 참조)
- 3가지 채점 방식: automated(JSON 필드 비교), llm_judge(GPT-5.3 판정), hybrid(자동+LLM)
- 판정 LLM: azure-openai/gpt-5.3-chat

**산출물**: 세계 유일의 한국어 OpenClaw 벤치마크

### Phase 3: 리더보드 사이트 + 자동화 파이프라인 — 완료

구현 완료 항목:
- [x] `run-all.sh` 오케스트레이터 (단일/전체 모델, PB/KO/all, dry-run, free-only)
- [x] `normalize.py` 증분 병합 (기존 데이터 보존, 새 raw만 갱신)
- [x] `deploy-results.sh` → git push → GitHub Actions → Pages 자동 배포
- [x] Astro 정적 사이트 5페이지 (리더보드, 모델 비교, 비용 효율, PinchBench, ClawBench-KO)
- [x] Upstage Solar Pro 3 프로바이더 추가 (2026-04-06)
- [x] 러너 스크립트 → 3개 프로바이더 지원 (dashscope→modelstudio, openrouter, upstage)
- [x] PinchBench full 24 tasks 전환 — `run-pinchbench.sh`에서 `--suite automated-only` 제거 (2026-04-07)
- [x] 사이트 메뉴 개편: 그래프→PinchBench 상세, 한국어→ClawBench-KO 라벨 변경 (2026-04-07)
- [x] 모든 페이지 빈 데이터 empty state 처리 (2026-04-07)

- `normalize.py`: raw 결과 → leaderboard.json 다중 실행 집계 (best/average/std)
- `run-all.sh`: 모델+횟수 지정 → PinchBench + ClawBench-KO 순차 실행 → normalize 자동 호출
- `deploy-results.sh`: leaderboard.json git push → GitHub Actions → Pages 자동 배포
- E2E 검증 완료 (fake raw → normalize → build → 5페이지 렌더링 확인)

**남은 작업**: 실제 모델로 벤치마크 실행 (`bash run-all.sh <model> --runs 3`)

### Phase 4: 정기 실행 + 히스토리 (미정)

- cron: 주 1회 PinchBench 재실행
- `leaderboard.json`의 runs 배열로 시계열 추적 (별도 history.json 불필요)
- 리더보드 페이지 또는 PinchBench/ClawBench-KO 상세 페이지에서 시계열 표시

### ~~Phase (삭제): AgentBench~~

초기 계획에서 "OpenClaw 내장 `/benchmark`"로 가정했으나, OpenClaw v2026.4.2에 해당 기능이 존재하지 않음. OpenClaw의 벤치마크 관련 기능은 Model latency bench(추론 속도 ms 측정)와 CLI startup bench(CLI 시작 시간 프로파일링)뿐이며, 에이전트 능력 평가 프레임워크가 아님. 2026-04-04 확인 후 삭제.

## 7. 한국어 벤치마크 태스크 설계 (초기 계획)

> 초기 15개 태스크를 계획했으나 실제로는 10개를 구현했다.
> 구현된 10개 태스크의 상세 구조는 `claw-bench-ko-테스크 전체구조.md` 참조.

3개 카테고리, 15개 태스크 (초기 계획):

**한국어 처리 (5개)**

| # | 태스크 | 채점 방식 |
|---|--------|-----------|
| 1 | HWP 문서 데이터 추출 | structured |
| 2 | 뉴스 기사 요약 | semantic |
| 3 | 법률 문서 영→한 번역 | semantic |
| 4 | 맞춤법 교정 | exact |
| 5 | 비즈니스 이메일 작성 | semantic |

**한국 시스템 (5개)**

| # | 태스크 | 채점 방식 |
|---|--------|-----------|
| 6 | 한국 주소 파싱 (도/시/구/동) | structured |
| 7 | 날짜 형식 변환 (음력↔양력, 한국식) | exact |
| 8 | 만원/억원 금액 변환 | exact |
| 9 | 주민번호 형식 검증 | exact |
| 10 | 전화번호 정규화 (010-XXXX-XXXX) | exact |

**한국 문서/도구 (5개)**

| # | 태스크 | 채점 방식 |
|---|--------|-----------|
| 11 | HWP → Markdown 변환 | structured |
| 12 | 은행 거래 CSV 처리 | structured |
| 13 | 제안서 작성 | semantic |
| 14 | 공공데이터 API 파싱 | structured |
| 15 | 한자 읽기 (음독/훈독) | exact |

## 8. 예산 전략

총 가용 예산: **$9 (Z.AI 크레딧) + DashScope 무료 크레딧**

실행 순서 (무료 먼저):
1. OpenRouter `:free` 모델들 (Arcee Trinity, Qwen3-Coder, Nemotron) → **$0**
2. Qwen 3.5 27B (DashScope 무료 크레딧 1M tokens) → **$0**
3. GLM-5 1회 → **~$1.50**
4. GLM-5.1 1회 → **~$1.50**
5. 나머지 ~$6 → 한국어 벤치마크 + 재실행 예비

## 9. WildClawBench 참조 (현재 미실행)

InternLM(상하이 AI Lab)이 2026-03-23에 공개한 오픈소스 에이전트 벤치마크. 호스팅 평가 환경을 제공하지 않으며, 전부 로컬에서 Docker 기반으로 직접 실행해야 한다.

- **리포**: github.com/InternLM/WildClawBench (MIT 라이센스, 241 stars)
- **리더보드**: internlm.github.io/WildClawBench/
- **데이터셋**: huggingface.co/datasets/internlm/WildClawBench
- **논문/인용**: Shuangrui Ding, Xuanlang Dai, Long Xing 외

### 벤치마크 구성

60개 태스크, 6개 카테고리. 각 태스크가 개별 Docker 컨테이너 안에서 실제 OpenClaw 인스턴스를 구동하여 에이전트를 평가한다. 채점 스크립트는 에이전트 실행 종료 후에만 주입되며, 실행 중에는 보이지 않는다.

| 카테고리 | 태스크 수 |
|----------|----------|
| Productivity Flow | 10 |
| Code Intelligence | 12 |
| Social Interaction | 6 |
| Search & Retrieval | 11 |
| Creative Synthesis | 11 |
| Safety Alignment | 10 |

점수: 각 지표 0.00~1.00, 전체 점수는 가중 평균.

### 실행에 필요한 환경

#### 하드웨어

| 항목 | 요구사항 |
|------|---------|
| CPU | x86_64 멀티코어 (ARM 미지원 — Docker 이미지 `wildclawbench-ubuntu:v1.2`가 x86_64 전용으로 추정. 문서에 ARM/aarch64 언급 없음) |
| RAM | 최소 8GB, 권장 16GB+ |
| 디스크 | **100GB+** — Docker 이미지 ~13GB 압축 (전개 시 더 큼) + YouTube 영상 3개 (축구 경기, 강의, 제품 발표) + SAM3 모델 가중치 + workspace 데이터 |
| 네트워크 | 안정적 인터넷 (API 호출 + 대용량 다운로드) |

#### 소프트웨어

| 도구 | 버전/비고 |
|------|----------|
| Docker | 최신 안정 버전. macOS: `brew install --cask docker`, Ubuntu: apt |
| Python | 3.8+ |
| huggingface_hub | `pip install -U huggingface_hub` (이미지·데이터 다운로드용) |
| yt-dlp | YouTube 영상 다운로드 (`prepare.sh`에서 사용) |
| ffmpeg | 영상 처리/추출 |
| gdown | Google Drive 파일 다운로드 (SAM3 가중치) |

#### API 키

| 키 | 용도 | 필수 여부 |
|----|------|----------|
| `OPENROUTER_API_KEY` | 모델 접근 (OpenRouter 경유) | **필수** |
| `BRAVE_API_KEY` | Search & Retrieval 카테고리 11개 태스크 | **해당 카테고리 실행 시 필수** |
| 커스텀 엔드포인트 | `my_api.json`으로 로컬/프록시 모델 서빙 가능 | 선택 |

`.env` 파일 형식:
```
OPENROUTER_API_KEY=sk-...
BRAVE_API_KEY=...
DEFAULT_MODEL=openrouter/stepfun/step-3.5-flash:free
```

커스텀 엔드포인트(`my_api.json`) 형식:
```json
{
  "providers": {
    "my-proxy": {
      "baseUrl": "http://host.docker.internal:8000/v1",
      "apiKey": "${MY_PROXY_API_KEY}",
      "api": "openai-completions",
      "models": [{ "id": "my-model", "name": "My Model" }]
    }
  }
}
```

### 설치 및 실행 절차

```bash
# 1. 리포 클론
git clone https://github.com/InternLM/WildClawBench.git && cd WildClawBench

# 2. Docker 이미지 다운로드 및 로드 (~13GB)
pip install -U huggingface_hub
huggingface-cli download internlm/WildClawBench Images/wildclawbench-ubuntu_v1.2.tar \
  --repo-type dataset --local-dir .
docker load -i Images/wildclawbench-ubuntu_v1.2.tar

# 3. 태스크 데이터 다운로드
huggingface-cli download internlm/WildClawBench workspace --repo-type dataset --local-dir .

# 4. 데이터 준비 (YouTube 영상 3개 + git 아카이브 + SAM3 가중치)
bash script/prepare.sh

# 5. .env 설정 (API 키)
# 6. 전체 실행
bash script/run.sh
# 또는 카테고리별/태스크별:
python3 eval/run_batch.py --category 01_Productivity_Flow --parallel 4
python3 eval/run_batch.py --task tasks/01_Productivity_Flow/task_2_table_tex_download.md
```

### 출력 구조

```
output/<category>/<task_id>/<model_timestamp_runid>/
├── score.json        # 지표별 점수 (0.00~1.00)
├── usage.json        # 토큰 수, 비용, 소요 시간
├── agent.log         # 에이전트 실행 추적
├── gateway.log       # API 게이트웨이 로그
├── chat.jsonl        # 전체 대화 트랜스크립트
└── task_output/      # 에이전트가 생성한 파일
```

요약 파일: `output/summary_all.json` (전체), `output/<category>/summary.json` (카테고리별).

### 공식 리더보드 비용/시간 데이터

| 모델 | 1회 비용 | 소요 시간 | 점수 |
|------|----------|----------|------|
| Claude Opus 4.6 | $80.85 | 508분 | 51.6% |
| GPT-5.4 | $20.08 | 350분 | 50.3% |
| Gemini 3.1 Pro | $18.22 | 240분 | 40.8% |
| MiMo V2 Pro | $26.47 | 458분 | 40.2% |
| GLM-5 | $11.39 | 373분 | — |
| DeepSeek V3.2 | $11.50 | 549분 | — |
| Step 3.5 Flash (무료) | $6.63 | 430분 | — |

### 현 프로젝트에서 미실행 사유

1. **CPU 아키텍처**: Docker 이미지가 x86_64 전용으로 추정. 현재 Oracle ARM 서버에서 실행 불가.
2. **디스크**: 100GB+ 필요. 서버 여유 ~42GB. Block Volume 추가로 해결은 가능하나 아키텍처 문제가 선행.
3. **API 한도**: 60 tasks × 다수 API 호출. OpenRouter 무료 1000 req/day로 완주 불확실.
4. **비용**: 무료 모델도 Brave API 키 필요. GLM-5는 $11.39/회로 현 예산($9) 초과.
5. **시간**: 4~9시간/회. PinchBench 15분 대비 20~36배.

**향후 실행 조건**: x86_64 서버 + 100GB+ 디스크 + OpenRouter 유료 크레딧 충분 + Brave API 키 확보 시 재검토.

## 10. 검증 방법

1. **Phase 1 검증**: `run-pinchbench.sh`를 무료 모델 1개로 실행 → 결과 JSON 확인 → `normalize.py`로 `leaderboard.json` 생성 → 데이터 정합성 확인
2. **Phase 2 검증**: `npm run build` → `site/dist/index.html`을 브라우저에서 열어 테이블/차트 렌더링 확인
3. **E2E(End-to-End) 검증**: 서버에서 `deploy-results.sh` → GitHub Actions 트리거 → Pages URL에서 리더보드 확인

## 11. 프론트엔드 디자인 시스템

**컨셉**: "Warm Parchment" — 학술 저널/문서 스타일의 라이트 테마

| 요소 | 설정 |
|------|------|
| 배경 | #f0ead8 (크림/베이지) |
| 카드 배경 | #ffffff, border: rgba(120, 100, 70, 0.12) |
| 폰트 (제목) | DM Serif Display (세리프) |
| 폰트 (데이터) | IBM Plex Mono (모노스페이스) |
| 폰트 (본문) | Noto Sans KR |
| 1차 악센트 | #8c2416 (다크 레드) |
| 순위 뱃지 | 1위 골드(#b8860b), 2위 실버(#6a7a8a), 3위 브론즈(#8a5520) |
| 점수 바 | Best: #8c2416 (레드), Average: #d4744a (오렌지) |
| 차트 | Chart.js v4 (CDN) — 레이더/산점도/바 차트 |
| 네비게이션 | 스티키 상단, blur(16px) 백드롭, 활성 탭 레드 밑줄 |
| 애니메이션 | fade-up 진입(stagger), bar-grow 점수 바 |

**페이지 구성** (5페이지):
- **리더보드** (index): 통계 카드 4개 + 종합/PinchBench/ClawBench-KO 탭 바차트 + 정렬 가능 테이블
- **모델 비교** (compare): 2개 모델 드롭다운 → Chart.js 레이더 차트 (4축: PB, KO, 속도, 가성비) + 지표 바 + 상세 테이블
- **비용 효율** (cost): Chart.js 산점도 (X=비용, Y=점수) + 비용 효율 순위 리스트
- **PinchBench** (pinchbench): 모델 순위 바차트 + 실행 상세 테이블(best/avg/std/횟수/속도) + 벤치마크 개요
- **ClawBench-KO** (korean): 종합 바차트 + 카테고리별 비교 차트 + 카테고리 카드 3개 + 채점 방식 설명

모든 페이지는 데이터가 없을 때 empty state를 표시한다.
