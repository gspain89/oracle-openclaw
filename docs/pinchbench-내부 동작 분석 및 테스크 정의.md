# PinchBench 내부 동작 분석 + 태스크 정의

최종 수정: 2026-04-08
PinchBench 위치: `~/pinchbench-skill/` (서버)
의존성: Python 3.10+, PyYAML, OpenClaw CLI

---

## 1. PinchBench란

PinchBench는 LLM 에이전트의 실무 능력을 측정하는 벤치마크 도구다. 24개 태스크를 에이전트에게 수행시키고, 자동 채점 + LLM 판정으로 점수를 매긴다. 태스크 자체는 프레임워크에 의존하지 않으며, 실행 하네스만 OpenClaw CLI에 결합되어 있다 (§10 참조).

핵심 특징:
- 현재 실행 환경에서 모든 모델 호출은 `openclaw agent` CLI를 통해 수행 — 외부 API 직접 호출 없음
- 테스트 대상 모델과 채점(judge) 모델이 분리되어 있음
- 두 모델 모두 OpenClaw 에이전트로 실행됨


## 2. 실행 명령

```bash
cd ~/pinchbench-skill/scripts

# 전체 24개 태스크 (judge 필요) — 기본 실행 방식
python3 benchmark.py --model openrouter/nvidia/nemotron-3-super-120b-a12b:free --judge azure-openai/gpt-5.3-chat

# 3회 반복 실행 (best/average 산출용)
python3 benchmark.py --model openrouter/nvidia/nemotron-3-super-120b-a12b:free --judge azure-openai/gpt-5.3-chat --runs 3

# automated 태스크만 (judge 불필요, 9개) — 빠른 테스트용
python3 benchmark.py --model openrouter/nvidia/nemotron-3-super-120b-a12b:free --suite automated-only
```

> **참고**: `run-pinchbench.sh`는 2026-04-07부터 항상 full 24 tasks를 실행한다 (`--suite automated-only` 제거됨).
> `run-all.sh` 오케스트레이터를 통해 실행하면 자동으로 full 24 tasks가 적용된다.

### CLI 주요 옵션

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--model` | (필수) | 테스트 대상 모델 |
| `--judge` | `openrouter/anthropic/claude-opus-4.5` | 채점 모델 (llm_judge/hybrid 태스크용) |
| `--suite` | `all` | `all`, `automated-only`, 또는 `task_00_sanity,task_09_files` 등 |
| `--runs` | 1 | 태스크당 반복 횟수 |
| `--timeout-multiplier` | 1.0 | 타임아웃 배율 |
| `--verbose` | off | 상세 로그 (transcript, workspace 내용 출력) |


## 3. 에이전트 생성 시점

PinchBench는 벤치마크 실행 시 에이전트를 **동적으로 생성**한다. 실행 전에 미리 만들어둘 필요 없다.

### 3.1 테스트 에이전트 생성 시점

```
benchmark.py main()
    │
    ├─ model_slug = slugify_model(args.model)
    │   "openrouter/nvidia/nemotron-3-super-120b-a12b:free"
    │   → "openrouter-nvidia-nemotron-3-super-120b-a12b-free"
    │
    ├─ agent_id = f"bench-{model_slug}"
    │   → "bench-openrouter-nvidia-nemotron-3-super-120b-a12b-free"
    │
    ├─ agent_workspace = Path(f"/tmp/pinchbench/{run_id}/agent_workspace")
    │
    └─ ensure_agent_exists(agent_id, args.model, agent_workspace)  ← ★ 여기서 생성
        │
        ├─ openclaw agents list → 이미 존재하는지 확인
        │   ├─ 존재하고 workspace 동일 → 그대로 사용 (재생성 안 함)
        │   ├─ 존재하지만 workspace 다름 → 삭제 후 재생성
        │   └─ 존재하지 않음 → 새로 생성
        │
        └─ openclaw agents add bench-openrouter-nvidia-... \
               --model openrouter/nvidia/nemotron-3-super-120b-a12b:free \
               --workspace /tmp/pinchbench/0015/agent_workspace \
               --non-interactive
