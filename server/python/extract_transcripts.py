#!/usr/bin/env python3
"""extract_transcripts.py — PinchBench 실행 후 OpenClaw 세션에서 transcript 추출

PinchBench는 에이전트 응답/도구 사용 정보를 results.json에 저장하지 않는다.
이 스크립트는 OpenClaw 세션 파일(~/.openclaw/agents/bench-*/sessions/*.jsonl)에서
각 태스크별 에이전트 응답과 도구 호출 목록을 추출하여 results.json에 병합한다.

사용법:
  # PinchBench 실행 직후 (세션 파일 존재할 때):
  python3 extract_transcripts.py --result results/raw/pinchbench/model_20260407.json

  # 에이전트 ID 직접 지정:
  python3 extract_transcripts.py --result foo.json --agent-id bench-openrouter-nvidia-nemotron

의존성: 표준 라이브러리만 (pip 의존성 0)
"""

import argparse
import json
import re
import sys
from pathlib import Path

OPENCLAW_DIR = Path.home() / ".openclaw" / "agents"
# 에이전트 응답 최대 길이 (자)
MAX_RESPONSE_LEN = 5000


def find_agent_dir(model_raw: str) -> Path | None:
    """모델 ID에서 PinchBench 에이전트 디렉토리를 추정"""
    if not OPENCLAW_DIR.exists():
        return None

    # PinchBench 에이전트 ID 형식: bench-{slugified_model}
    slug = re.sub(r"[/:.]", "-", model_raw)
    agent_id = f"bench-{slug}"
    agent_dir = OPENCLAW_DIR / agent_id
    if agent_dir.exists():
        return agent_dir

    # slug 변형 시도 (: → - 등 다양한 slugify 방식)
    for d in OPENCLAW_DIR.iterdir():
        if d.is_dir() and d.name.startswith("bench-") and not d.name.startswith("bench-judge"):
            if slug.replace("-", "") in d.name.replace("-", ""):
                return d

    return None


