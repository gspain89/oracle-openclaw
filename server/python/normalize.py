#!/usr/bin/env python3
"""normalize.py — raw 벤치마크 결과 → leaderboard.json 생성

사용법:
  python3 normalize.py                  # 기본 경로 사용
  python3 normalize.py --repo-root /x   # 저장소 루트 명시

동작:
  1. results/raw/pinchbench/ 와 results/raw/korean/ 에서 모든 결과 JSON 수집
  2. 각 JSON 내부의 model 필드로 모델 식별 → models.json과 매칭
  3. 모델별 다중 실행 집계: best, average, std 계산
  4. results/normalized/leaderboard.json 생성

의존성: 표준 라이브러리만 (pip 의존성 0)
"""

import json
import os
import sys
import math
import argparse
from datetime import datetime, timezone
from pathlib import Path

# ── 경로 설정 ──

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REPO_ROOT = SCRIPT_DIR.parent.parent

PROVIDER_PREFIXES = ("openrouter/", "modelstudio/", "azure-openai/", "upstage/")


def resolve_paths(repo_root: Path):
    return {
        "raw_pb": repo_root / "results" / "raw" / "pinchbench",
        "raw_ko": repo_root / "results" / "raw" / "korean",
        "models": repo_root / "server" / "config" / "models.json",
        "output": repo_root / "results" / "normalized" / "leaderboard.json",
    }


# ── 모델 ID 매칭 ──

def strip_provider_prefix(raw_model: str) -> str:
    """raw JSON의 model 필드에서 provider 접두어 제거 → models.json ID와 매칭"""
    for prefix in PROVIDER_PREFIXES:
        if raw_model.startswith(prefix):
            return raw_model[len(prefix):]
    return raw_model