```

**정리:** 에이전트는 `benchmark.py`의 `main()` 시작 직후, 첫 번째 태스크 실행 이전에 1회 생성된다. 이미 같은 이름의 에이전트가 있으면 workspace 경로가 맞는 한 재사용한다.

### 3.2 Judge 에이전트 생성 시점

Judge 에이전트는 테스트 에이전트와 달리 **첫 번째 llm_judge/hybrid 태스크의 채점 시점**에 생성된다.

```
benchmark.py 태스크 루프
    │
    ├─ execute_openclaw_task(task, agent_id, ...)  ← 테스트 에이전트가 태스크 수행
    │
    └─ grade_task(task, execution_result, judge_model=args.judge, ...)
        │
        ├─ grading_type == "automated" → Python grade() 함수만 실행, judge 불필요
        │
        ├─ grading_type == "llm_judge" → _grade_llm_judge(...)
        │   │
        │   └─ _ensure_judge_agent(judge_agent_prefix, judge_model, skill_dir)  ← ★ 여기서 생성
        │       │
        │       ├─ agent_id = "bench-judge-{slugify(judge_model)}"
        │       │   → "bench-judge-azure-openai-gpt-5-3-chat"
        │       │
        │       └─ ensure_agent_exists(agent_id, judge_model, workspace)
        │           → openclaw agents add bench-judge-azure-openai-gpt-5-3-chat \
        │               --model azure-openai/gpt-5.3-chat \
        │               --workspace /tmp/pinchbench/judge/workspace
        │
        └─ grading_type == "hybrid" → automated 채점 + llm_judge 채점 결합
