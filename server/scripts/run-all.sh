#!/usr/bin/env bash
# run-all.sh — 전체 모델 벤치마크 오케스트레이터
# models.json에서 모델 목록을 읽어 순서대로 PinchBench를 실행한다.
# 실행 순서: 무료 모델 먼저 → 유료 모델 (예산 전략)
# 사용법: bash run-all.sh [--dry-run] [--free-only]
set -euo pipefail

DRY_RUN=""
FREE_ONLY=""
for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY_RUN="--dry-run" ;;
    --free-only) FREE_ONLY="true" ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT_DIR="$REPO_ROOT/server/scripts"
MODELS_FILE="$REPO_ROOT/server/config/models.json"

if [ ! -f "$MODELS_FILE" ]; then
  echo "ERROR: $MODELS_FILE 없음"
  exit 1
fi

echo "========================================="
echo "  OpenClaw 벤치마크 전체 실행"
echo "  시각: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
[ -n "$DRY_RUN" ] && echo "  모드: DRY RUN"
[ -n "$FREE_ONLY" ] && echo "  필터: 무료 모델만"
echo "========================================="
echo ""

# ── models.json 파싱: 무료 먼저, 유료 나중 ──
MODELS=$(python3 -c "
import json
with open('$MODELS_FILE') as f:
    data = json.load(f)
models = data['models']
# 무료 모델 먼저 정렬
free = [m for m in models if m['free']]
paid = [m for m in models if not m['free']]
ordered = free + paid
for m in ordered:
    tag = 'FREE' if m['free'] else f'\${m[\"input_price_per_1m\"]:.2f}/1M'
    print(f'{m[\"id\"]}|{m[\"name\"]}|{tag}')
")

TOTAL=0
SUCCESS=0
SKIP=0
FAIL=0

while IFS='|' read -r model_id model_name cost_tag; do
  TOTAL=$((TOTAL + 1))

  # --free-only 필터
  if [ -n "$FREE_ONLY" ] && [ "$cost_tag" != "FREE" ]; then
    echo "[$TOTAL] SKIP (유료): $model_name ($model_id)"
    SKIP=$((SKIP + 1))
    continue
  fi

  echo ""
  echo "───────────────────────────────────────"
  echo "[$TOTAL] $model_name"
  echo "  ID: $model_id"
  echo "  비용: $cost_tag"
  echo "───────────────────────────────────────"

  if bash "$SCRIPT_DIR/run-pinchbench.sh" "$model_id" $DRY_RUN; then
    SUCCESS=$((SUCCESS + 1))
    echo "  => 성공"
  else
    FAIL=$((FAIL + 1))
    echo "  => 실패 (계속 진행)"
  fi

done <<< "$MODELS"

echo ""
echo "========================================="
echo "  실행 완료"
echo "  전체: $TOTAL / 성공: $SUCCESS / 건너뜀: $SKIP / 실패: $FAIL"
echo "========================================="
echo ""

# ── normalize + deploy 제안 ──
if [ "$SUCCESS" -gt 0 ] && [ -z "$DRY_RUN" ]; then
  echo "다음 단계:"
  echo "  1. 결과 정규화: python3 $REPO_ROOT/server/python/normalize.py"
  echo "  2. 배포: bash $SCRIPT_DIR/deploy-results.sh"
fi