def parse_session_file(session_path: Path) -> dict:
    """단일 세션 .jsonl 파일에서 에이전트 응답과 도구 호출 추출

    OpenClaw v3 세션 포맷은 각 이벤트를 `{type, ..., message: {role, content}}` 로
    감싸므로 `entry.message.role`로 접근해야 한다. v2 이하(평면 role/content)도
    하위 호환 처리.

    반환: {
        "agent_response": str,
        "tool_calls": [str],
        "tool_details": [{"tool", "input_summary"}],
        "turn_count": int,
    }
    """
    tool_calls = []
    tool_details = []
    agent_texts = []
    turn_count = 0

    def _consume_content(content):
        """assistant content를 받아 텍스트/toolCall 블록 처리

        OpenClaw 세션은 block type `toolCall` (camelCase)에 `name`+`arguments`를 사용.
        Anthropic 포맷 `tool_use`(name+input)도 함께 지원.
        """
        if isinstance(content, str) and content.strip():
            agent_texts.append(content.strip())
            return
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and block.get("text"):
                agent_texts.append(block["text"].strip())
            elif btype in ("toolCall", "tool_use"):
                tool_name = block.get("name", "unknown")
                # OpenClaw: arguments, Anthropic: input
                tool_input = block.get("arguments") or block.get("input") or {}
                tool_calls.append(tool_name)
                input_str = json.dumps(tool_input, ensure_ascii=False)
                if len(input_str) > 200:
                    input_str = input_str[:200] + "..."
                tool_details.append({
                    "tool": tool_name,
                    "input_summary": input_str,
                })

    try:
        with open(session_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # OpenClaw v3: {"type": "message", "message": {"role", "content"}}
                # 하위 호환 v2: {"role", "content"} 평면 구조
                msg = entry.get("message") if entry.get("type") == "message" else entry
                if not isinstance(msg, dict):
                    msg = {}

                role = msg.get("role", "")

                if role == "assistant":
                    turn_count += 1
                    _consume_content(msg.get("content", ""))

                # 구 OpenAI chat 포맷 (tool_calls 필드가 최상위/msg에)
                openai_tool_calls = msg.get("tool_calls") or entry.get("tool_calls")
                if openai_tool_calls:
                    for tc in openai_tool_calls:
                        name = tc.get("function", {}).get("name", tc.get("name", "unknown"))
                        tool_calls.append(name)
                        args = tc.get("function", {}).get("arguments", tc.get("input", ""))
                        if isinstance(args, str) and len(args) > 200:
                            args = args[:200] + "..."
                        tool_details.append({
                            "tool": name,
                            "input_summary": str(args)[:200],
                        })

    except Exception as e:
        return {"error": str(e)}

    # 최종 응답: 마지막 텍스트 블록 (또는 전체 연결)
    agent_response = agent_texts[-1] if agent_texts else ""
    if len(agent_response) > MAX_RESPONSE_LEN:
        agent_response = agent_response[:MAX_RESPONSE_LEN] + "\n... (truncated)"

    # 도구 목록 중복 제거하되 순서 유지
    seen = set()
    unique_tools = []
    for t in tool_calls:
        if t not in seen:
            seen.add(t)
            unique_tools.append(t)

    return {
        "agent_response": agent_response,
        "tool_calls": unique_tools,
        "tool_details": tool_details[:20],  # 최대 20개
        "turn_count": turn_count,
    }


def match_session_to_task(session_name: str, task_id: str) -> bool:
    """세션 파일명이 해당 태스크에 속하는지 판별

    PinchBench 세션 ID 형식: {task_id}_{timestamp}
    """
    return session_name.startswith(task_id)


def extract_transcripts(result_path: Path, agent_id: str | None = None,
                        task_sessions_dir: Path | None = None) -> dict:
    """results.json에서 태스크 ID를 읽고 세션 파일에서 transcript 추출

    세션 소스 2가지:
      1. task_sessions_dir: ClawBench-KO 방식. {task_sessions_dir}/<task_id>/session/*.jsonl
         (runner.py가 clear_agent_sessions 직전에 복사해둔 태스크별 세션)
      2. agent_id 또는 자동 탐색: PinchBench 방식. ~/.openclaw/agents/{agent_id}/sessions/*.jsonl
         (세션 파일명 prefix로 태스크 매칭)

    반환: {task_id: {agent_response, tool_calls, tool_details, turn_count}}
    """
    with open(result_path, encoding="utf-8") as f:
        data = json.load(f)

    # 태스크 ID 목록 수집 (공통)
    task_ids = set()
    for t in data.get("tasks", []):
        tid = t.get("task_id") or t.get("frontmatter", {}).get("id", "")
        if tid:
            task_ids.add(tid)

    transcripts = {}

    # Mode 1: 태스크별 세션 디렉토리 (ClawBench-KO)
    if task_sessions_dir:
        base = Path(task_sessions_dir)
        if not base.exists():
            print(f"태스크 세션 디렉토리 없음: {base}", file=sys.stderr)
            return {}
        for tid in task_ids:
            task_session_dir = base / tid / "session"
            if not task_session_dir.exists():
                continue
            session_files = sorted(task_session_dir.glob("*.jsonl"))
            if not session_files:
                continue
            # 태스크당 파일이 여러개면 모두 합쳐서 파싱
            merged = {"agent_response": "", "tool_calls": [], "tool_details": [], "turn_count": 0}
            texts = []
            for sf in session_files:
                parsed = parse_session_file(sf)
                if parsed.get("error"):
                    continue
                if parsed.get("agent_response"):
                    texts.append(parsed["agent_response"])
                merged["tool_calls"].extend(parsed.get("tool_calls", []))
                merged["tool_details"].extend(parsed.get("tool_details", []))
                merged["turn_count"] += parsed.get("turn_count", 0)
            # 중복 tool_calls 제거 (순서 유지)
            seen = set()
            merged["tool_calls"] = [t for t in merged["tool_calls"]
                                   if not (t in seen or seen.add(t))]
            merged["agent_response"] = "\n\n---\n\n".join(texts)[:MAX_RESPONSE_LEN]
            transcripts[tid] = merged
        return transcripts

    # Mode 2: agent_id 기반 (PinchBench)
    model_raw = data.get("model", data.get("summary", {}).get("model", ""))
    if agent_id:
        agent_dir = OPENCLAW_DIR / agent_id
    else:
        agent_dir = find_agent_dir(model_raw)

    if not agent_dir or not agent_dir.exists():
        print(f"에이전트 디렉토리 없음: {agent_dir or '(찾을 수 없음)'}", file=sys.stderr)
        print(f"  모델 ID: {model_raw}", file=sys.stderr)
        print(f"  검색 위치: {OPENCLAW_DIR}", file=sys.stderr)
        return {}

    sessions_dir = agent_dir / "sessions"
    if not sessions_dir.exists():
        print(f"세션 디렉토리 없음: {sessions_dir}", file=sys.stderr)
        return {}

    session_files = sorted(sessions_dir.glob("*.jsonl"))
    for sf in session_files:
        session_name = sf.stem
        for tid in task_ids:
            if match_session_to_task(session_name, tid):
                parsed = parse_session_file(sf)
                if parsed and not parsed.get("error"):
                    transcripts[tid] = parsed
                break

    return transcripts


def merge_into_result(result_path: Path, transcripts: dict):
    """추출한 transcript를 results.json의 각 태스크에 병합"""
    with open(result_path, encoding="utf-8") as f:
        data = json.load(f)

    merged = 0
    for t in data.get("tasks", []):
        tid = t.get("task_id") or t.get("frontmatter", {}).get("id", "")
        if tid in transcripts:
            tr = transcripts[tid]
            t["agent_response"] = tr.get("agent_response", "")
            t["tool_calls"] = tr.get("tool_calls", [])
            t["tool_details"] = tr.get("tool_details", [])
            t["turn_count"] = tr.get("turn_count", 0)
            merged += 1

    if merged > 0:
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  {merged}/{len(data.get('tasks', []))} 태스크에 transcript 병합 완료")
    else:
        print("  병합할 transcript 없음", file=sys.stderr)

    return merged


def main():
    parser = argparse.ArgumentParser(description="벤치마크 transcript 추출기 (PinchBench/ClawBench-KO 공용)")
    parser.add_argument("--result", required=True, help="results.json 경로")
    parser.add_argument("--agent-id", default=None,
                        help="PinchBench 방식: OpenClaw 에이전트 ID (미지정 시 자동 탐색)")
    parser.add_argument("--task-sessions-dir", default=None,
                        help="ClawBench-KO 방식: {dir}/<task_id>/session/*.jsonl 스캔")
    parser.add_argument("--dry-run", action="store_true", help="병합 없이 출력만")
    args = parser.parse_args()

    result_path = Path(args.result)
    if not result_path.exists():
        print(f"ERROR: 결과 파일 없음 — {result_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[1/2] Transcript 추출: {result_path}")
    transcripts = extract_transcripts(
        result_path, args.agent_id,
        task_sessions_dir=Path(args.task_sessions_dir) if args.task_sessions_dir else None,
    )

    if not transcripts:
        print("ERROR: 추출된 transcript 없음", file=sys.stderr)
        sys.exit(1)

    print(f"  {len(transcripts)}개 태스크 transcript 추출")

    if args.dry_run:
        for tid, tr in sorted(transcripts.items()):
            tools = ", ".join(tr.get("tool_calls", [])) or "(없음)"
            resp_len = len(tr.get("agent_response", ""))
            print(f"  {tid}: tools=[{tools}], response={resp_len}자, turns={tr.get('turn_count', 0)}")
        return

    print(f"[2/2] 결과 파일에 병합")
    merge_into_result(result_path, transcripts)


if __name__ == "__main__":
    main()