```

**정리:** Judge 에이전트는 채점 단계에서 lazy하게 생성된다. automated-only 태스크만 실행하면 judge 에이전트는 아예 생성되지 않는다.


## 4. 태스크 실행 흐름

하나의 태스크가 실행되는 전체 과정:

```
┌──────────────────────────────────────────────────────────────────┐
│ Phase 1: 태스크 준비                                              │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  prepare_task_workspace(skill_dir, run_id, task, agent_id)       │
│  ├─ /tmp/pinchbench/{run_id}/agent_workspace/ 디렉토리 생성       │
│  └─ task.workspace_files에 정의된 파일을 workspace에 복사          │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│ Phase 2: 에이전트 실행                                            │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  subprocess.run([                                                │
│      "openclaw", "agent",                                        │
│      "--agent", "bench-openrouter-nvidia-nemotron-...",           │
│      "--session-id", "task_00_sanity_1712345678000",             │
│      "--message", task.prompt     ← 태스크의 Prompt 섹션 전송     │
│  ], cwd=workspace, timeout=task.timeout_seconds)                 │
│                                                                  │
│  에이전트가 OpenClaw을 통해 LLM 호출 → 응답 생성                   │
│  에이전트는 도구(파일 읽기/쓰기, 웹 검색 등)를 사용할 수 있음         │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│ Phase 3: Transcript 수집                                         │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  _load_transcript(agent_id, session_id, start_time)              │
│  ├─ ~/.openclaw/agents/{agent-id}/sessions/*.jsonl 파일 읽기      │
│  └─ 에이전트의 전체 대화 이력(턴, 도구 호출, 응답) 추출             │
│                                                                  │
│  _extract_usage_from_transcript(transcript)                      │
│  └─ 토큰 사용량, 비용, 요청 횟수 집계                              │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│ Phase 4: 채점                                                     │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  grade_task(task, execution_result, ...)                          │
│  ├─ automated:  task 파일 내 grade() Python 함수 실행              │
│  │   └─ transcript + workspace_path를 인자로 전달                  │
│  │   └─ 반환: {"score": 0.0~1.0, ...}                            │
│  │                                                                │
│  ├─ llm_judge:  judge 에이전트가 채점                              │
│  │   └─ (아래 §5 참조)                                            │
│  │                                                                │
│  └─ hybrid:     automated 점수와 llm_judge 점수를 가중 결합         │
│      └─ 기본 가중치: automated 50% + llm_judge 50%                │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```


## 5. Judge 채점 상세 흐름

LLM Judge는 테스트 에이전트의 수행 결과(transcript + workspace)를 다른 LLM에게 평가시키는 방식이다.

```
_grade_llm_judge()
    │
    ├─ 1. Transcript 요약
    │   _summarize_transcript(transcript)
    │   └─ 에이전트의 대화 내역을 텍스트로 변환
    │
    ├─ 2. Workspace 파일 읽기
    │   _read_workspace_files(workspace)
    │   └─ 에이전트가 생성/수정한 파일 내용 수집
    │
    ├─ 3. Judge 프롬프트 구성
    │   _build_judge_prompt(task, transcript_summary, rubric, workspace_content)
    │   └─ 태스크 설명 + 에이전트 행동 기록 + 채점 기준(rubric) → 하나의 프롬프트로 결합
    │
    ├─ 4. Judge 에이전트 확보
    │   _ensure_judge_agent("bench-judge", judge_model, skill_dir)
    │   └─ OpenClaw 에이전트 생성 (§3.2 참조)
    │
    ├─ 5. Judge 에이전트에 프롬프트 전송
    │   run_openclaw_prompt(agent_id, prompt, workspace, timeout=180초)
    │   │
    │   ├─ Bootstrap 파일 제거 (SOUL.md, IDENTITY.md 등)
    │   │   └─ Judge가 불필요한 페르소나/컨텍스트 없이 순수 채점에 집중하도록
    │   │
    │   ├─ 프롬프트가 3000자 초과 시 chunk 분할 전송
    │   │   └─ "Part 1/3: ...", "Part 2/3: ...", "Part 3/3 (final): ..."
    │   │
    │   └─ subprocess.run(["openclaw", "agent", "--agent", judge_agent_id,
    │       "--session-id", "judge_1712345678000", "--message", chunk])
    │       └─ Judge 모델(GPT-5.3)이 채점 결과를 JSON으로 응답
    │
    ├─ 6. 응답 파싱
    │   _parse_judge_response(transcript)
    │   └─ JSON 추출 (```json 코드블록 우선, 이후 중괄호 패턴 탐색)
    │
    └─ 7. 점수 정규화
        _normalize_judge_response(parsed)
        └─ { "scores": {...}, "total": 0.0~1.0, "notes": "..." }
```

### Judge의 채점 기준 (Rubric)

각 태스크의 `.md` 파일에 `LLM Judge Rubric` 섹션이 정의되어 있다. 없으면 `Grading Criteria` 섹션의 체크리스트로 대체한다.

Judge에게 전달되는 프롬프트 구조:
```
[태스크 설명]
[에이전트가 수행한 transcript 요약]
[에이전트가 생성/수정한 파일 내용]
[채점 기준 (rubric)]
→ "위 기준에 따라 0.0~1.0 점수를 JSON으로 반환하라"
```


## 6. 태스크 포맷

각 태스크는 `tasks/task_XX_name.md` 파일로 정의된다.

```markdown
---
id: task_00_sanity
name: Sanity Check
category: basic
grading_type: automated          ← automated | llm_judge | hybrid
timeout_seconds: 60
workspace_files: []              ← 태스크 시작 시 workspace에 복사할 파일
grading_weights:                 ← hybrid 전용
  automated: 0.5
  llm_judge: 0.5
---

## Prompt
(에이전트에게 보낼 지시문)

## Expected Behavior
(기대 행동 설명 — 채점 참고용)

## Grading Criteria
- [ ] 항목 1
- [ ] 항목 2

## Automated Checks
```python
def grade(transcript: list, workspace_path: str) -> dict:
    # transcript: 에이전트 대화 이력
    # workspace_path: 에이전트 작업 디렉토리 경로
    return {"score": 1.0, "max_score": 1.0, "details": {...}}
`` `

## LLM Judge Rubric
(Judge 모델에게 전달할 상세 채점 기준)
```

### 24개 태스크 전체 정의

#### 채점 방식별 분류

| 채점 방식 | 태스크 수 | 설명 |
|-----------|----------|------|
| `automated` | 9개 | Python 함수가 자동 채점. Judge 불필요 |
| `llm_judge` | 7개 | LLM이 transcript를 읽고 채점 |
| `hybrid` | 8개 | 자동 채점 50% + LLM 채점 50% (가중치 태스크별 설정 가능) |

#### 전체 태스크 목록

| # | ID | 태스크명 | 카테고리 | 채점 | 설명 |
|---|------|---------|---------|------|------|
| 0 | task_00_sanity | Sanity Check | basic | automated | 기본 응답 능력 확인 ("Hello, I'm ready!") |
| 1 | task_01_calendar | Calendar Event Creation | calendar | automated | ICS 이벤트 생성 (다음 주 화요일 3pm, john@example.com, "Project Sync") |
| 2 | task_02_stock | Stock Price Research | research | automated | Apple(AAPL) 주가 조사 → stock_report.txt (가격, 날짜, 시장 요약) |
| 3 | task_03_blog | Blog Post Writing | writing | llm_judge | 원격 근무 장점 500단어 블로그 → blog_post.md |
| 4 | task_04_weather | Weather Script Creation | coding | automated | wttr.in API로 샌프란시스코 날씨 가져오는 weather.py 작성 |
| 5 | task_05_summary | Document Summarization | comprehension | llm_judge | summary_source.txt 읽고 3문단 요약 → summary_output.txt |
| 6 | task_06_events | Tech Conference Research | research | llm_judge | 5개 기술 컨퍼런스 조사 (이름, 날짜, 장소, 웹사이트) → events.md |
| 7 | task_07_email | Professional Email Drafting | writing | llm_judge | 일정 충돌로 미팅 정중히 거절하는 이메일 → email_draft.txt |
| 8 | task_08_memory | Memory Retrieval from Context | context | automated | notes.md 읽고 "베타 릴리스 마감일은?" 답변 → answer.txt |
| 9 | task_09_files | File Structure Creation | file_ops | automated | 프로젝트 구조 생성: src/main.py, README.md, .gitignore |
| 10 | task_10_workflow | Multi-step API Workflow | complex | hybrid | config.json 읽기 → API 호출 스크립트 작성 → NOTES.md 문서화 |
| 11 | task_11_clawdhub | Create Project Structure | file_ops | automated | Python 라이브러리 프로젝트: src/datautils/, tests/, pyproject.toml |
| 12 | task_12_skill_search | Search and Replace in Files | file_ops | automated | config/ 파일에서 localhost→prod-db, dev→prod, debug→warn 일괄 치환 |
| 13 | task_13_image_gen | AI Image Generation | creative | hybrid | "로봇이 카페에서 책 읽는" 이미지 생성 → robot_cafe.png |
| 14 | task_14_humanizer | Humanize AI-Generated Blog | content_transformation | llm_judge | AI 생성 블로그를 자연스럽게 리라이팅 → humanized_blog.txt |
| 15 | task_15_daily_summary | Daily Research Summary | synthesis | llm_judge | research/ 폴더 리뷰 → daily_briefing.md 종합 보고서 |
| 16a | task_16_email_triage | Email Inbox Triage | organization | hybrid | 13개 이메일 우선순위(P0-P4) 분류/카테고리 지정 → triage_report.md |
| 16b | task_16_market_research | Competitive Market Research | research | hybrid | 엔터프라이즈 APM 시장 분석: 경쟁사 5개, 차별화, 트렌드, 가격 |
| 17 | task_17_email_search | Email Search & Summarization | comprehension | hybrid | 12개 이메일에서 "Project Alpha" 검색 → alpha_summary.md |
| 18 | task_18_spreadsheet_summary | CSV/Excel Data Summary | data_analysis | hybrid | quarterly_sales.csv + company_expenses.xlsx → data_summary.md |
| 20 | task_20_eli5_pdf_summary | ELI5 PDF Summarization | comprehension | llm_judge | GPT4.pdf 읽고 200-400단어 쉬운 요약 → eli5_summary.txt |
| 21 | task_21_openclaw_comprehension | OpenClaw Report Comprehension | comprehension | automated | openclaw_report.pdf에서 8개 사실 추출 (스킬 수, 카테고리, API 유형 등) |
| 22 | task_22_second_brain | Second Brain Knowledge | memory | hybrid | 멀티 세션: 사실 저장 → 다른 세션에서 recall |
| 24 | task_24_polymarket_briefing | Polymarket + News Briefing | research | hybrid | 상위 3개 예측 시장 + 관련 뉴스(48시간) → polymarket_briefing.md |

> **참고**: task_19, task_23은 PinchBench에 정의되어 있지 않다 (번호 건너뜀). task_16은 두 개가 같은 번호를 공유한다.

#### 카테고리 → 5개 그룹 매핑

| 그룹 | 원본 카테고리 | 해당 태스크 |
|------|-------------|-----------|
| **이해/기억** (understanding) | comprehension, context, memory | #5, #8, #17, #20, #21, #22 |
| **조사/분석** (research) | research, synthesis, data_analysis | #2, #6, #15, #16b, #18, #24 |
| **생성/작문** (creation) | writing, creative, content_transformation | #3, #7, #13, #14 |
| **실행/코딩** (execution) | file_ops, coding, complex | #4, #9, #10, #11, #12 |
| **기본/관리** (basic) | calendar, organization, basic | #0, #1, #16a |


### 모델별 태스크 한계 분석

2026-04-07 기준 solar-pro3 (62.1%) / qwen3.5-122b-a10b (77.5%) 실행 결과 기반.

#### task_13 (AI Image Generation) — 양쪽 모두 실패

| 항목 | solar-pro3 (11.5점) | qwen3.5-122b-a10b (8.5점) |
|------|---------------------|--------------------------|
| 원인 | 잘못된 도구 사용 (`video_generate` 호출) | 도구 없다고 판단, 수행 거부 |
| 행동 | video=false 파라미터로 반복 시도 → 타임아웃 | 합리적인 프롬프트는 제안했으나 실행 안 함 |
| 결과 | 이미지 파일 미생성, 가짜 job ID 반환 | 이미지 파일 미생성 |

**원인 분석**: 이 태스크는 OpenClaw의 이미지 생성 도구(`/image_gen` 또는 유사 스킬)를 사용해야 하는데, 두 모델 모두 올바른 도구를 찾지 못했다. 이미지 생성 자체가 텍스트 모델의 내재적 한계라기보다는, OpenClaw 에이전트 환경에서 해당 도구를 올바르게 활용하는 능력의 차이다.

#### 그 외 주요 차이가 나는 태스크

| 태스크 | solar-pro3 | qwen3.5-122b-a10b | 차이 원인 |
|--------|-----------|-------------------|----------|
| task_20 (PDF 요약) | 6.2점 (읽었지만 출력 안 함) | 0.0점 (타임아웃 332.6초) | PDF 처리 능력 부족 (양쪽 모두) |
| task_21 (OpenClaw PDF 이해) | 0.0점 (추출 실패) | 100.0점 (8개 사실 전부 정확) | 구조화된 PDF 이해력 차이 |
| task_22 (멀티세션 메모리) | 94.0점 | 0.0점 (수행 미시도) | 메모리 도구 활용 능력 차이 |
| task_24 (Polymarket 리서치) | 54.8점 (부분 성공, 3번째 시장 환각) | 0.0점 (수행 미시도) | 웹 리서치 도구 활용 능력 차이 |

**핵심 패턴**: 두 모델의 강약이 정확히 반대다. solar-pro3는 도구 활용(메모리, 웹 리서치)에 강하지만 텍스트 이해(PDF)에 약하고, qwen3.5-122b-a10b는 텍스트 이해에 강하지만 도구 활용에서 수행을 회피하는 경향이 있다.


## 7. 점수 산출 방식

### 단일 실행 (--runs 1)
각 태스크의 점수(0.0~1.0)를 합산하여 백분율로 표시:
```
총점 = Σ(태스크 점수) / 태스크 수 × 100%
```

### 복수 실행 (--runs N)
각 태스크를 N번 반복 실행하여:
- **best score**: 각 태스크의 최고 점수 사용
- **average score**: 각 태스크의 평균 점수 사용

공식 PinchBench 리더보드는 best와 average를 모두 게시한다.


## 8. 우리 환경에서의 실행 계획

```
테스트 모델: openrouter/nvidia/nemotron-3-super-120b-a12b:free (무료)
Judge 모델: azure-openai/gpt-5.3-chat (Azure 크레딧)
실행 명령:
  python3 benchmark.py \
    --model openrouter/nvidia/nemotron-3-super-120b-a12b:free \
    --judge azure-openai/gpt-5.3-chat \
    --runs 3

예상 결과:
  - 테스트 에이전트 생성: bench-openrouter-nvidia-nemotron-3-super-120b-a12b-free
  - Judge 에이전트 생성: bench-judge-azure-openai-gpt-5-3-chat
  - 24 태스크 × 3 실행 = 72회 테스트 에이전트 호출
  - llm_judge/hybrid 15개 태스크 × 3 실행 = 45회 judge 호출

토큰 비용 (judge 기준, 추정):
  - judge 1회 호출: ~12,000 input tokens (프롬프트+transcript)
  - 45회 × 12,000 = ~540,000 input tokens
  - Azure GPT-5.3 가격은 사용자 크레딧으로 처리
```


## 9. 파일 구조

```
~/pinchbench-skill/
├── scripts/
│   ├── benchmark.py          ← 메인 실행 스크립트
│   ├── lib_agent.py          ← 에이전트 생성/실행/세션 관리
│   ├── lib_grading.py        ← 채점 로직 (automated + llm_judge + hybrid)
│   ├── lib_tasks.py          ← 태스크 로더 (YAML frontmatter 파싱)
│   ├── lib_upload.py         ← 리더보드 업로드
│   └── run.sh                ← 쉘 래퍼
├── tasks/
│   ├── TASK_TEMPLATE.md      ← 태스크 작성 템플릿
│   ├── task_00_sanity.md     ← 기본 동작 확인
│   ├── task_01_calendar.md   ← 일정 관리
│   ├── ...
│   └── task_24_polymarket_briefing.md
├── tests/
│   └── test_lib_grading.py   ← 채점 로직 단위 테스트
└── crab.txt                  ← ASCII 아트 (시작 시 출력)
```


## 10. 프레임워크 의존성 분석

PinchBench는 3개 계층으로 구성되며, 각 계층의 프레임워크 의존도가 다르다.

### 계층별 의존성

| 계층 | 해당 코드 | OpenClaw 의존도 | 설명 |
|------|----------|----------------|------|
| **태스크 정의** | `tasks/*.md` — Prompt, Expected Behavior, Rubric | **없음** | 자연어 지시문. "블로그 글을 써라", "PDF를 요약하라" 등 프레임워크 특정 명령이 없다 |
| **실행 하네스** | `lib_agent.py` — 에이전트 생성, 세션 관리, 프롬프트 전송 | **강함** | `openclaw agent` CLI를 직접 호출. `ensure_agent_exists()`, `run_openclaw_prompt()` 등 OpenClaw 전용 함수 |
| **채점 로직** | `lib_grading.py` + 각 태스크의 `grade()` 함수 | **약함** | 순수 Python으로 파일 존재 확인, 텍스트 패턴 매칭, JSON 검증 등 수행. LLM judge 호출 부분만 OpenClaw 경유 |

### 왜 태스크가 프레임워크 비의존적인가

24개 태스크의 Prompt 섹션을 분석하면:
- `openclaw`이라는 단어가 등장하는 태스크: 0개
- 프레임워크 특정 도구명을 지시하는 태스크: 0개 (task_13도 "generate an image"라고만 함)
- 모든 지시가 "파일을 만들어라", "검색해서 정리해라", "CSV를 분석해라" 등 **일반적인 에이전트 능력**을 요구

즉, 같은 태스크를 CrewAI, LangGraph, AutoGen 등 다른 에이전트 프레임워크에서도 동일하게 수행시킬 수 있다.

### 다른 프레임워크로 포팅 시

```
변경 필요:  lib_agent.py  (에이전트 생성/실행/세션 관리 — 프레임워크별 재작성)
변경 가능:  lib_grading.py의 LLM judge 호출 부분 (현재 OpenClaw 에이전트로 judge 실행)
변경 불필요: tasks/*.md (태스크 정의), grade() 함수 (순수 Python 채점 로직)
```

실질적으로 `lib_agent.py` 하나만 대상 프레임워크의 에이전트 실행 API로 교체하면 된다. 태스크 정의와 자동 채점 로직은 그대로 재사용 가능하다.
