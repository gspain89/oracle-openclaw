#!/usr/bin/env bash
# run-pinchbench.sh — 단일 모델 PinchBench 실행
# 사용법: bash run-pinchbench.sh <model_id> [--dry-run]
# 예시:   bash run-pinchbench.sh arcee-ai/trinity-large-preview:free
set -euo pipefail

MODEL_ID="${1:-}"
DRY_RUN="${2:-}"

if [ -z "$MODEL_ID" ]; then
  echo "사용법: bash run-pinchbench.sh <model_id> [--dry-run]"
  echo "예시:   bash run-pinchbench.sh arcee-ai/trinity-large-preview:free"
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PINCHBENCH_DIR="$HOME/pinchbench-skill"
RESULTS_DIR="$REPO_ROOT/results/raw/pinchbench"
MODELS_FILE="$REPO_ROOT/server/config/models.json"
TIMESTAMP="$(date -u '+%Y%m%d-%H%M%S')"

# 모델 ID에서 파일명-안전 문자열 생성
SAFE_NAME="$(echo "$MODEL_ID" | tr '/:' '__')"
RUN_OUTPUT_DIR="$RESULTS_DIR/${SAFE_NAME}_${TIMESTAMP}"

# ── OpenClaw 프로바이더 접두어 해석 ──
# models.json의 provider 필드를 보고 openclaw에서 사용할 전체 모델 ID를 결정
# 예: provider=openrouter, id=arcee-ai/xxx → openrouter/arcee-ai/xxx
#     provider=dashscope, id=qwen3.5-plus → modelstudio/qwen3.5-plus
OPENCLAW_MODEL_ID="$MODEL_ID"
if [ -f "$MODELS_FILE" ]; then
  PROVIDER=$(python3 -c "
import json
with open('$MODELS_FILE') as f:
    data = json.load(f)
for m in data['models']:
    if m['id'] == '$MODEL_ID':
        print(m.get('provider', ''))
        break
" 2>/dev/null)

  case "$PROVIDER" in
    openrouter) OPENCLAW_MODEL_ID="openrouter/$MODEL_ID" ;;
    dashscope)  OPENCLAW_MODEL_ID="modelstudio/$MODEL_ID" ;;
    upstage)    OPENCLAW_MODEL_ID="upstage/$MODEL_ID" ;;
  esac
fi

echo "  OpenClaw 모델 ID: $OPENCLAW_MODEL_ID"

echo "=== PinchBench 실행 ==="
echo "모델: $MODEL_ID"
echo "시각: $TIMESTAMP"
echo "출력 디렉토리: $RUN_OUTPUT_DIR"
echo ""

# ── 사전 확인 ──
if [ ! -d "$PINCHBENCH_DIR" ]; then
  echo "ERROR: PinchBench 미설치. 먼저 setup-server.sh 실행"
  exit 1
fi

# uv 필요 — PinchBench가 uv run으로 실행됨
if ! command -v uv &>/dev/null; then
  source "$HOME/.local/bin/env" 2>/dev/null || true
fi
if ! command -v uv &>/dev/null; then
  echo "ERROR: uv 미설치. curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

mkdir -p "$RESULTS_DIR"

# ── 이미 최근 실행이 있는지 확인 (24시간 이내) ──
RECENT=$(find "$RESULTS_DIR" -name "${SAFE_NAME}_*" -type d -mmin -1440 2>/dev/null | head -1)
if [ -n "$RECENT" ]; then
  echo "WARN: 24시간 이내 실행 결과 존재 — $RECENT"
  echo "  건너뛰려면 Ctrl+C, 계속하려면 5초 대기..."
  sleep 5
fi

# ── Dry run ──
if [ "$DRY_RUN" = "--dry-run" ]; then
  echo "[DRY RUN] 실제 실행하지 않음"
  echo "  명령어: cd $PINCHBENCH_DIR && uv run scripts/benchmark.py --model $OPENCLAW_MODEL_ID --output-dir $RUN_OUTPUT_DIR --no-upload --suite automated-only"
  exit 0
fi

# ── OpenClaw 모델 설정 ──
echo "[1/3] OpenClaw 기본 모델을 $OPENCLAW_MODEL_ID 로 전환..."
openclaw config set agents.defaults.model "$OPENCLAW_MODEL_ID" 2>/dev/null || {
  echo "WARN: openclaw config set 실패 — 수동 설정 필요"
}

# ── PinchBench 실행 ──
echo "[2/3] PinchBench 실행 중 (automated-only 태스크, 약 11~40분 소요)..."
echo "  시작: $(date -u '+%H:%M:%S UTC')"

START_SEC=$(date +%s)

cd "$PINCHBENCH_DIR"

# PinchBench 실행 — uv run으로 benchmark.py 호출
# --no-upload: 외부 서버 업로드 방지
# --suite automated-only: 자동 채점 태스크만 (judge 모델 비용 절약)
# --no-fail-fast: 실패해도 나머지 태스크 계속
uv run scripts/benchmark.py \
  --model "$OPENCLAW_MODEL_ID" \
  --output-dir "$RUN_OUTPUT_DIR" \
  --no-upload \
  --suite automated-only \
  --no-fail-fast \
  2>&1 | tee "$RESULTS_DIR/${SAFE_NAME}_${TIMESTAMP}.log"

END_SEC=$(date +%s)
ELAPSED=$((END_SEC - START_SEC))

