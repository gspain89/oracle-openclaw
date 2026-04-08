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

    반환: {
        "agent_response": str,   # 에이전트의 최종 텍스트 응답
        "tool_calls": [str],     # 사용한 도구 이름 목록
        "tool_details": [        # 도구 호출 상세 (이름 + 입력 요약)
            {"tool": "web_search", "input_summary": "AAPL stock price"},
            ...
        ],
        "turn_count": int,       # 대화 턴 수
    }
    """
    tool_calls = []
    tool_details = []
    agent_texts = []
    turn_count = 0

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

                role = entry.get("role", "")

                # 에이전트(assistant) 응답 텍스트 수집
                if role == "assistant":
                    turn_count += 1
                    content = entry.get("content", "")
                    if isinstance(content, str) and content.strip():
                        agent_texts.append(content.strip())
                    elif isinstance(content, list):
                        # content가 블록 배열인 경우 (text, tool_use 등)
                        for block in content:
                            if isinstance(block, dict):
                                if block.get("type") == "text" and block.get("text"):
                                    agent_texts.append(block["text"].strip())
                                elif block.get("type") == "tool_use":
                                    tool_name = block.get("name", "unknown")
                                    tool_input = block.get("input", {})
                                    tool_calls.append(tool_name)
                                    # 입력 요약: 첫 200자
                                    input_str = json.dumps(tool_input, ensure_ascii=False)
                                    if len(input_str) > 200:
                                        input_str = input_str[:200] + "..."
                                    tool_details.append({
                                        "tool": tool_name,
                                        "input_summary": input_str,
                                    })

                # tool_calls 필드 (구 형식)
                if "tool_calls" in entry:
                    for tc in entry["tool_calls"]:
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


def extract_transcripts(result_path: Path, agent_id: str | None = None) -> dict:
    """PinchBench results.json에서 모델 ID를 읽고 세션 파일에서 transcript 추출

    반환: {task_id: {agent_response, tool_calls, tool_details, turn_count}}
    """
    with open(result_path, encoding="utf-8") as f:
        data = json.load(f)

    model_raw = data.get("model", data.get("summary", {}).get("model", ""))

    # 에이전트 디렉토리 찾기
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

    # 태스크 ID 목록 수집
    task_ids = set()
    for t in data.get("tasks", []):
        tid = t.get("task_id") or t.get("frontmatter", {}).get("id", "")
        if tid:
            task_ids.add(tid)

    # 세션 파일 → 태스크 매핑
    transcripts = {}
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
    parser = argparse.ArgumentParser(description="PinchBench transcript 추출기")
    parser.add_argument("--result", required=True, help="PinchBench results.json 경로")
    parser.add_argument("--agent-id", default=None, help="에이전트 ID (미지정 시 자동 탐색)")
    parser.add_argument("--dry-run", action="store_true", help="병합 없이 출력만")
    args = parser.parse_args()

    result_path = Path(args.result)
    if not result_path.exists():
        print(f"ERROR: 결과 파일 없음 — {result_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[1/2] Transcript 추출: {result_path}")
    transcripts = extract_transcripts(result_path, args.agent_id)

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
