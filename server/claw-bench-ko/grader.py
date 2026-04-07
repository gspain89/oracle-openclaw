#!/usr/bin/env python3
"""claw-bench-ko grader — 채점 엔진

채점 유형:
  automated  — 파일 존재, JSON 유효성, 필드 값 일치 등 자동 체크
  llm_judge  — judge 모델이 루브릭 기반으로 채점 (0~100점)
  hybrid     — automated + judge 가중 결합

의존성: Python 3.8+ 표준 라이브러리만 사용
"""

import csv
import io
import json
import re
import subprocess
import time
import uuid
from pathlib import Path


# ── judge 에이전트 관리 ──

_judge_agent_created = {}


def _ensure_judge_agent(judge_model: str) -> str:
    """judge 모델용 OpenClaw 에이전트 생성 (lazy — 첫 호출 시에만)"""
    if judge_model in _judge_agent_created:
        return _judge_agent_created[judge_model]

    slug = judge_model.replace("/", "-").replace(":", "-").replace(".", "-")
    agent_id = f"clawbench-judge-{slug}"

    result = subprocess.run(
        ["openclaw", "agents", "list"],
        capture_output=True, text=True, timeout=30
    )
    if agent_id not in result.stdout:
        workspace = Path(f"/tmp/claw-bench-ko/judge_{slug}")
        workspace.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["openclaw", "agents", "add", agent_id,
             "--model", judge_model,
             "--workspace", str(workspace),
             "--non-interactive"],
            capture_output=True, text=True, timeout=30
        )
        print(f"    judge 에이전트 생성: {agent_id}")

    _judge_agent_created[judge_model] = agent_id
    return agent_id


def _run_judge(judge_model: str, prompt: str, timeout: int = 180) -> str:
    """judge 에이전트에 채점 요청을 보내고 응답 텍스트 반환"""
    agent_id = _ensure_judge_agent(judge_model)
    session_id = f"judge_{uuid.uuid4().hex[:8]}"

    result = subprocess.run(
        ["openclaw", "agent",
         "--agent", agent_id,
         "--session-id", session_id,
         "--message", prompt],
        capture_output=True, text=True, timeout=timeout
    )
    return result.stdout


# ── automated 체크 함수들 ──

def _read_file(workspace: Path, rel_path: str) -> str | None:
    fpath = workspace / rel_path
    if not fpath.exists():
        return None
    try:
        return fpath.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return fpath.read_text(encoding="euc-kr")
        except Exception:
            return None


def _load_json(workspace: Path, rel_path: str):
    content = _read_file(workspace, rel_path)
    if content is None:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def _resolve_json_field(data, field: str):
    """JSON 필드 경로를 해석하여 값 반환.
    지원 형식: "key", "[0].key", "items[2].name", "total.supply_amount"
    """
    parts = re.findall(r'\[(\d+)\]|\.?([^.\[\]]+)', field)
    current = data
    for bracket_idx, key in parts:
        if bracket_idx:
            idx = int(bracket_idx)
            if not isinstance(current, list) or idx >= len(current):
                return _MISSING
            current = current[idx]
        elif key:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return _MISSING
    return current


class _MissingSentinel:
    """필드가 존재하지 않음을 나타내는 센티넬"""
    pass

_MISSING = _MissingSentinel()


def _check_file_exists(workspace: Path, check: dict) -> bool:
    return (workspace / check["path"]).exists()


def _check_json_valid(workspace: Path, check: dict) -> bool:
    return _load_json(workspace, check["path"]) is not None


def _check_json_array_length(workspace: Path, check: dict) -> bool:
    data = _load_json(workspace, check["path"])
    if not isinstance(data, list):
        return False
    return len(data) == check["expected"]


def _check_json_array_min_length(workspace: Path, check: dict) -> bool:
    data = _load_json(workspace, check["path"])
    field = check.get("field")
    if field:
        data = _resolve_json_field(data, field)
    if not isinstance(data, list):
        return False
    return len(data) >= check["min"]


def _check_json_field_equals(workspace: Path, check: dict) -> bool:
    data = _load_json(workspace, check["path"])
    if data is None:
        return False
    value = _resolve_json_field(data, check["field"])
    if isinstance(value, _MissingSentinel):
        return False
    expected = check["expected"]
    # 숫자 비교 시 타입 유연성 (int vs float)
    if isinstance(expected, (int, float)) and isinstance(value, (int, float)):
        return abs(value - expected) < 0.01
    return value == expected


def _check_json_field_exists(workspace: Path, check: dict) -> bool:
    data = _load_json(workspace, check["path"])
    if data is None:
        return False
    value = _resolve_json_field(data, check["field"])
    return not isinstance(value, _MissingSentinel)


