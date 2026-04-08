#!/usr/bin/env bash
# run-all.sh — 벤치마크 오케스트레이터
#
# 사용법:
#   bash run-all.sh <model_id> [--runs N] [--bench pb|ko|all] [--dry-run]
#   bash run-all.sh --all-models [--runs N] [--free-only] [--dry-run]
#
# 예시:
#   bash run-all.sh qwen3.5-27b --runs 3              # 두 벤치마크 각 3회
#   bash run-all.sh qwen3.5-27b --runs 1 --bench pb   # PinchBench만 1회
#   bash run-all.sh --all-models --runs 1 --free-only  # 무료 모델 전체
#
# 동작:
#   1. PinchBench 실행 (순차, --runs N 만큼 반복)
#   2. ClawBench-KO 실행 (순차, --runs N 만큼 반복)
#   3. normalize.py 호출 → leaderboard.json 갱신
#   4. (선택) deploy-results.sh 호출
#
# 벤치마크는 반드시 순차 실행 — 병렬 실행 금지
set -euo pipefail

# ── 인자 파싱 ──
MODEL_ID=""
ALL_MODELS=""
RUNS=1
BENCH="all"  # pb, ko, all
DRY_RUN=""
FREE_ONLY=""
NO_NORMALIZE=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --all-models) ALL_MODELS="true"; shift ;;
    --runs)       RUNS="$2"; shift 2 ;;
    --bench)      BENCH="$2"; shift 2 ;;
    --dry-run)    DRY_RUN="--dry-run"; shift ;;
    --free-only)  FREE_ONLY="true"; shift ;;
    --no-normalize) NO_NORMALIZE="true"; shift ;;
    -*)           echo "알 수 없는 옵션: $1"; exit 1 ;;
    *)            MODEL_ID="$1"; shift ;;
  esac
done

if [ -z "$MODEL_ID" ] && [ -z "$ALL_MODELS" ]; then
  echo "사용법:"
  echo "  bash run-all.sh <model_id> [--runs N] [--bench pb|ko|all] [--dry-run]"
  echo "  bash run-all.sh --all-models [--runs N] [--free-only] [--dry-run]"
  echo ""
  echo "옵션:"
  echo "  --runs N        벤치마크별 반복 횟수 (기본: 1)"
  echo "  --bench pb|ko|all  실행할 벤치마크 (기본: all)"
  echo "  --dry-run       실제 실행 없이 명령어 확인"
  echo "  --free-only     무료 모델만 실행 (--all-models 시)"
  echo "  --no-normalize  normalize.py 실행 건너뜀"
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT_DIR="$REPO_ROOT/server/scripts"
MODELS_FILE="$REPO_ROOT/server/config/models.json"

if [ ! -f "$MODELS_FILE" ]; then
  echo "ERROR: $MODELS_FILE 없음"
  exit 1
fi

# ── nvm 환경 로드 (OpenClaw CLI 필요) ──
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh" 2>/dev/null || true

# ── OpenClaw 등록 모델 목록 캐싱 (사전 검증용) ──
OPENCLAW_MODELS_CACHE=$(openclaw models list 2>/dev/null || echo "")
if [ -z "$OPENCLAW_MODELS_CACHE" ]; then
  echo "ERROR: openclaw models list 실행 실패. openclaw CLI가 올바르게 설정되어 있는지 확인하세요."
  exit 1
fi