echo ""
echo "[3/3] 완료"
echo "  소요 시간: ${ELAPSED}초 ($((ELAPSED / 60))분 $((ELAPSED % 60))초)"
echo "  출력 디렉토리: $RUN_OUTPUT_DIR"

# ── 결과 요약 출력 ── PinchBench가 output-dir에 results.json 생성
RESULT_FILE=$(find "$RUN_OUTPUT_DIR" -name "results.json" -o -name "*.json" 2>/dev/null | head -1)
if [ -n "$RESULT_FILE" ] && [ -f "$RESULT_FILE" ]; then
  echo ""
  echo "--- 결과 요약 ---"
  echo "  결과 파일: $RESULT_FILE"
  python3 -c "
import json, sys
try:
    with open('$RESULT_FILE') as f:
        data = json.load(f)
    s = data.get('summary', data)
    print(f'  점수: {s.get(\"best_score\", s.get(\"score\", s.get(\"overall_score\", \"N/A\")))}')
    print(f'  완료 태스크: {s.get(\"tasks_completed\", s.get(\"completed\", \"N/A\"))}/{s.get(\"tasks_total\", s.get(\"total\", 23))}')
    if 'tasks' in data:
        passed = sum(1 for t in data['tasks'] if t.get('passed') or t.get('score', 0) > 0.5)
        print(f'  통과 태스크: {passed}/{len(data[\"tasks\"])}')
except Exception as e:
    print(f'  (파싱 실패: {e})')
" 2>/dev/null || echo "  (결과 파싱 불가)"

  # 결과를 표준 위치에 복사 (normalize.py 호환)
  cp "$RESULT_FILE" "$RESULTS_DIR/${SAFE_NAME}_${TIMESTAMP}.json" 2>/dev/null || true
  echo "  복사: $RESULTS_DIR/${SAFE_NAME}_${TIMESTAMP}.json"

  # ── 0% 태스크 재시도 (1회) ──
  # 1차 실행에서 0%인 태스크만 추출하여 1회 재실행. 결과를 1차에 병합.
  FAILED_TASKS=$(python3 -c "
import json
with open('$RESULT_FILE') as f:
    data = json.load(f)
failed = [t['task_id'] for t in data['tasks']
          if t['grading']['mean'] == 0.0 and t['task_id'] != 'task_00_sanity']
print(','.join(failed))
" 2>/dev/null)

  if [ -n "$FAILED_TASKS" ]; then
    echo ""
    echo "=== 0% 태스크 재시도 (1회) ==="
    echo "  대상: $FAILED_TASKS"
    RETRY_DIR="${RUN_OUTPUT_DIR}_retry"
    RETRY_START=$(date +%s)

    uv run scripts/benchmark.py \
      --model "$OPENCLAW_MODEL_ID" \
      --output-dir "$RETRY_DIR" \
      --no-upload \
      --suite "$FAILED_TASKS" \
      --no-fail-fast \
      2>&1 | tee -a "$RESULTS_DIR/${SAFE_NAME}_${TIMESTAMP}.log"

    RETRY_END=$(date +%s)
    RETRY_ELAPSED=$((RETRY_END - RETRY_START))
    echo "  재시도 소요: ${RETRY_ELAPSED}초"

    # 재시도 결과 병합 — 0%였던 태스크를 재시도 점수로 교체
    RETRY_FILE=$(find "$RETRY_DIR" -name "*.json" -type f 2>/dev/null | head -1)
    if [ -n "$RETRY_FILE" ] && [ -f "$RETRY_FILE" ]; then
      python3 -c "
import json
with open('$RESULT_FILE') as f:
    orig = json.load(f)
with open('$RETRY_FILE') as f:
    retry = json.load(f)

# 재시도 결과를 dict로 변환
retry_map = {t['task_id']: t for t in retry.get('tasks', [])}

# 원본에서 0%였던 태스크를 재시도 결과로 교체 (재시도도 0%면 그대로)
total = 0.0
for i, t in enumerate(orig['tasks']):
    tid = t['task_id']
    if tid in retry_map:
        r = retry_map[tid]
        orig_score = t['grading']['mean']
        retry_score = r['grading']['mean']
        if retry_score > orig_score:
            orig['tasks'][i] = r
            print(f'  {tid}: {orig_score:.0%} -> {retry_score:.0%} (개선)')
        else:
            print(f'  {tid}: {orig_score:.0%} -> {retry_score:.0%} (유지)')
    total += orig['tasks'][i]['grading']['mean']

# 전체 점수 재계산
n = len(orig['tasks'])
orig['overall_score'] = total / n if n > 0 else 0
orig['retry_applied'] = True
print(f'  최종 점수: {total:.1f}/{n} ({total/n*100:.1f}%)')

with open('$RESULT_FILE', 'w') as f:
    json.dump(orig, f, indent=2, ensure_ascii=False)
" 2>/dev/null
      # 병합된 결과를 표준 위치에 재복사
      cp "$RESULT_FILE" "$RESULTS_DIR/${SAFE_NAME}_${TIMESTAMP}.json" 2>/dev/null || true
    fi
  else
    echo ""
    echo "0% 태스크 없음 — 재시도 불필요"
  fi
else
  echo ""
  echo "결과 디렉토리 내용:"
  ls -la "$RUN_OUTPUT_DIR" 2>/dev/null || echo "  (디렉토리 비어있음)"
  echo "WARN: 결과 JSON 파일을 찾지 못했습니다."
  exit 1
fi