def _check_json_has_fields(workspace: Path, check: dict) -> bool:
    """배열의 첫 번째 요소가 필수 필드를 모두 갖고 있는지 확인"""
    data = _load_json(workspace, check["path"])
    if not isinstance(data, list) or len(data) == 0:
        return False
    first = data[0]
    if not isinstance(first, dict):
        return False
    return all(f in first for f in check["fields"])


def _check_json_items_have_fields(workspace: Path, check: dict) -> bool:
    """배열의 모든 요소가 필수 필드를 갖고 있는지 확인"""
    data = _load_json(workspace, check["path"])
    if data is None:
        return False
    items = _resolve_json_field(data, check["field"])
    if not isinstance(items, list) or len(items) == 0:
        return False
    required = check["required_fields"]
    return all(
        isinstance(item, dict) and all(f in item for f in required)
        for item in items
    )


def _check_encoding_is(workspace: Path, check: dict) -> bool:
    fpath = workspace / check["path"]
    if not fpath.exists():
        return False
    expected = check["expected"].lower()
    raw = fpath.read_bytes()
    if expected == "utf-8":
        try:
            raw.decode("utf-8")
            return True
        except UnicodeDecodeError:
            return False
    return False


def _check_csv_header_equals(workspace: Path, check: dict) -> bool:
    content = _read_file(workspace, check["path"])
    if content is None:
        return False
    first_line = content.strip().split("\n")[0].strip()
    return first_line == check["expected"]


def _check_csv_row_count(workspace: Path, check: dict) -> bool:
    content = _read_file(workspace, check["path"])
    if content is None:
        return False
    lines = [l for l in content.strip().split("\n") if l.strip()]
    # 헤더 제외
    return len(lines) - 1 == check["expected"]


def _check_csv_field_matches_pattern(workspace: Path, check: dict) -> bool:
    content = _read_file(workspace, check["path"])
    if content is None:
        return False
    reader = csv.DictReader(io.StringIO(content))
    col = check["column"]
    pattern = re.compile(check["pattern"])
    for row in reader:
        val = row.get(col, "")
        if not pattern.match(val):
            return False
    return True


def _check_csv_field_is_integer(workspace: Path, check: dict) -> bool:
    content = _read_file(workspace, check["path"])
    if content is None:
        return False
    reader = csv.DictReader(io.StringIO(content))
    col = check["column"]
    for row in reader:
        val = row.get(col, "").strip()
        if val == "" or val == "0":
            continue
        try:
            int(val)
        except ValueError:
            return False
    return True


# 체크 타입 → 함수 매핑
CHECK_HANDLERS = {
    "file_exists": _check_file_exists,
    "json_valid": _check_json_valid,
    "json_array_length": _check_json_array_length,
    "json_array_min_length": _check_json_array_min_length,
    "json_field_equals": _check_json_field_equals,
    "json_field_exists": _check_json_field_exists,
    "json_has_fields": _check_json_has_fields,
    "json_items_have_fields": _check_json_items_have_fields,
    "encoding_is": _check_encoding_is,
    "csv_header_equals": _check_csv_header_equals,
    "csv_row_count": _check_csv_row_count,
    "csv_field_matches_pattern": _check_csv_field_matches_pattern,
    "csv_field_is_integer": _check_csv_field_is_integer,
}


# ── 채점 메인 로직 ──

def grade_automated(task: dict, workspace: Path) -> dict:
    """automated 체크 실행. 통과율을 0.0~1.0 점수로 반환."""
    auto_config = task["grading"]["automated"]
    checks = auto_config["checks"]
    results = []

    for check in checks:
        handler = CHECK_HANDLERS.get(check["type"])
        if handler is None:
            results.append({"check": check, "passed": False,
                            "error": f"unknown check type: {check['type']}"})
            continue
        try:
            passed = handler(workspace, check)
        except Exception as e:
            passed = False
            results.append({"check": check, "passed": False, "error": str(e)})
            continue
        results.append({"check": check, "passed": passed})

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    score = passed / total if total > 0 else 0.0

    # 실패한 체크 로그 출력
    failed = [r for r in results if not r["passed"]]
    if failed:
        print(f"    채점 상세: {passed}/{total} 통과")
        for r in failed:
            c = r["check"]
            err = r.get("error", "")
            desc = c.get("type", "?")
            if "path" in c:
                desc += f" [{c['path']}]"
            if "field" in c:
                desc += f" .{c['field']}"
            if "expected" in c:
                desc += f" == {c['expected']}"
            if err:
                desc += f" (err: {err})"
            print(f"      ✗ {desc}")

    return {
        "score": round(score, 4),
        "passed": passed,
        "total": total,
        "details": results
    }


