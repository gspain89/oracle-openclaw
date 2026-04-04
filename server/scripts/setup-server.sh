#!/usr/bin/env bash
# setup-server.sh — 서버 1회 초기화
# Oracle ARM 인스턴스에서 벤치마크 환경을 세팅한다.
# 사용법: bash setup-server.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PINCHBENCH_DIR="$HOME/pinchbench-skill"
RESULTS_RAW="$REPO_ROOT/results/raw"

echo "=== OpenClaw Benchmark 서버 초기화 ==="
echo "시각: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "REPO_ROOT: $REPO_ROOT"

# ── 1) 기본 도구 확인 ──
echo ""
echo "[1/4] 필수 도구 확인..."

check_cmd() {
  if ! command -v "$1" &>/dev/null; then
    echo "  ERROR: $1 이 설치되어 있지 않습니다."
    return 1
  fi
  echo "  OK: $1 ($($1 --version 2>/dev/null | head -1))"
}

check_cmd node
check_cmd python3
check_cmd git
check_cmd openclaw || echo "  WARN: openclaw CLI 미발견 — 설치 필요 (curl -fsSL https://openclaw.ai/install.sh | bash)"

NODE_MAJOR=$(node -v 2>/dev/null | sed 's/v\([0-9]*\).*/\1/')
if [ "${NODE_MAJOR:-0}" -lt 22 ]; then
  echo "  WARN: Node.js v22+ 필요 (현재 v$(node -v)). nvm install 22 실행 권장"
fi

# ── 2) PinchBench clone ──
echo ""
echo "[2/4] PinchBench 설치..."

if [ -d "$PINCHBENCH_DIR" ]; then
  echo "  이미 존재: $PINCHBENCH_DIR"
  cd "$PINCHBENCH_DIR" && git pull --ff-only 2>/dev/null || echo "  (pull 실패 — 무시하고 계속)"
else
  echo "  클론 중: https://github.com/pinchbench/skill"
  git clone --depth 1 https://github.com/pinchbench/skill "$PINCHBENCH_DIR"
fi

# PinchBench 의존성 설치
if [ -f "$PINCHBENCH_DIR/package.json" ]; then
  echo "  npm install..."
  cd "$PINCHBENCH_DIR" && npm install --production 2>&1 | tail -1
fi

# ── 3) 결과 디렉토리 생성 ──
echo ""
echo "[3/4] 결과 디렉토리 생성..."

mkdir -p "$RESULTS_RAW/pinchbench"
mkdir -p "$RESULTS_RAW/agentbench"
mkdir -p "$RESULTS_RAW/korean"
mkdir -p "$REPO_ROOT/results/normalized"
echo "  OK: $RESULTS_RAW/{pinchbench,agentbench,korean}"

# ── 4) OpenClaw 설정 확인 ──
echo ""
echo "[4/4] OpenClaw 설정 확인..."

OPENCLAW_CONFIG="$HOME/.openclaw/openclaw.json"
if [ -f "$OPENCLAW_CONFIG" ]; then
  echo "  설정 파일: $OPENCLAW_CONFIG"
  # 등록된 auth provider 표시
  python3 -c "
import json, sys
with open('$OPENCLAW_CONFIG') as f:
    cfg = json.load(f)
providers = cfg.get('auth', {}).get('providers', {})
for name in providers:
    masked = providers[name].get('apiKey', '???')[:8] + '...'
    print(f'  Auth: {name} ({masked})')
" 2>/dev/null || echo "  (설정 파싱 실패)"
else
  echo "  WARN: $OPENCLAW_CONFIG 없음 — openclaw setup 실행 필요"
fi

echo ""
echo "=== 초기화 완료 ==="
echo ""
echo "다음 단계:"
echo "  1. 무료 모델로 테스트: bash server/scripts/run-pinchbench.sh arcee-ai/trinity-large-preview:free"
echo "  2. 전체 실행: bash server/scripts/run-all.sh"
