# Run #001: ClawBench-KO Full Run (10 Tasks)

- **Date**: 2026-04-04
- **Model**: `openrouter/nvidia/nemotron-3-super-120b-a12b:free` (Nemotron 3 Super 120B)
- **Judge**: `azure-openai/gpt-5.2-chat` (GPT-5.2)
- **Runs per task**: 1
- **Total duration**: 1087.3 seconds (18.1 minutes)
- **Overall score**: **29.86 / 100**

## Per-Task Results

| # | Task | Category | Grading | Score | Duration | Output Created |
|---|------|----------|---------|------:|----------:|:-:|
| 1 | addr_parse | data_processing | automated | 0.00 | 107s | No |
| 2 | num_convert | data_processing | automated | 0.00 | 90s | No |
| 3 | phone_normalize | data_processing | automated | 0.00 | 85s | No |
| 4 | csv_transform | data_processing | hybrid | 97.50 | 58s | Yes |
| 5 | meeting_minutes | document_generation | llm_judge | 0.00 | 76s | No |
| 6 | biz_email | document_generation | llm_judge | 5.00 | 121s | Yes |
| 7 | news_summary | document_generation | llm_judge | 85.00 | 62s | Yes |
| 8 | invoice_gen | korean_system | hybrid | 61.11 | 82s | Yes |
| 9 | resume_parse | korean_system | hybrid | 0.00 | 85s | No |
| 10 | regulation_extract | korean_system | hybrid | 50.00 | 180s | Yes |

## Score Distribution by Grading Type

| Grading Type | Tasks | Average Score |
|---|---|---|
| automated | 3 | 0.00 |
| llm_judge | 3 | 30.00 |
| hybrid | 4 | 52.15 |

## Detailed Analysis

### Succeeded (score > 50)

**csv_transform (97.50)** — Best result. Automated: 7/7 checks passed (file exists, UTF-8 encoding, correct header, 15 rows, date format, amount format, type column). Judge: 95/100 ("변환 정확도와 한국어 헤더, 날짜·금액 포맷이 모두 올바름"). Agent wrote a `process_transactions.py` script and executed it.

**news_summary (85.00)** — Judge: 85/100. Breakdown: accuracy 30/30, completeness 25/30, conciseness 10/20, Korean quality 20/20. Feedback: "핵심 수치와 정책, 투자, HBM 경쟁 구도가 정확히 반영. 분량이 600자를 초과하여 간결성 기준 미충족." Agent created `summary.md` with correct semiconductor news synthesis.

**invoice_gen (61.11)** — Automated: 2/9 (file_exists + json_valid only; `supplier`/`buyer`/`items`/`total` field checks all failed — agent likely used Korean key names instead of English). Judge: 100/100 ("공급가액, 세액 10% 원 단위 절사, 합계 계산이 모두 정확"). Agent wrote `create_invoice.py` and generated `invoice.json`.

**regulation_extract (50.00)** — Automated: 5/5 (checklist.json created, valid JSON, items field, 8+ items, required fields present). Judge: 0/100 ("에이전트 출력이 전혀 제공되지 않아"). Timed out at 180s (rc=-1). Workspace also contained leftover `parse_resume.py` from previous task.

### Failed (score < 50)

**addr_parse (0.00)** — Agent ran 107s, returned 0, but workspace only contained input `addresses.txt`. No `result.json` created. All 13 automated checks failed.

**num_convert (0.00)** — Agent ran 90s, returned 0, but no `result.json`. All 18 automated checks failed.

**phone_normalize (0.00)** — Agent ran 85s, returned 0, but no `result.json`. All 13 automated checks failed.

**meeting_minutes (0.00)** — Judge: 0/100. Feedback: "태스크와 무관한 CSV 변환 결과를 제출하여 회의록 작성 요구사항을 전혀 충족하지 못함." Workspace contained only `transcript.txt` (input). Bug: agent likely saw residual state from the previous csv_transform task.

**biz_email (5.00)** — Agent created `email.txt` but judge: 5/100. Feedback: "파일 존재 여부를 안내하는 답변을 제출하여 요구사항을 거의 충족하지 못함." Agent appears to have echoed file listing rather than writing an actual email.

**resume_parse (0.00)** — Workspace only contained `resume.txt` (input). No `result.json` created. Automated: 0/11, Judge: 0/100.

## Identified Issues

### 1. Agent fails to create output files for automated tasks

All 3 pure automated tasks (addr_parse, num_convert, phone_normalize) failed because the agent did not write `result.json` to the workspace. The agent processed the input (ran 85-107s, returned exit code 0) but likely responded in conversation rather than creating a file. The task prompts explicitly state "결과를 workspace에 result.json 파일로 저장하세요" but the agent did not execute file writes.

Possible cause: Nemotron 3 Super 120B may not reliably handle file-writing tool calls through the OpenClaw agent interface.

### 2. Workspace contamination between tasks

meeting_minutes (task 5) received judge feedback about "CSV 변환 결과" — output from csv_transform (task 4) leaked into the workspace. The runner.py workspace cleanup between tasks is not fully effective.

### 3. invoice_gen field name mismatch

invoice_gen scored 100/100 from judge (all calculations correct) but only 2/9 from automated checks. The agent used Korean or differently-structured JSON keys instead of the expected `supplier`, `buyer`, `items`, `total` fields. The grading checks use exact English key names.

### 4. regulation_extract timeout

Task hit the 180s timeout limit (rc=-1). The agent was still processing when killed. Despite timeout, automated checks passed (5/5) because `checklist.json` was partially written. Judge scored 0 due to incomplete or missing agent output.

## Raw Results Location

Server: `~/oracle-openclaw/server/claw-bench-ko/results/openrouter-nvidia-nemotron-3-super-120b-a12b-free_20260404-102312/results.json`