def load_registry(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {m["id"]: m for m in data["models"]}


# ── 결과 파일 수집 ──

def collect_result_files(raw_dir: Path) -> list[Path]:
    """디렉토리 내 모든 결과 JSON 파일을 수집

    두 가지 패턴 처리:
      1. 플랫 파일: {dir}/{name}_{ts}.json
      2. 서브디렉토리: {dir}/{name}_{ts}/results.json
    """
    if not raw_dir.exists():
        return []

    files = []
    for item in raw_dir.iterdir():
        if item.is_file() and item.suffix == ".json" and item.name != ".gitkeep":
            files.append(item)
        elif item.is_dir():
            rj = item / "results.json"
            if rj.exists():
                files.append(rj)
    return files


# ── PinchBench 파싱 ──

def parse_pinchbench_run(raw: dict) -> dict | None:
    """단일 PinchBench 실행 결과 → 정규화된 점수

    반환: {"score": 0-100, "completed": int, "total": int, "date": str,
           "avg_seconds_per_task": float, "model_raw": str}
    """
    # overall_score (0-1 비율)
    score = None
    if "overall_score" in raw and isinstance(raw["overall_score"], (int, float)):
        score = raw["overall_score"]
    elif "summary" in raw:
        s = raw["summary"]
        score = s.get("best_score") or s.get("score")

    if score is None:
        # tasks 배열에서 직접 계산
        tasks = raw.get("tasks", [])
        if not tasks:
            return None
        means = [t.get("grading", {}).get("mean", t.get("score", 0)) for t in tasks]
        score = sum(means) / len(means) if means else 0

    # 0-1 → 0-100 변환
    if isinstance(score, (int, float)) and score <= 1.0:
        score *= 100

    # completed/total
    s = raw.get("summary", {})
    completed = int(s.get("tasks_completed", s.get("completed", 0)))
    total = int(s.get("tasks_total", s.get("total", 24)))
    if completed == 0:
        tasks = raw.get("tasks", [])
        completed = sum(1 for t in tasks if t.get("passed") or t.get("grading", {}).get("mean", 0) > 0.5)
        total = total or len(tasks) or 24

    # 평균 실행 시간
    tasks = raw.get("tasks", [])
    exec_times = [t["execution_time"] for t in tasks if "execution_time" in t]
    avg_sec = sum(exec_times) / len(exec_times) if exec_times else 0

    # 타임스탬프 → 날짜
    ts = raw.get("timestamp", 0)
    date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d") if ts else ""

    return {
        "score": round(float(score), 1),
        "completed": completed,
        "total": total,
        "date": date_str,
        "avg_seconds_per_task": round(avg_sec, 1),
        "model_raw": raw.get("model", ""),
    }


# ── ClawBench-KO 파싱 ──

def parse_korean_run(raw: dict) -> dict | None:
    """단일 ClawBench-KO 실행 결과 → 정규화된 점수

    runner.py 출력 형식:
      overall_score: {"mean": 0-1, "total_earned": float, "total_possible": float}
      tasks[].grading.mean: 0-1
      tasks[].frontmatter.category: "data_processing" | "doc_generation" | "korean_system"
    """
    os_field = raw.get("overall_score")
    if isinstance(os_field, dict):
        score = os_field.get("mean", 0)
    elif isinstance(os_field, (int, float)):
        score = os_field
    else:
        return None

    # 0-1 → 0-100
    if score <= 1.0:
        score *= 100

    tasks = raw.get("tasks", [])
    total_tasks = len(set(t.get("task_id") for t in tasks))
    completed = 0
    # 카테고리별 점수 집계 (task_id 기준 중복 제거: 같은 task_id면 첫 번째만)
    seen_tasks = set()
    cat_scores = {}  # category → [scores]
    for t in tasks:
        tid = t.get("task_id")
        if tid in seen_tasks:
            continue
        seen_tasks.add(tid)

        mean = t.get("grading", {}).get("mean", 0)
        if mean > 0:
            completed += 1

        cat = t.get("frontmatter", {}).get("category", "unknown")
        if cat not in cat_scores:
            cat_scores[cat] = []
        cat_scores[cat].append(mean * 100)  # 0-1 → 0-100

    categories = {}
    for cat, scores in cat_scores.items():
        categories[cat] = round(sum(scores) / len(scores), 1) if scores else 0

    # 평균 실행 시간
    exec_times = [t["execution_time"] for t in tasks if "execution_time" in t]
    avg_sec = sum(exec_times) / len(exec_times) if exec_times else 0

    ts = raw.get("timestamp", 0)
    date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d") if ts else ""

    return {
        "score": round(float(score), 1),
        "completed": completed,
        "total": total_tasks or len(tasks),
        "date": date_str,
        "categories": categories,
        "avg_seconds_per_task": round(avg_sec, 1),
        "model_raw": raw.get("model", ""),
    }


# ── 다중 실행 집계 ──

def aggregate_runs(runs: list[dict]) -> dict:
    """여러 실행 결과를 집계: best, average, std

    runs: parse_*_run() 반환값 리스트
    """
    scores = [r["score"] for r in runs]
    n = len(scores)

    best = max(scores)
    avg = sum(scores) / n
    if n >= 2:
        variance = sum((s - avg) ** 2 for s in scores) / (n - 1)
        std = math.sqrt(variance)
    else:
        std = 0.0

    run_records = []
    for r in sorted(runs, key=lambda x: x["date"]):
        run_records.append({
            "score": r["score"],
            "completed": r["completed"],
            "total": r["total"],
            "date": r["date"],
        })

    # 카테고리 (ClawBench-KO): best run의 카테고리 사용
    best_run = max(runs, key=lambda r: r["score"])
    categories = best_run.get("categories")

    # 평균 실행 시간 (전체 실행의 평균)
    avg_secs = [r["avg_seconds_per_task"] for r in runs if r.get("avg_seconds_per_task")]
    avg_sec_per_task = sum(avg_secs) / len(avg_secs) if avg_secs else 0

    result = {
        "best": round(best, 1),
        "average": round(avg, 1),
        "std": round(std, 2),
        "runs": run_records,
    }
    if categories:
        result["categories"] = categories
    return result, round(avg_sec_per_task, 1)


# ── 비용 추정 ──

def estimate_cost(info: dict, num_tasks: int = 24) -> float:
    """모델 가격 정보로 1회 실행 비용 추정

    가정: 태스크당 평균 2000 input tokens + 3000 output tokens
    """
    if info.get("free", False):
        return 0.0
    inp = info.get("input_price_per_1m", 0)
    out = info.get("output_price_per_1m", 0)
    est_in = num_tasks * 2000
    est_out = num_tasks * 3000
    return round((est_in / 1e6 * inp) + (est_out / 1e6 * out), 2)


# ── 기존 leaderboard 로드 (증분 병합용) ──

def load_existing_leaderboard(path: Path) -> dict:
    """기존 leaderboard.json을 읽어서 model_id → entry dict로 반환"""
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {m["id"]: m for m in data.get("models", [])}
    except (json.JSONDecodeError, OSError):
        return {}


# ── 메인 빌드 ──

def build_leaderboard(registry: dict, paths: dict) -> dict:
    # 기존 leaderboard 로드 — raw 데이터가 없는 모델은 여기서 유지
    existing = load_existing_leaderboard(paths["output"])
    if existing:
        print(f"기존 leaderboard: {len(existing)}개 모델 (증분 병합)")

    # 결과 파일 수집
    pb_files = collect_result_files(paths["raw_pb"])
    ko_files = collect_result_files(paths["raw_ko"])

    print(f"PinchBench 결과 파일: {len(pb_files)}개")
    print(f"ClawBench-KO 결과 파일: {len(ko_files)}개")
    print()

    # 모델별 실행 결과 그룹핑 (model_id → [parsed_run, ...])
    pb_runs = {}  # model_id → [run_dict]
    ko_runs = {}

    for fpath in pb_files:
        try:
            with open(fpath, encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  SKIP {fpath.name}: {e}")
            continue

        parsed = parse_pinchbench_run(raw)
        if not parsed:
            print(f"  SKIP {fpath.name}: 파싱 실패")
            continue

        model_id = strip_provider_prefix(parsed["model_raw"])
        if model_id not in registry:
            print(f"  WARN {fpath.name}: 모델 '{model_id}' 레지스트리에 없음")
            continue

        pb_runs.setdefault(model_id, []).append(parsed)

    for fpath in ko_files:
        try:
            with open(fpath, encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  SKIP {fpath.name}: {e}")
            continue

        parsed = parse_korean_run(raw)
        if not parsed:
            print(f"  SKIP {fpath.name}: 파싱 실패")
            continue

        model_id = strip_provider_prefix(parsed["model_raw"])
        if model_id not in registry:
            print(f"  WARN {fpath.name}: 모델 '{model_id}' 레지스트리에 없음")
            continue

        ko_runs.setdefault(model_id, []).append(parsed)

    # 리더보드 모델 엔트리 빌드
    models = []
    total_run_count = 0
    models_from_raw = set()  # raw 데이터로 갱신된 모델 ID

    for model_id, info in registry.items():
        pb_list = pb_runs.get(model_id, [])
        ko_list = ko_runs.get(model_id, [])

        # raw 데이터가 없는 모델 → 기존 leaderboard 데이터 유지
        if not pb_list and not ko_list:
            if model_id in existing:
                models.append(existing[model_id])
                # 기존 실행 횟수 합산
                for bench in ("pinchbench", "clawbench_ko"):
                    runs = existing[model_id].get("scores", {}).get(bench, {}).get("runs", [])
                    total_run_count += len(runs)
            continue

        models_from_raw.add(model_id)

        entry = {
            "id": model_id,
            "name": info["name"],
            "provider": info.get("provider", ""),
            "provider_label": info.get("provider_label", info.get("provider", "")),
            "free": info.get("free", False),
            "cost_per_run_usd": estimate_cost(info),
            "input_price_per_1m": info.get("input_price_per_1m", 0),
            "output_price_per_1m": info.get("output_price_per_1m", 0),
            "params_b": info.get("params_b", 0),
            "avg_seconds_per_task": 0,
            "scores": {},
        }

        # PinchBench 집계
        avg_secs = []
        if pb_list:
            agg, avg_sec = aggregate_runs(pb_list)
            entry["scores"]["pinchbench"] = agg
            total_run_count += len(pb_list)
            if avg_sec > 0:
                avg_secs.append(avg_sec)

        # ClawBench-KO 집계
        if ko_list:
            agg, avg_sec = aggregate_runs(ko_list)
            entry["scores"]["clawbench_ko"] = agg
            total_run_count += len(ko_list)
            if avg_sec > 0:
                avg_secs.append(avg_sec)

        # 전체 평균 태스크 시간
        if avg_secs:
            entry["avg_seconds_per_task"] = round(sum(avg_secs) / len(avg_secs), 0)

        # 복합 점수 (PinchBench 50% + ClawBench-KO 50%)
        pb_best = entry["scores"].get("pinchbench", {}).get("best", 0)
        ko_best = entry["scores"].get("clawbench_ko", {}).get("best", 0)
        pb_avg = entry["scores"].get("pinchbench", {}).get("average", 0)
        ko_avg = entry["scores"].get("clawbench_ko", {}).get("average", 0)

        if pb_best > 0 and ko_best > 0:
            entry["scores"]["composite"] = {
                "best": round((pb_best + ko_best) / 2, 2),
                "average": round((pb_avg + ko_avg) / 2, 2),
            }
        elif pb_best > 0:
            entry["scores"]["composite"] = {"best": pb_best, "average": pb_avg}
        elif ko_best > 0:
            entry["scores"]["composite"] = {"best": ko_best, "average": ko_avg}

        models.append(entry)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if models_from_raw:
        kept = [m["name"] for m in models if m["id"] not in models_from_raw]
        if kept:
            print(f"\n기존 데이터 유지: {', '.join(kept)}")

    return {
        "meta": {
            "last_updated": now,
            "total_runs": total_run_count,
            "generated_at": now,
            "_new_from_raw": len(models_from_raw),
        },
        "models": models,
    }


def main():
    parser = argparse.ArgumentParser(description="벤치마크 결과 → leaderboard.json")
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT),
                        help="저장소 루트 경로")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    paths = resolve_paths(repo_root)

    print("=== normalize.py: 결과 정규화 ===")
    print(f"저장소: {repo_root}")
    print(f"모델 레지스트리: {paths['models']}")
    print()

    registry = load_registry(paths["models"])
    print(f"등록 모델: {len(registry)}개")

    leaderboard = build_leaderboard(registry, paths)

    models = leaderboard["models"]
    new_count = leaderboard["meta"].get("_new_from_raw", 0)
    kept_count = len(models) - new_count
    pb_count = sum(1 for m in models if "pinchbench" in m["scores"])
    ko_count = sum(1 for m in models if "clawbench_ko" in m["scores"])
    print(f"\n전체 모델: {len(models)}개 (raw에서 갱신: {new_count}, 기존 유지: {kept_count})")
    print(f"PinchBench: {pb_count}개 모델")
    print(f"ClawBench-KO: {ko_count}개 모델")
    print(f"총 실행 횟수: {leaderboard['meta']['total_runs']}")

    if pb_count > 0:
        scored = sorted(
            [m for m in models if "pinchbench" in m["scores"]],
            key=lambda m: m["scores"]["pinchbench"]["best"],
            reverse=True,
        )
        print("\n--- PinchBench 순위 ---")
        for i, m in enumerate(scored, 1):
            s = m["scores"]["pinchbench"]
            runs_n = len(s["runs"])
            print(f"  {i}. {m['name']}: best={s['best']}% avg={s['average']}% "
                  f"std=\u00b1{s['std']} ({runs_n}회)")

    # 저장
    paths["output"].parent.mkdir(parents=True, exist_ok=True)
    with open(paths["output"], "w", encoding="utf-8") as f:
        json.dump(leaderboard, f, ensure_ascii=False, indent=2)

    size = paths["output"].stat().st_size
    print(f"\n저장: {paths['output']} ({size:,} bytes)")


if __name__ == "__main__":
    main()