# ── 모델 목록 구성 ──
if [ -n "$ALL_MODELS" ]; then
  MODELS=$(python3 -c "
import json
with open('$MODELS_FILE') as f:
    data = json.load(f)
models = data['models']
free = [m for m in models if m['free']]
paid = [m for m in models if not m['free']]
ordered = free + paid
for m in ordered:
    free_flag = '1' if m['free'] else '0'
    print(f'{m[\"id\"]}|{m[\"name\"]}|{free_flag}')
")

  # --all-models 사전 검증: 각 모델이 openclaw에 등록되어 있는지 확인
  echo "모델 사전 검증..."
  VALIDATED_MODELS=""
  SKIPPED=0
  while IFS='|' read -r mid mname mfree; do
    [ -z "$mid" ] && continue
    if echo "$mid" | grep -q '/'; then
      # 이미 full ID — 직접 확인
      if echo "$OPENCLAW_MODELS_CACHE" | grep -qE "^${mid} "; then
        VALIDATED_MODELS="${VALIDATED_MODELS}${mid}|${mname}|${mfree}"$'\n'
      else
        echo "  SKIP: $mname ($mid) — openclaw에 미등록"
        SKIPPED=$((SKIPPED + 1))
      fi
    else
      # short ID — suffix 매칭
      if echo "$OPENCLAW_MODELS_CACHE" | grep -qE "/${mid} "; then
        VALIDATED_MODELS="${VALIDATED_MODELS}${mid}|${mname}|${mfree}"$'\n'
      else
        echo "  SKIP: $mname ($mid) — openclaw에 미등록"
        SKIPPED=$((SKIPPED + 1))
      fi
    fi
  done <<< "$MODELS"
  MODELS="$VALIDATED_MODELS"
  if [ "$SKIPPED" -gt 0 ]; then
    echo "  ${SKIPPED}개 모델 건너뜀 (openclaw 미등록)"
  fi
  echo ""
else
  # 단일 모델 — resolve-model.sh로 검증 (실패 시 즉시 exit)
  source "$SCRIPT_DIR/resolve-model.sh" "$MODEL_ID"
  MODEL_NAME=$(python3 -c "
import json
with open('$MODELS_FILE') as f:
    data = json.load(f)
for m in data['models']:
    if m['id'] == '$MODEL_ID':
        print(m['name'])
        break
else:
    print('$MODEL_ID')
" 2>/dev/null)
  MODELS="${MODEL_ID}|${MODEL_NAME}|0"
fi

# ── 헤더 출력 ──
echo "========================================="
echo "  OpenClaw 벤치마크 실행"
echo "  시각: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "  벤치마크: $BENCH"
echo "  반복: ${RUNS}회"
[ -n "$DRY_RUN" ] && echo "  모드: DRY RUN"
echo "========================================="
echo ""

TOTAL_MODELS=0
TOTAL_SUCCESS=0
TOTAL_FAIL=0
START_ALL=$(date +%s)

while IFS='|' read -r model_id model_name free_flag; do
  [ -z "$model_id" ] && continue
  TOTAL_MODELS=$((TOTAL_MODELS + 1))

  # --free-only 필터
  if [ -n "$FREE_ONLY" ] && [ "$free_flag" != "1" ]; then
    echo "SKIP (유료): $model_name"
    continue
  fi

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "모델: $model_name ($model_id)"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  MODEL_SUCCESS=0
  MODEL_FAIL=0

  # ── PinchBench ──
  if [ "$BENCH" = "all" ] || [ "$BENCH" = "pb" ]; then
    for run_i in $(seq 1 "$RUNS"); do
      echo ""
      echo "[PinchBench $run_i/$RUNS] $model_name"
      if bash "$SCRIPT_DIR/run-pinchbench.sh" "$model_id" $DRY_RUN; then
        MODEL_SUCCESS=$((MODEL_SUCCESS + 1))
        echo "  => PinchBench $run_i/$RUNS 성공"
      else
        EXIT_CODE=$?
        MODEL_FAIL=$((MODEL_FAIL + 1))
        echo "  => PinchBench $run_i/$RUNS 실패 (exit $EXIT_CODE)"
        echo "     로그: $REPO_ROOT/results/raw/pinchbench/ 에서 최신 .log 파일 확인"
      fi
    done
  fi

  # ── ClawBench-KO ──
  if [ "$BENCH" = "all" ] || [ "$BENCH" = "ko" ]; then
    for run_i in $(seq 1 "$RUNS"); do
      echo ""
      echo "[ClawBench-KO $run_i/$RUNS] $model_name"
      if bash "$SCRIPT_DIR/run-claw-bench-ko.sh" "$model_id" --runs 1 $DRY_RUN; then
        MODEL_SUCCESS=$((MODEL_SUCCESS + 1))
        echo "  => ClawBench-KO $run_i/$RUNS 성공"
      else
        EXIT_CODE=$?
        MODEL_FAIL=$((MODEL_FAIL + 1))
        echo "  => ClawBench-KO $run_i/$RUNS 실패 (exit $EXIT_CODE)"
        echo "     로그: $REPO_ROOT/results/raw/korean/ 에서 최신 .log 파일 확인"
      fi
    done
  fi

  TOTAL_SUCCESS=$((TOTAL_SUCCESS + MODEL_SUCCESS))
  TOTAL_FAIL=$((TOTAL_FAIL + MODEL_FAIL))
  echo ""
  echo "  모델 소계: 성공 $MODEL_SUCCESS / 실패 $MODEL_FAIL"

done <<< "$MODELS"

END_ALL=$(date +%s)
ELAPSED=$((END_ALL - START_ALL))

echo ""
echo "========================================="
echo "  전체 실행 완료"
echo "  모델: ${TOTAL_MODELS}개"
echo "  성공: ${TOTAL_SUCCESS} / 실패: ${TOTAL_FAIL}"
echo "  소요: ${ELAPSED}초 ($((ELAPSED / 60))분 $((ELAPSED % 60))초)"
echo "========================================="

# ── normalize.py 호출 ──
if [ -z "$DRY_RUN" ] && [ -z "$NO_NORMALIZE" ] && [ "$TOTAL_SUCCESS" -gt 0 ]; then
  echo ""
  echo "=== normalize.py: leaderboard.json 갱신 ==="
  # PinchBench 태스크 정의 디렉토리 (프롬프트 추출용)
  PB_TASKS_DIR="${HOME}/pinchbench-skill/tasks"
  PB_TASKS_ARG=""
  if [ -d "$PB_TASKS_DIR" ]; then
    PB_TASKS_ARG="--pinchbench-tasks $PB_TASKS_DIR"
  fi
  python3 "$REPO_ROOT/server/python/normalize.py" --repo-root "$REPO_ROOT" $PB_TASKS_ARG
fi

# ── 다음 단계 안내 ──
if [ "$TOTAL_SUCCESS" -gt 0 ] && [ -z "$DRY_RUN" ]; then
  echo ""
  echo "다음 단계:"
  echo "  배포: bash $SCRIPT_DIR/deploy-results.sh"
fi
