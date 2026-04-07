#!/usr/bin/env bash
# run-claw-bench-ko.sh — 단일 모델 claw-bench-ko 실행
# 사용법: bash run-claw-bench-ko.sh <model_id> [--judge <judge_model>] [--runs <N>] [--dry-run]
# 예시:   bash run-claw-bench-ko.sh nvidia/nemotron-3-super-120b-a12b:free --runs 3
set -euo pipefail

MODEL_ID="${1:-}"
shift || true

if [ -z "$MODEL_ID" ]; then
  echo "사용법: bash run-claw-bench-ko.sh <model_id> [--judge <model>] [--runs <N>] [--dry-run]"
  echo "예시:   bash run-claw-bench-ko.sh nvidia/nemotron-3-super-120b-a12b:free --runs 3"
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BENCH_DIR="$REPO_ROOT/server/claw-bench-ko"
RESULTS_DIR="$REPO_ROOT/results/raw/korean"
TIMESTAMP="$(date -u '+%Y%m%d-%H%M%S')"

# 모델 ID에서 파일명 안전 문자열 생성
SAFE_NAME="$(echo "$MODEL_ID" | tr '/:.' '__')"
RUN_OUTPUT_DIR="$RESULTS_DIR/${SAFE_NAME}_${TIMESTAMP}"

# ── OpenClaw 모델 ID 해석 ──
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/resolve-model.sh" "$MODEL_ID"

# ── 인자 파싱 ──
JUDGE="anthropic/claude-opus-4-6"
RUNS=1
DRY_RUN=""
EXTRA_ARGS=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --judge)  JUDGE="$2"; shift 2 ;;
    --runs)   RUNS="$2"; shift 2 ;;
    --dry-run) DRY_RUN="--dry-run"; shift ;;
    --task)   EXTRA_ARGS="$EXTRA_ARGS --task $2"; shift 2 ;;
    --no-fail-fast) EXTRA_ARGS="$EXTRA_ARGS --no-fail-fast"; shift ;;
    *) echo "알 수 없는 옵션: $1"; exit 1 ;;
  esac
done

echo "=== ClawBench-KO 실행 ==="
echo "모델: $MODEL_ID (OpenClaw: $OPENCLAW_MODEL_ID)"
echo "Judge: $JUDGE"
echo "반복: ${RUNS}회"
echo "시각: $TIMESTAMP"
echo "출력: $RUN_OUTPUT_DIR"
echo ""

# ── 사전 확인 ──
if [ ! -f "$BENCH_DIR/runner.py" ]; then
  echo "ERROR: runner.py 미발견 — $BENCH_DIR"
  exit 1
fi

# openclaw CLI는 resolve-model.sh에서 이미 확인됨

mkdir -p "$RESULTS_DIR"

# ── 실행 ──
START_SEC=$(date +%s)

python3 "$BENCH_DIR/runner.py" \
  --model "$OPENCLAW_MODEL_ID" \
  --judge "$JUDGE" \
  --runs "$RUNS" \
  --output-dir "$RUN_OUTPUT_DIR" \
  --skip-preflight \
  $DRY_RUN \
  $EXTRA_ARGS \
  2>&1 | tee "$RESULTS_DIR/${SAFE_NAME}_${TIMESTAMP}.log"

END_SEC=$(date +%s)
ELAPSED=$((END_SEC - START_SEC))

echo ""
echo "=== 완료 ==="
echo "소요 시간: ${ELAPSED}초 ($((ELAPSED / 60))분 $((ELAPSED % 60))초)"

# ── 결과 복사 (normalize.py 호환) ──
RESULT_FILE="$RUN_OUTPUT_DIR/results.json"
if [ -f "$RESULT_FILE" ]; then
  cp "$RESULT_FILE" "$RESULTS_DIR/${SAFE_NAME}_${TIMESTAMP}.json"
  echo "결과 복사: $RESULTS_DIR/${SAFE_NAME}_${TIMESTAMP}.json"

  # ── 0% 태스크 재시도 (1회) ──
  # 1차 실행에서 0%인 태스크만 추출하여 1회 재실행. 결과를 1차에 병합.
  FAILED_TASKS=$(python3 -c "
import json
with open('$RESULT_FILE') as f:
    data = json.load(f)
failed = [t['task_id'] for t in data['tasks']
          if t['grading']['mean'] == 0.0]
print(','.join(failed))
" 2>/dev/null)

  if [ -n "$FAILED_TASKS" ]; then
    echo ""
    echo "=== 0% 태스크 재시도 (1회) ==="
    echo "  대상: $FAILED_TASKS"
    RETRY_DIR="${RUN_OUTPUT_DIR}_retry"
    RETRY_START=$(date +%s)

    python3 "$BENCH_DIR/runner.py" \
      --model "$OPENCLAW_MODEL_ID" \
      --judge "$JUDGE" \
      --runs 1 \
      --output-dir "$RETRY_DIR" \
      --skip-preflight \
      --task "$FAILED_TASKS" \
      --no-fail-fast \
      2>&1 | tee -a "$RESULTS_DIR/${SAFE_NAME}_${TIMESTAMP}.log"

    RETRY_END=$(date +%s)
    RETRY_ELAPSED=$((RETRY_END - RETRY_START))
    echo "  재시도 소요: ${RETRY_ELAPSED}초"

    # 재시도 결과 병합 — 0%였던 태스크를 재시도 점수로 교체
    RETRY_FILE="$RETRY_DIR/results.json"
    if [ -f "$RETRY_FILE" ]; then
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
seen = set()
for i, t in enumerate(orig['tasks']):
    tid = t['task_id']
    if tid in seen:
        continue
    seen.add(tid)
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

# 전체 점수 재계산 (ClawBench-KO: overall_score는 dict)
n = len(seen)
mean = total / n if n > 0 else 0
orig['overall_score'] = {
    'mean': round(mean, 4),
    'total_earned': round(total, 4),
    'total_possible': float(n),
}
orig['retry_applied'] = True
print(f'  최종 점수: {total:.1f}/{n} ({mean*100:.1f}%)')

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
fi
