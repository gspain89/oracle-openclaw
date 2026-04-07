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
JUDGE="azure-openai/gpt-5.3-chat"
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
fi
