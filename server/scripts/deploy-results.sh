#!/usr/bin/env bash
# deploy-results.sh — 정규화된 결과를 GitHub에 push → Pages 자동 배포 트리거
# 사용법: bash deploy-results.sh [--dry-run]
set -euo pipefail

DRY_RUN="${1:-}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NORMALIZED="$REPO_ROOT/results/normalized"

echo "=== 결과 배포 ==="
echo "시각: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo ""

cd "$REPO_ROOT"

# ── 1) 변경사항 확인 ──
if ! git diff --quiet "$NORMALIZED/" 2>/dev/null || ! git diff --cached --quiet "$NORMALIZED/" 2>/dev/null; then
  echo "[1/3] 변경된 파일:"
  git diff --name-only "$NORMALIZED/"
  git diff --cached --name-only "$NORMALIZED/"
elif [ -n "$(git ls-files --others --exclude-standard "$NORMALIZED/")" ]; then
  echo "[1/3] 새로운 파일:"
  git ls-files --others --exclude-standard "$NORMALIZED/"
else
  echo "변경사항 없음 — 배포 건너뜀"
  exit 0
fi

# ── 2) leaderboard.json 요약 ──
echo ""
echo "[2/3] leaderboard.json 요약:"
python3 -c "
import json
with open('$NORMALIZED/leaderboard.json') as f:
    data = json.load(f)
models = data['models']
pb = sum(1 for m in models if m['scores'].get('pinchbench'))
ko = sum(1 for m in models if m['scores'].get('clawbench_ko'))
runs = data['meta'].get('total_runs', 0)
print(f'  모델: {len(models)}개')
print(f'  PinchBench: {pb}개 모델')
print(f'  ClawBench-KO: {ko}개 모델')
print(f'  총 실행: {runs}회')
print(f'  생성: {data[\"meta\"][\"generated_at\"]}')
" 2>/dev/null || echo "  (요약 불가)"

# ── 3) Git commit + push ──
echo ""
if [ "$DRY_RUN" = "--dry-run" ]; then
  echo "[3/3] DRY RUN — push하지 않음"
  echo "  git add results/normalized/"
  echo "  git commit -m 'data: update benchmark results'"
  echo "  git push origin main"
  exit 0
fi

echo "[3/3] Git push..."
git add results/normalized/
git commit -m "data: update benchmark results $(date -u '+%Y-%m-%d')" || {
  echo "  커밋할 변경사항 없음"
  exit 0
}
git push origin main

echo ""
echo "배포 완료. GitHub Actions가 Pages를 자동 빌드합니다."
echo "확인: https://github.com/gspain89/oracle-openclaw/actions"
