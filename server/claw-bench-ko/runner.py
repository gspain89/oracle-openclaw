#!/usr/bin/env python3
"""claw-bench-ko runner — 한국어 에이전트 벤치마크 실행기

사용법:
  python3 runner.py --model <openclaw-model-id> [options]

옵션:
  --model       OpenClaw 모델 ID (필수)
  --judge       judge 모델 ID (기본: anthropic/claude-opus-4-6)
  --task        특정 태스크만 실행 (쉼표 구분)
  --runs        반복 실행 횟수 (기본: 1)
  --output-dir  결과 저장 디렉토리
  --dry-run     실제 실행 없이 태스크 목록만 출력
  --verbose     상세 로그 출력 (워크스페이스 파일, 에이전트 stdout 등)
  --no-fail-fast  첫 태스크 0점이어도 계속 실행

의존성: Python 3.8+ 표준 라이브러리만 사용
"""

import argparse
import hashlib
import json
import logging
import os
import shutil
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TASKS_DIR = SCRIPT_DIR / "tasks"
MANIFEST_FILE = SCRIPT_DIR / "manifest.json"

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(SCRIPT_DIR / "benchmark.log"),
    ],
)
logger = logging.getLogger("claw-bench-ko")


def load_manifest():
    with open(MANIFEST_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_task(task_id: str) -> dict:
    task_file = TASKS_DIR / task_id / "task.json"
    with open(task_file, encoding="utf-8") as f:
        return json.load(f)


def slug_from_model(model_id: str) -> str:
    """모델 ID → 에이전트/파일명 안전 문자열"""
    return model_id.replace("/", "-").replace(":", "-").replace(".", "-")


def create_agent(agent_id: str, model: str, workspace: Path):
    """OpenClaw 에이전트 생성 (기존 동명 에이전트는 삭제 후 재생성)"""
    result = subprocess.run(
        ["openclaw", "agents", "list"],
        capture_output=True, text=True, timeout=30
    )
    if agent_id in result.stdout:
        subprocess.run(
            ["openclaw", "agents", "delete", agent_id, "--force"],
            capture_output=True, text=True, timeout=30
        )
        logger.debug("  기존 에이전트 삭제: %s", agent_id)

    workspace.mkdir(parents=True, exist_ok=True)
    cmd = [
        "openclaw", "agents", "add", agent_id,
        "--model", model,
        "--workspace", str(workspace),
        "--non-interactive"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        logger.warning("  에이전트 생성 실패 — %s", result.stderr.strip())
        raise RuntimeError(f"에이전트 생성 실패: {result.stderr}")
    logger.debug("  에이전트 생성: %s (model=%s)", agent_id, model)


def delete_agent(agent_id: str):
    """에이전트 삭제 (세션/워크스페이스 정리)

    openclaw agents delete --force가 세션 파일을 완전히 삭제하지 못하는
    경우가 있어, 에이전트 디렉토리를 직접 정리한다. 세션 히스토리가 남으면
    동일 agent_id 재사용 시 이전 대화가 누적되어 모델이 혼란에 빠진다.
    """
    subprocess.run(
        ["openclaw", "agents", "delete", agent_id, "--force"],
        capture_output=True, text=True, timeout=30
    )
    # openclaw delete가 남기는 잔여 세션/에이전트 파일 강제 정리
    agent_dir = Path.home() / ".openclaw" / "agents" / agent_id
    if agent_dir.exists():
        shutil.rmtree(agent_dir, ignore_errors=True)
    logger.debug("  에이전트 삭제: %s", agent_id)


def setup_workspace(workspace: Path, task: dict):
    """워크스페이스를 초기화하고 태스크 입력 파일을 복사"""
    PRESERVE_DIRS = {".git", ".openclaw"}
    if workspace.exists():
        for item in workspace.iterdir():
            if item.name in PRESERVE_DIRS:
                continue
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
    workspace.mkdir(parents=True, exist_ok=True)

    task_id = task["id"]
    input_dir = TASKS_DIR / task_id / "input"
    if not input_dir.exists():
        return

    for src_file in input_dir.iterdir():
        dst = workspace / src_file.name
        shutil.copy2(src_file, dst)

    # EUC-KR 인코딩 변환이 필요한 파일 처리
    encoding_setup = task.get("encoding_setup", {})
    for filename, target_enc in encoding_setup.items():
        fpath = workspace / filename
        if fpath.exists():
            content = fpath.read_text(encoding="utf-8")
            fpath.write_bytes(content.encode(target_enc))
            logger.debug("    인코딩 변환: %s → %s", filename, target_enc)


def run_agent_task(agent_id: str, session_id: str, prompt: str,
                   timeout: int) -> dict:
    """OpenClaw 에이전트에 태스크 전송 후 응답 수집"""
    cmd = [
        "openclaw", "agent",
        "--agent", agent_id,
        "--session-id", session_id,
        "--timeout", str(timeout),
        "--message", prompt
    ]
    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout + 60
        )
        elapsed = time.time() - start
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "duration_seconds": round(elapsed, 1),
            "timed_out": False,
            "status": "success" if result.returncode == 0 else "error",
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        return {
            "stdout": "",
            "stderr": f"TIMEOUT after {timeout}s",
            "returncode": -1,
            "duration_seconds": round(elapsed, 1),
            "timed_out": True,
            "status": "timeout",
        }


def collect_workspace_files(workspace: Path) -> dict:
    """워크스페이스의 모든 파일 목록과 크기를 수집"""
    files = {}
    if not workspace.exists():
        return files
    for item in workspace.rglob("*"):
        if item.is_file():
            rel = str(item.relative_to(workspace))
            files[rel] = {"size_bytes": item.stat().st_size}
    return files


def run_single_task(agent_id: str, task: dict, workspace: Path,
                    judge_model: str, run_index: int,
                    verbose: bool = False) -> dict:
    """단일 태스크 1회 실행 + 채점"""
    task_id = task["id"]
    session_id = f"clawbench_{task_id}_{run_index}_{uuid.uuid4().hex[:8]}"

    setup_workspace(workspace, task)

    # 워크스페이스 초기 상태 확인 — 입력 파일이 제대로 복사됐는지
    input_files = [f.name for f in workspace.iterdir() if f.is_file()]
    if input_files:
        logger.info("    입력 파일: %s", input_files)
    else:
        logger.warning("    ⚠️ 워크스페이스에 입력 파일 없음")

    agent_result = run_agent_task(
        agent_id, session_id, task["prompt"],
        task.get("timeout_seconds", 180)
    )

    workspace_files = collect_workspace_files(workspace)

    # 에이전트 실행 에러 감지 — 비verbose에서도 항상 출력
    if agent_result["returncode"] != 0:
        logger.warning("    ⚠️ 에이전트 returncode=%d", agent_result["returncode"])
        if agent_result["stderr"]:
            logger.warning("    stderr: %s", agent_result["stderr"][:500])
    if agent_result["timed_out"]:
        logger.warning("    ⚠️ 에이전트 타임아웃 (%ds)", task.get("timeout_seconds", 180))
    if not workspace_files:
        logger.warning("    ⚠️ 워크스페이스 비어있음 — 에이전트가 파일을 생성하지 않음")
    else:
        logger.info("    워크스페이스 파일: %s", list(workspace_files.keys()))

    if verbose:
        if agent_result["stdout"]:
            logger.info("    [VERBOSE] Stdout (전문): %s",
                         agent_result["stdout"][:2000])

    # 채점
    from grader import grade_task
    grade_result = grade_task(
        task, workspace, agent_result["stdout"], judge_model
    )

    # 0점 진단 — stdout에 결과가 있지만 파일로 저장 안 된 경우 등 원인 특정
    if grade_result["score"] == 0:
        output_file = task.get("grading", {}).get("automated", {}).get("output_file", "")
        has_output_file = output_file and (workspace / output_file).exists()

        logger.warning("    ── 0점 진단 ──")
        logger.warning("    returncode: %d | timed_out: %s | duration: %.1fs",
                        agent_result["returncode"],
                        agent_result["timed_out"],
                        agent_result["duration_seconds"])

        if output_file and not has_output_file:
            logger.warning("    기대 출력 파일 '%s' 미존재", output_file)
            # stdout에 JSON이 포함돼있는지 확인 — 파일 대신 채팅으로 응답한 경우
            stdout = agent_result["stdout"]
            if stdout and ("{" in stdout or "[" in stdout):
                logger.warning("    ⚠️ stdout에 JSON 포함 — 에이전트가 파일 대신 채팅으로 응답한 것으로 추정")
                logger.warning("    stdout (앞 800자): %s", stdout[:800])
            elif not stdout:
                logger.warning("    ⚠️ stdout 비어있음 — 에이전트가 응답하지 않음")
            else:
                logger.warning("    stdout (앞 500자): %s", stdout[:500])
        elif has_output_file:
            logger.warning("    출력 파일 '%s' 존재하나 채점 실패 — 내용 오류", output_file)
            try:
                content = (workspace / output_file).read_text(encoding="utf-8")[:500]
                logger.warning("    파일 내용 (앞 500자): %s", content)
            except Exception:
                pass

        if agent_result["stderr"]:
            logger.warning("    stderr: %s", agent_result["stderr"][:500])

    return {
        "task_id": task_id,
        "name": task["name"],
        "category": task["category"],
        "grading_type": task["grading_type"],
        "run_index": run_index,
        "score": grade_result["score"],
        "max_score": 1.0,
        "grading": grade_result,
        "duration_seconds": agent_result["duration_seconds"],
        "timed_out": agent_result["timed_out"],
        "status": agent_result["status"],
        "agent_returncode": agent_result["returncode"],
        "workspace_files": list(workspace_files.keys()),
    }


def aggregate_runs(task_results: list) -> dict:
    """같은 태스크의 복수 실행 결과를 mean/std/min/max로 집계 (PinchBench 호환)"""
    if not task_results:
        return {}

    scores = [r["score"] for r in task_results]

    return {
        "task_id": task_results[0]["task_id"],
        "name": task_results[0]["name"],
        "category": task_results[0]["category"],
        "grading_type": task_results[0]["grading_type"],
        "grading": {
            "runs": [r["grading"] for r in task_results],
            "mean": statistics.mean(scores),
            "std": statistics.stdev(scores) if len(scores) > 1 else 0.0,
            "min": min(scores),
            "max": max(scores),
        },
        "average_duration_seconds": round(
            sum(r["duration_seconds"] for r in task_results) / len(task_results), 1
        ),
    }


def _log_category_summary(aggregated: list):
    """카테고리별 점수 요약 (PinchBench 형식)"""
    category_scores = {}
    for agg in aggregated:
        cat = agg["category"].upper()
        mean = agg["grading"]["mean"]
        if cat not in category_scores:
            category_scores[cat] = {"earned": 0.0, "possible": 0.0, "task_count": 0}
        category_scores[cat]["earned"] += mean
        category_scores[cat]["possible"] += 1.0
        category_scores[cat]["task_count"] += 1

    total_earned = sum(c["earned"] for c in category_scores.values())
    total_possible = sum(c["possible"] for c in category_scores.values())
    overall_pct = (total_earned / total_possible * 100) if total_possible > 0 else 0

    logger.info("\n%s", "=" * 80)
    logger.info("🦀 CLAWBENCH-KO SCORE SUMMARY")
    logger.info("%s", "=" * 80)
    logger.info("")
    logger.info("   Overall Score: %.1f%% (%.1f / %.1f)",
                overall_pct, total_earned, total_possible)
    logger.info("")
    logger.info("   %-24s %8s %12s", "CATEGORY", "SCORE", "TASKS")
    logger.info("   %s", "-" * 44)

    for cat in sorted(category_scores.keys()):
        data = category_scores[cat]
        pct = (data["earned"] / data["possible"] * 100) if data["possible"] > 0 else 0
        count = data["task_count"]
        task_label = "task" if count == 1 else "tasks"

        if pct >= 90:
            indicator = "🟢"
        elif pct >= 70:
            indicator = "🟡"
        else:
            indicator = "🔴"

        logger.info("   %s %-20s %6.1f%% %6d %s",
                     indicator, cat, pct, count, task_label)

    logger.info("   %s", "-" * 44)


def _preflight_check_model(model_id: str, label: str = "Model"):
    """openclaw models list에서 모델 존재 여부를 사전 확인.
    미등록 모델이면 에러 메시지와 함께 즉시 종료."""
    try:
        result = subprocess.run(
            ["openclaw", "models", "list"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            logger.error("openclaw models list 실행 실패: %s", result.stderr[:200])
            sys.exit(1)

        # 모델 ID가 출력에 존재하는지 확인
        if model_id not in result.stdout:
            logger.error("=" * 80)
            logger.error("🚨 %s '%s' — openclaw에 등록되지 않은 모델", label, model_id)
            logger.error("")
            logger.error("  등록된 모델 목록:")
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if "/" in line and not line.startswith("Model"):
                    logger.error("    %s", line.split()[0])
            logger.error("")
            logger.error("  모델을 등록하려면: openclaw config")
            logger.error("=" * 80)
            sys.exit(1)

        logger.info("✅ %s 확인: %s", label, model_id)
    except FileNotFoundError:
        logger.error("openclaw CLI를 찾을 수 없습니다")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        logger.warning("openclaw models list 타임아웃 — 검증 건너뜀")


def main():
    parser = argparse.ArgumentParser(description="claw-bench-ko runner")
    parser.add_argument("--model", required=True, help="OpenClaw 모델 ID")
    parser.add_argument("--judge", default="anthropic/claude-opus-4-6",
                        help="Judge 모델 ID")
    parser.add_argument("--task", default=None,
                        help="특정 태스크만 실행 (쉼표 구분)")
    parser.add_argument("--runs", type=int, default=1, help="반복 실행 횟수")
    parser.add_argument("--output-dir", default=None, help="결과 저장 디렉토리")
    parser.add_argument("--dry-run", action="store_true",
                        help="실행 없이 태스크 목록만 출력")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="상세 로그 출력")
    parser.add_argument("--no-fail-fast", action="store_true",
                        help="첫 태스크 0점이어도 계속 실행")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="모델 사전 검증 건너뜀 (shell script에서 이미 검증한 경우)")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # ── 모델 사전 검증 (preflight) ──
    if args.skip_preflight:
        logger.debug("모델 사전 검증 건너뜀 (--skip-preflight)")
    else:
        _preflight_check_model(args.model, "Model")
        _preflight_check_model(args.judge, "Judge")

    manifest = load_manifest()
    logger.info("=" * 80)
    logger.info("🦀 ClawBench-KO v%s", manifest["version"])
    logger.info("=" * 80)
    logger.info("   Model: %s", args.model)
    logger.info("   Judge: %s", args.judge)
    logger.info("   Runs:  %d", args.runs)
    logger.info("")

    # 실행할 태스크 목록 결정
    task_ids = [t["id"] for t in manifest["tasks"]]
    if args.task:
        requested = [t.strip() for t in args.task.split(",")]
        task_ids = [t for t in task_ids if t in requested]
        if not task_ids:
            logger.error("유효한 태스크 없음. 가능한 태스크: %s",
                         [t["id"] for t in manifest["tasks"]])
            sys.exit(1)

    logger.info("   Tasks: %d — %s", len(task_ids), task_ids)

    if args.dry_run:
        logger.info("\n[DRY RUN] 실행하지 않음")
        for tid in task_ids:
            t = load_task(tid)
            logger.info("  %s: %s (%s)", tid, t["name"], t["grading_type"])
        sys.exit(0)

    # 출력 디렉토리 설정
    model_slug = slug_from_model(args.model)
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = SCRIPT_DIR / "results" / f"{model_slug}_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 태스크 실행
    all_results = {}  # task_id → [run results]
    total_start = time.time()
    total_tasks = len(task_ids)
    runs_per_task = args.runs

    for task_idx, task_id in enumerate(task_ids, 1):
        task = load_task(task_id)
        all_results[task_id] = []

        for run_i in range(runs_per_task):
            # PinchBench 스타일 진행 헤더
            logger.info("\n%s", "=" * 80)
            logger.info("📋 Task %d/%d (Run %d/%d)",
                        task_idx, total_tasks, run_i + 1, runs_per_task)
            logger.info("%s", "=" * 80)
            logger.info("🤖 Agent starting task: %s", task_id)
            logger.info("   Task: %s", task["name"])
            logger.info("   Category: %s", task["category"])

            # 태스크마다 고유 에이전트 생성 (세션 격리)
            run_id = uuid.uuid4().hex[:6]
            model_hash = hashlib.md5(model_slug.encode()).hexdigest()[:6]
            agent_id = f"cb-{model_hash}-{task_id}-{run_i}"
            workspace = Path(f"/tmp/claw-bench-ko/{run_id}/workspace")
            create_agent(agent_id, args.model, workspace)

            result = run_single_task(
                agent_id, task, workspace, args.judge, run_i,
                verbose=args.verbose,
            )
            all_results[task_id].append(result)

            delete_agent(agent_id)

            # PinchBench 스타일 점수 표시
            score = result["score"]
            max_score = result["max_score"]
            score_pct = score / max_score * 100 if max_score > 0 else 0
            if score >= max_score:
                emoji = "✅"
            elif score > 0:
                emoji = "⚠️"
            else:
                emoji = "❌"

            logger.info("%s Task %s: %.1f/%.1f (%.0f%%) - %s",
                        emoji, task_id, score, max_score, score_pct,
                        task["grading_type"])

            # fail-fast: 첫 태스크가 0점이면 중단
            if (task_idx == 1 and run_i == 0
                    and score == 0 and not args.no_fail_fast):
                logger.error(
                    "🚨 FAIL FAST: 첫 태스크 (%s) 0%%. "
                    "벤치마크를 중단합니다. --no-fail-fast로 우회 가능.",
                    task_id)
                sys.exit(3)

    total_elapsed = time.time() - total_start

    # 결과 집계
    aggregated = []
    for task_id in task_ids:
        agg = aggregate_runs(all_results[task_id])
        aggregated.append(agg)

    # --- 결과 JSON 생성 (PinchBench 호환 스키마) ---
    task_entries = []
    for task_id in task_ids:
        for r in all_results[task_id]:
            task_entries.append({
                "task_id": r["task_id"],
                "status": r["status"],
                "timed_out": r["timed_out"],
                "execution_time": r["duration_seconds"],
                "workspace_files": r["workspace_files"],
                "grading": next(
                    a["grading"] for a in aggregated if a["task_id"] == task_id
                ),
                "frontmatter": {
                    "id": r["task_id"],
                    "name": r["name"],
                    "category": r["category"],
                    "grading_type": r["grading_type"],
                },
            })

    # overall score
    all_means = [a["grading"]["mean"] for a in aggregated]
    total_earned = sum(all_means)
    total_possible = float(len(aggregated))
    overall_pct = (total_earned / total_possible * 100) if total_possible > 0 else 0

    output = {
        "benchmark": "claw-bench-ko",
        "version": manifest["version"],
        "model": args.model,
        "judge": args.judge,
        "timestamp": time.time(),
        "suite": args.task or "all",
        "runs_per_task": runs_per_task,
        "overall_score": {
            "mean": round(total_earned / total_possible, 4) if total_possible else 0,
            "total_earned": round(total_earned, 4),
            "total_possible": total_possible,
        },
        "total_duration_seconds": round(total_elapsed, 1),
        "tasks": task_entries,
    }

    result_file = output_dir / "results.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # --- 최종 요약 출력 (PinchBench 스타일) ---
    logger.info("📊 Final score: %.2f/%.0f (%.1f%%)",
                total_earned, total_possible, overall_pct)
    logger.info("Saved results to %s", result_file)

    _log_category_summary(aggregated)

    # 토큰 효율 요약은 ClawBench-KO에서 토큰 추적이 불가하므로
    # 실행 시간 기반 요약으로 대체
    logger.info("\n%s", "=" * 80)
    logger.info("⏱️  EXECUTION SUMMARY")
    logger.info("%s", "=" * 80)
    logger.info("   Total duration: %.0fs (%.1f min)",
                total_elapsed, total_elapsed / 60)
    logger.info("   Tasks: %d × %d runs = %d executions",
                len(task_ids), runs_per_task, len(task_ids) * runs_per_task)
    avg_dur = total_elapsed / (len(task_ids) * runs_per_task)
    logger.info("   Avg per execution: %.1fs", avg_dur)
    logger.info("%s", "=" * 80)


if __name__ == "__main__":
    main()