def grade_llm_judge(task: dict, workspace: Path, transcript: str,
                    judge_model: str) -> dict:
    """judge 모델로 채점. 0.0~1.0 점수로 반환."""
    judge_config = task["grading"]["judge"]
    rubric = judge_config["rubric"]

    # 워크스페이스 출력 파일 내용 수집
    workspace_content = ""
    for item in sorted(workspace.iterdir()):
        if item.is_file():
            try:
                content = item.read_text(encoding="utf-8")
                # 너무 긴 파일은 잘라냄 (judge 컨텍스트 절약)
                if len(content) > 5000:
                    content = content[:5000] + "\n... (이하 생략)"
                workspace_content += f"\n--- {item.name} ---\n{content}\n"
            except Exception:
                workspace_content += f"\n--- {item.name} --- (읽기 실패)\n"

    judge_prompt = f"""당신은 한국어 에이전트 벤치마크의 채점관입니다. 아래 태스크의 결과물을 채점하세요.

## 태스크
{task['name']} ({task['id']})

## 워크스페이스 출력 파일 (채점 대상)
{workspace_content if workspace_content else '(파일 없음)'}

주의: 아래 에이전트 대화 로그는 참고용입니다. 채점은 반드시 위 워크스페이스 파일 내용을 기준으로 하세요. 대화 로그에 타임아웃/오류 메시지가 있더라도 워크스페이스 파일이 정상이면 파일 기준으로 채점하세요.

## 에이전트 대화 로그 (참고용)
{transcript[:2000] if transcript else '(없음)'}

## 채점 루브릭
{rubric}

## 응답 형식
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트를 추가하지 마세요.

```json
{{
  "score": <0~100 정수>,
  "breakdown": {{
    "<기준1>": <0~해당 기준 만점>,
    "<기준2>": <0~해당 기준 만점>
  }},
  "feedback": "<1~2문장 한국어 피드백>"
}}
```"""

    print(f"    judge 호출 중 ({judge_model})...")
    start = time.time()
    response = _run_judge(judge_model, judge_prompt)
    elapsed = time.time() - start
    print(f"    judge 응답 ({elapsed:.1f}초)")

    # JSON 파싱 (응답에서 JSON 블록 추출)
    score_data = _parse_judge_response(response)

    return {
        "score": round(score_data.get("score", 0) / 100, 4),
        "raw_score": score_data.get("score", 0),
        "max_score": 100,
        "breakdown": score_data.get("breakdown", {}),
        "feedback": score_data.get("feedback", ""),
        "judge_model": judge_model,
        "judge_duration_seconds": round(elapsed, 1)
    }


def _parse_judge_response(response: str) -> dict:
    """judge 응답에서 JSON 추출. 실패 시 점수 0 반환."""
    if not response:
        print("    ⚠️ judge 응답 비어있음 — API 에러 또는 타임아웃 가능성")
        return {"score": 0, "feedback": "judge 응답 없음"}

    # ```json ... ``` 블록 추출 시도
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response,
                           re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # 중괄호 블록 직접 추출
    brace_match = re.search(r'\{[^{}]*"score"\s*:\s*\d+[^{}]*\}', response,
                            re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    # 숫자만이라도 추출
    num_match = re.search(r'"score"\s*:\s*(\d+)', response)
    if num_match:
        return {"score": int(num_match.group(1)),
                "feedback": "JSON 파싱 실패 — 점수만 추출"}

    print(f"    ⚠️ judge 응답 파싱 실패 — 응답 앞 300자: {response[:300]}")
    return {"score": 0, "feedback": f"judge 응답 파싱 실패: {response[:200]}"}


def grade_hybrid(task: dict, workspace: Path, transcript: str,
                 judge_model: str) -> dict:
    """automated + judge 가중 결합."""
    auto_result = grade_automated(task, workspace)
    judge_result = grade_llm_judge(task, workspace, transcript, judge_model)

    auto_weight = task["grading"]["automated"].get("weight", 0.5)
    judge_weight = task["grading"]["judge"].get("weight", 0.5)

    combined = (auto_result["score"] * auto_weight +
                judge_result["score"] * judge_weight)

    return {
        "score": round(combined, 4),
        "automated": auto_result,
        "judge": judge_result,
        "weights": {"automated": auto_weight, "judge": judge_weight}
    }


def grade_task(task: dict, workspace: Path, transcript: str,
               judge_model: str) -> dict:
    """태스크 유형에 따라 적절한 채점 방식 호출"""
    grading_type = task["grading_type"]

    if grading_type == "automated":
        return grade_automated(task, workspace)
    elif grading_type == "llm_judge":
        return grade_llm_judge(task, workspace, transcript, judge_model)
    elif grading_type == "hybrid":
        return grade_hybrid(task, workspace, transcript, judge_model)
    else:
        return {"score": 0.0, "error": f"unknown grading_type: {grading_type}"}
