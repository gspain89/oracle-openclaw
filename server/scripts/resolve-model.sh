#!/usr/bin/env bash
# resolve-model.sh — 모델 ID를 OpenClaw full ID로 해석
#
# 사용법: source resolve-model.sh <model_id>
# 결과:  OPENCLAW_MODEL_ID 환경변수에 해석된 full ID 설정
#
# 동작:
#   1. model_id에 이미 '/'가 있으면 그대로 사용
#   2. 없으면 `openclaw models list` 출력에서 suffix 매칭
#   3. 못 찾으면 에러 메시지 출력 후 exit 1

_MODEL_ARG="${1:-}"

if [ -z "$_MODEL_ARG" ]; then
  echo "ERROR: resolve-model.sh에 모델 ID가 전달되지 않았습니다."
  exit 1
fi

# nvm 환경 로드 (openclaw CLI 필요)
if ! command -v openclaw &>/dev/null; then
  export NVM_DIR="$HOME/.nvm"
  [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh" 2>/dev/null || true
fi

if ! command -v openclaw &>/dev/null; then
  echo "ERROR: openclaw CLI를 찾을 수 없습니다"
  exit 1
fi

if echo "$_MODEL_ARG" | grep -q '/'; then
  # 이미 provider/model 형태
  OPENCLAW_MODEL_ID="$_MODEL_ARG"
else
  # openclaw models list에서 suffix 매칭
  OPENCLAW_MODEL_ID=$(openclaw models list 2>/dev/null | grep -E "/$_MODEL_ARG " | head -1 | awk '{print $1}')
  if [ -z "$OPENCLAW_MODEL_ID" ]; then
    echo "ERROR: openclaw models list에서 '$_MODEL_ARG' 모델을 찾을 수 없습니다."
    echo ""
    echo "  사용 가능한 모델:"
    openclaw models list 2>/dev/null | grep -E '^\S+/\S+' | awk '{print "    " $1}'
    echo ""
    echo "  전체 ID를 직접 지정할 수도 있습니다:"
    echo "    예: azure-openai/gpt-5.3-chat"
    exit 1
  fi
fi

export OPENCLAW_MODEL_ID
