#!/usr/bin/env python3
"""pinchbench_wrapper.py — PinchBench을 `--no-judge` / `--save-artifacts-dir` 로 확장

PinchBench 원본(benchmark.py)은 judge 호출 생략 옵션과 태스크별 아티팩트 보존
훅이 없다. 이 래퍼는 runtime monkey-patch로 두 기능을 주입한다:

  --no-judge
    - llm_judge 태스크: judge 호출 생략, 점수 0 + pending_manual_review notes
    - hybrid 태스크: automated 부분만 채점, judge 부분은 pending
    - automated 태스크: 그대로 채점
  --save-artifacts-dir PATH
    - 태스크 실행 직후 워크스페이스 스냅샷/세션 jsonl/stdout/stderr 복사
    - 복사는 다음 태스크의 워크스페이스 초기화 전에 수행

사용법:
  uv run scripts/pinchbench_wrapper.py --model X [PinchBench 기존 옵션] \
      [--no-judge] [--save-artifacts-dir PATH]

이 래퍼는 `~/pinchbench-skill/scripts/` 안에 배치되어야 lib_agent/lib_grading을
import할 수 있다. run-pinchbench.sh가 실행 전 자동으로 복사한다.
"""
import shutil
import sys
from pathlib import Path

PB_ROOT = Path(__file__).resolve().parent.parent  # scripts/ 의 상위 = pinchbench-skill
if not (PB_ROOT / "scripts" / "benchmark.py").exists():
    # 원본 경로 추정 실패 시 HOME/pinchbench-skill fallback
    PB_ROOT = Path.home() / "pinchbench-skill"

sys.path.insert(0, str(PB_ROOT / "scripts"))

# ── 우리가 추가한 플래그 파싱 (PinchBench argparse로 넘어가기 전에 제거) ──
_argv = list(sys.argv)
NO_JUDGE = False
ARTIFACTS_DIR: Path | None = None

if "--no-judge" in _argv:
    _argv.remove("--no-judge")
    NO_JUDGE = True

if "--save-artifacts-dir" in _argv:
    idx = _argv.index("--save-artifacts-dir")
    if idx + 1 >= len(_argv):
        print("ERROR: --save-artifacts-dir 에 경로 인자 필요", file=sys.stderr)
        sys.exit(2)
    ARTIFACTS_DIR = Path(_argv[idx + 1])
    del _argv[idx : idx + 2]
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

sys.argv = _argv

# ── lib_grading 패치 ──
import lib_grading  # noqa: E402

_orig_grade_task = lib_grading.grade_task


def _patched_grade_task(*, task, execution_result, skill_dir, **kwargs):
    if NO_JUDGE and task.grading_type == "llm_judge":
        return lib_grading.GradeResult(
            task_id=task.task_id,
            score=0.0,
            max_score=1.0,
            grading_type=task.grading_type,
            breakdown={},
            notes="pending_manual_review: --no-judge로 judge 생략",
        )
    if NO_JUDGE and task.grading_type == "hybrid":
        # automated 부분은 정상 채점, judge 부분은 0 + pending
        auto = lib_grading._grade_automated(
            task, execution_result, verbose=kwargs.get("verbose", False)
        )
        stub = lib_grading.GradeResult(
            task_id=task.task_id,
            score=0.0,
            max_score=1.0,
            grading_type="llm_judge",
            breakdown={},
            notes="pending_manual_review: --no-judge로 judge 생략",
        )
        combined = lib_grading._combine_grades(task, auto, stub)
        # 표시를 위해 notes에 부분 채점임을 기재
        combined.notes = (combined.notes or "") + " [--no-judge: automated only]"
        return combined
    return _orig_grade_task(
        task=task, execution_result=execution_result, skill_dir=skill_dir, **kwargs
    )


# ── lib_agent 패치 (artifact 저장) ──
import lib_agent  # noqa: E402

_orig_execute = lib_agent.execute_openclaw_task


def _snapshot_artifacts(task, agent_id: str, result: dict) -> None:
    """태스크 실행 직후 호출되어 artifacts/<task_id>/ 에 워크스페이스/세션/로그 복사."""
    if ARTIFACTS_DIR is None:
        return
    try:
        task_dir = ARTIFACTS_DIR / task.task_id
        if task_dir.exists():
            shutil.rmtree(task_dir, ignore_errors=True)
        task_dir.mkdir(parents=True, exist_ok=True)

        # workspace 스냅샷 (.git/.openclaw 제외)
        ws = result.get("workspace") or ""
        ws_path = Path(ws) if ws else None
        if ws_path and ws_path.exists() and ws_path.is_dir():
            try:
                shutil.copytree(
                    ws_path,
                    task_dir / "workspace",
                    ignore=shutil.ignore_patterns(".git", ".openclaw"),
                )
            except Exception as e:
                (task_dir / "workspace_error.txt").write_text(
                    f"copytree 실패: {e}\n원본: {ws_path}\n", encoding="utf-8"
                )

        # 세션 jsonl 복사 (다음 태스크의 cleanup 전에)
        sessions = Path.home() / ".openclaw" / "agents" / agent_id / "sessions"
        sess_dst = task_dir / "session"
        sess_dst.mkdir(parents=True, exist_ok=True)
        copied = 0
        if sessions.exists():
            for sf in sessions.glob("*.jsonl"):
                try:
                    shutil.copy2(sf, sess_dst / sf.name)
                    copied += 1
                except Exception:
                    pass

        # stdout/stderr 전문 보존
        (task_dir / "agent_stdout.txt").write_text(
            result.get("stdout") or "", encoding="utf-8"
        )
        (task_dir / "agent_stderr.txt").write_text(
            result.get("stderr") or "", encoding="utf-8"
        )

        import json as _json

        meta = {
            "task_id": task.task_id,
            "grading_type": task.grading_type,
            "status": result.get("status"),
            "timed_out": result.get("timed_out"),
            "execution_time": result.get("execution_time"),
            "exit_code": result.get("exit_code"),
            "session_files_copied": copied,
        }
        (task_dir / "meta.json").write_text(
            _json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        # 아티팩트 저장 실패해도 벤치마크 자체는 계속
        print(f"[pinchbench_wrapper] artifact 저장 실패 ({task.task_id}): {e}",
              file=sys.stderr)


def _patched_execute_openclaw_task(**kwargs):
    # 원본은 keyword-only 인자 `*, task, agent_id, ...` 를 요구함
    task = kwargs.get("task")
    agent_id = kwargs.get("agent_id")
    result = _orig_execute(**kwargs)
    _snapshot_artifacts(task, agent_id, result)
    return result


# ── benchmark.py 를 모듈로 import 후 globals 패치 ──
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "pb_benchmark", PB_ROOT / "scripts" / "benchmark.py"
)
_pb_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pb_mod)

# benchmark.py가 `from lib_grading import grade_task` 로 바인딩한 이름을 교체
_pb_mod.grade_task = _patched_grade_task
_pb_mod.execute_openclaw_task = _patched_execute_openclaw_task

# 그리고 lib_agent 내부에서 자체 호출하는 경우에도 대비
lib_agent.execute_openclaw_task = _patched_execute_openclaw_task

if NO_JUDGE:
    print("[pinchbench_wrapper] --no-judge 활성: llm_judge/hybrid 판정 보류",
          file=sys.stderr)
if ARTIFACTS_DIR:
    print(f"[pinchbench_wrapper] artifact 보존: {ARTIFACTS_DIR}", file=sys.stderr)

# 정상 진입점 호출
_pb_mod.main()
