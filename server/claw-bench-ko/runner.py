#!/usr/bin/env python3
"""claw-bench-ko runner — 한국어 에이전트 벤치마크 실행기

사용법:
  python3 runner.py --model <openclaw-model-id> [options]

옵션:
  --model       OpenClaw 모델 ID (필수)
  --judge       judge 모델 ID (기본: azure-openai/gpt-5.2-chat)
  --task        특정 태스크만 실행 (쉼표 구분)
  --runs        반복 실행 횟수 (기본: 1)
  --output-dir  결과 저장 디렉토리
  --dry-run     실제 실행 없이 태스크 목록만 출력

의존성: Python 3.8+ 표준 라이브러리만 사용
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TASKS_DIR = SCRIPT_DIR / "tasks"
MANIFEST_FILE = SCRIPT_DIR / "manifest.json"


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


def ensure_agent(agent_id: str, model: str, workspace: Path):
    """OpenClaw 에이전트가 없으면 생성"""
    result = subprocess.run(
        ["openclaw", "agents", "list"],
        capture_output=True, text=True, timeout=30
    )
    if agent_id in result.stdout:
        print(f"  에이전트 재사용: {agent_id}")
        return

    workspace.mkdir(parents=True, exist_ok=True)
    cmd = [
        "openclaw", "agents", "add", agent_id,
        "--model", model,
        "--workspace", str(workspace),
        "--non-interactive"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"  WARN: 에이전트 생성 실패 — {result.stderr.strip()}")
        raise RuntimeError(f"에이전트 생성 실패: {result.stderr}")
    print(f"  에이전트 생성: {agent_id} (model={model})")


def setup_workspace(workspace: Path, task: dict):
    """워크스페이스를 초기화하고 태스크 입력 파일을 복사"""
    # 기존 파일 정리 (디렉토리 자체는 유지)
    if workspace.exists():
        for item in workspace.iterdir():
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
            print(f"    인코딩 변환: {filename} → {target_enc}")


def run_agent_task(agent_id: str, session_id: str, prompt: str,
                   timeout: int) -> dict:
    """OpenClaw 에이전트에 태스크 전송 후 응답 수집"""
    cmd = [
        "openclaw", "agent",
        "--agent", agent_id,
        "--session-id", session_id,
        "--message", prompt
    ]
    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        elapsed = time.time() - start
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "duration_seconds": round(elapsed, 1)
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        return {
            "stdout": "",
            "stderr": f"TIMEOUT after {timeout}s",
            "returncode": -1,
            "duration_seconds": round(elapsed, 1)
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
                    judge_model: str, run_index: int) -> dict:
    """단일 태스크 1회 실행 + 채점"""
    task_id = task["id"]
    session_id = f"clawbench_{task_id}_{run_index}_{uuid.uuid4().hex[:8]}"

    print(f"  [{task_id}] 워크스페이스 설정...")
    setup_workspace(workspace, task)

    print(f"  [{task_id}] 에이전트 실행 중...")
    agent_result = run_agent_task(
        agent_id, session_id, task["prompt"],
        task.get("timeout_seconds", 180)
    )

    if agent_result["returncode"] != 0:
        print(f"  [{task_id}] 에이전트 실행 실패 (rc={agent_result['returncode']})")

    workspace_files = collect_workspace_files(workspace)
    print(f"  [{task_id}] 워크스페이스 파일: {list(workspace_files.keys())}")

    # 채점은 grader 모듈에서 수행
    from grader import grade_task
    grade_result = grade_task(
        task, workspace, agent_result["stdout"], judge_model
    )

    return {
        "task_id": task_id,
        "name": task["name"],
        "category": task["category"],
        "grading_type": task["grading_type"],
        "run_index": run_index,
        "score": grade_result["score"],
        "grading": grade_result,
        "duration_seconds": agent_result["duration_seconds"],
        "agent_returncode": agent_result["returncode"],
        "workspace_files": list(workspace_files.keys())
    }


def aggregate_runs(task_results: list) -> dict:
    """같은 태스크의 복수 실행 결과를 best/average로 집계"""
    if not task_results:
        return {}

    scores = [r["score"] for r in task_results]
    best_idx = scores.index(max(scores))

    return {
        "task_id": task_results[0]["task_id"],
        "name": task_results[0]["name"],
        "category": task_results[0]["category"],
        "grading_type": task_results[0]["grading_type"],
        "best_score": max(scores),
        "average_score": round(sum(scores) / len(scores), 4),
        "scores_per_run": scores,
        "runs": len(scores),
        "best_run": task_results[best_idx],
        "average_duration_seconds": round(
            sum(r["duration_seconds"] for r in task_results) / len(task_results), 1
        )
    }


def main():
    parser = argparse.ArgumentParser(description="claw-bench-ko runner")
    parser.add_argument("--model", required=True, help="OpenClaw 모델 ID")
    parser.add_argument("--judge", default="azure-openai/gpt-5.2-chat",
                        help="Judge 모델 ID")
    parser.add_argument("--task", default=None,
                        help="특정 태스크만 실행 (쉼표 구분)")
    parser.add_argument("--runs", type=int, default=1, help="반복 실행 횟수")
    parser.add_argument("--output-dir", default=None, help="결과 저장 디렉토리")
    parser.add_argument("--dry-run", action="store_true",
                        help="실행 없이 태스크 목록만 출력")
    args = parser.parse_args()

    manifest = load_manifest()
    print(f"=== {manifest['name']} v{manifest['version']} ===")
    print(f"모델: {args.model}")
    print(f"Judge: {args.judge}")
    print(f"반복: {args.runs}회")
    print()

    # 실행할 태스크 목록 결정
    task_ids = [t["id"] for t in manifest["tasks"]]
    if args.task:
        requested = [t.strip() for t in args.task.split(",")]
        task_ids = [t for t in task_ids if t in requested]
        if not task_ids:
            print(f"ERROR: 유효한 태스크 없음. 가능한 태스크: "
                  f"{[t['id'] for t in manifest['tasks']]}")
            sys.exit(1)

    print(f"태스크: {len(task_ids)}개 — {task_ids}")

    if args.dry_run:
        print("\n[DRY RUN] 실행하지 않음")
        for tid in task_ids:
            t = load_task(tid)
            print(f"  {tid}: {t['name']} ({t['grading_type']})")
        sys.exit(0)

    # 출력 디렉토리 설정
    model_slug = slug_from_model(args.model)
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = SCRIPT_DIR / "results" / f"{model_slug}_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 에이전트 생성
    run_id = uuid.uuid4().hex[:6]
    agent_id = f"clawbench-{model_slug}"
    workspace = Path(f"/tmp/claw-bench-ko/{run_id}/workspace")
    print(f"\n에이전트 설정: {agent_id}")
    ensure_agent(agent_id, args.model, workspace)

    # 태스크 실행
    all_results = {}  # task_id → [run results]
    total_start = time.time()

    for task_id in task_ids:
        task = load_task(task_id)
        all_results[task_id] = []

        for run_i in range(args.runs):
            run_label = f"run {run_i + 1}/{args.runs}" if args.runs > 1 else ""
            print(f"\n── {task['name']} ({task_id}) {run_label} ──")

            result = run_single_task(
                agent_id, task, workspace, args.judge, run_i
            )
            all_results[task_id].append(result)

            score_pct = f"{result['score'] * 100:.1f}%"
            print(f"  점수: {score_pct} ({result['duration_seconds']}초)")

    total_elapsed = time.time() - total_start

    # 결과 집계
    aggregated = []
    for task_id in task_ids:
        agg = aggregate_runs(all_results[task_id])
        aggregated.append(agg)

    best_scores = [a["best_score"] for a in aggregated]
    avg_scores = [a["average_score"] for a in aggregated]
    overall_best = round(sum(best_scores) / len(best_scores), 4) if best_scores else 0
    overall_avg = round(sum(avg_scores) / len(avg_scores), 4) if avg_scores else 0

    # 결과 JSON 생성
    output = {
        "benchmark": "claw-bench-ko",
        "version": manifest["version"],
        "model": args.model,
        "judge": args.judge,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runs_per_task": args.runs,
        "overall_best_score": overall_best,
        "overall_average_score": overall_avg,
        "total_duration_seconds": round(total_elapsed, 1),
        "tasks": aggregated,
        "summary": {
            "total": len(aggregated),
            "by_category": _count_by(aggregated, "category"),
            "by_grading_type": _count_by(aggregated, "grading_type"),
        }
    }

    result_file = output_dir / "results.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 결과 요약 출력
    print(f"\n{'=' * 50}")
    print(f"=== 결과 요약 ===")
    print(f"모델: {args.model}")
    print(f"전체 best: {overall_best * 100:.1f}%")
    print(f"전체 average: {overall_avg * 100:.1f}%")
    print(f"소요 시간: {total_elapsed:.0f}초 ({total_elapsed / 60:.1f}분)")
    print()

    for agg in aggregated:
        best_pct = f"{agg['best_score'] * 100:.1f}%"
        avg_pct = f"{agg['average_score'] * 100:.1f}%"
        if args.runs > 1:
            print(f"  {agg['task_id']:25s} best={best_pct:>6s}  avg={avg_pct:>6s}")
        else:
            print(f"  {agg['task_id']:25s} {best_pct:>6s}")

    print(f"\n결과 저장: {result_file}")


def _count_by(items: list, key: str) -> dict:
    counts = {}
    for item in items:
        val = item.get(key, "unknown")
        counts[val] = counts.get(val, 0) + 1
    return counts


if __name__ == "__main__":
    main()
