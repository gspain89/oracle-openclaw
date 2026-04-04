#!/usr/bin/env python3
"""normalize.py — PinchBench 원본 결과를 leaderboard.json으로 통합

사용법: python3 normalize.py
  - results/raw/pinchbench/*.json 에서 각 모델의 최신 결과를 읽음
  - server/config/models.json 의 모델 레지스트리와 병합
  - results/normalized/leaderboard.json 생성

의존성: 표준 라이브러리만 사용 (pip 의존성 0)
"""

import json
import os
import glob
from datetime import datetime, timezone

# 경로 설정 — 이 스크립트는 server/python/ 에 위치
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

RAW_PINCHBENCH = os.path.join(REPO_ROOT, 'results', 'raw', 'pinchbench')
RAW_AGENTBENCH = os.path.join(REPO_ROOT, 'results', 'raw', 'agentbench')
RAW_KOREAN = os.path.join(REPO_ROOT, 'results', 'raw', 'korean')
MODELS_FILE = os.path.join(REPO_ROOT, 'server', 'config', 'models.json')
OUTPUT_FILE = os.path.join(REPO_ROOT, 'results', 'normalized', 'leaderboard.json')


def load_models_registry():
    """models.json에서 모델 레지스트리 로드"""
    with open(MODELS_FILE, encoding='utf-8') as f:
        data = json.load(f)
    return {m['id']: m for m in data['models']}


def safe_model_name(model_id: str) -> str:
    """모델 ID → 파일명 안전 문자열 (run-pinchbench.sh와 동일 로직)"""
    return model_id.replace('/', '__').replace(':', '__')


def find_latest_result(raw_dir: str, model_id: str) -> dict | None:
    """특정 모델의 가장 최근 벤치마크 결과 파일을 찾아 파싱"""
    safe = safe_model_name(model_id)
    pattern = os.path.join(raw_dir, f'{safe}_*.json')
    files = sorted(glob.glob(pattern), reverse=True)  # 최신 파일이 먼저

    for fpath in files:
        try:
            with open(fpath, encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
    return None


def parse_pinchbench(raw: dict) -> dict | None:
    """PinchBench 원본 JSON → 정규화된 점수 객체

    PinchBench 출력 형식이 확정되면 이 함수를 조정.
    현재는 여러 가능한 형식을 탐색한다.
    """
    if raw is None:
        return None

    # 형식 A: summary 필드가 있는 경우
    s = raw.get('summary', {})
    if s:
        score = s.get('best_score') or s.get('score')
        if score is not None:
            # 퍼센트(0-100) vs 비율(0-1) 자동 감지
            if isinstance(score, (int, float)) and score <= 1.0:
                score *= 100
            return {
                'score': round(float(score), 1),
                'completed': int(s.get('tasks_completed', s.get('completed', 0))),
                'total': int(s.get('tasks_total', s.get('total', 23))),
            }

    # 형식 B: tasks 배열에서 직접 계산
    tasks = raw.get('tasks', [])
    if tasks:
        passed = sum(1 for t in tasks if t.get('passed') or t.get('score', 0) > 0.5)
        scores = [t.get('score', 0) for t in tasks]
        avg = sum(scores) / len(scores) if scores else 0
        if avg <= 1.0:
            avg *= 100
        return {
            'score': round(avg, 1),
            'completed': passed,
            'total': len(tasks),
        }

    # 형식 C: 플랫 구조
    score = raw.get('score') or raw.get('best_score') or raw.get('overall_score')
    if score is not None:
        if isinstance(score, (int, float)) and score <= 1.0:
            score *= 100
        return {
            'score': round(float(score), 1),
            'completed': int(raw.get('completed', 0)),
            'total': int(raw.get('total', 23)),
        }

    return None


def parse_korean(raw: dict) -> dict | None:
    """ClawBench-KO 원본 JSON → 정규화된 점수 객체

    claw-bench-ko runner가 생성하는 results.json 형식:
    - overall_best_score / overall_average_score (0.0~1.0)
    - tasks[].best_score, tasks[].average_score
    """
    if raw is None:
        return None

    best = raw.get('overall_best_score')
    avg = raw.get('overall_average_score')
    if best is None and avg is None:
        return None

    # 0.0~1.0 → 0~100 변환
    if best is not None and best <= 1.0:
        best *= 100
    if avg is not None and avg <= 1.0:
        avg *= 100

    tasks = raw.get('tasks', [])
    total = len(tasks)
    completed = sum(1 for t in tasks if t.get('best_score', 0) > 0)

    # 카테고리별 점수
    categories = {}
    for t in tasks:
        cat = t.get('category', 'unknown')
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(t.get('best_score', 0) * 100)

    cat_scores = {}
    for cat, scores in categories.items():
        cat_scores[cat] = round(sum(scores) / len(scores), 1) if scores else 0

    return {
        'best_score': round(float(best), 1) if best is not None else None,
        'average_score': round(float(avg), 1) if avg is not None else None,
        'completed': completed,
        'total': total,
        'categories': cat_scores,
    }


def parse_agentbench(raw: dict) -> dict | None:
    """AgentBench 원본 JSON → 정규화된 점수 객체"""
    if raw is None:
        return None

    s = raw.get('summary', raw)
    score = s.get('overall_score') or s.get('score')
    if score is None:
        return None

    if isinstance(score, (int, float)) and score <= 1.0:
        score *= 100

    return {
        'score': round(float(score), 1),
        'task_completion': float(s.get('task_completion', 0)),
        'tool_accuracy': float(s.get('tool_accuracy', 0)),
        'efficiency': float(s.get('efficiency', 0)),
        'quality': float(s.get('quality', 0)),
    }


def build_leaderboard(registry: dict) -> dict:
    """모델 레지스트리 + 원본 결과 → leaderboard.json"""
    models = []
    latest_update = None

    for model_id, info in registry.items():
        # PinchBench 결과 탐색
        pb_raw = find_latest_result(RAW_PINCHBENCH, model_id)
        pb = parse_pinchbench(pb_raw)

        # AgentBench 결과 탐색
        ab_raw = find_latest_result(RAW_AGENTBENCH, model_id)
        ab = parse_agentbench(ab_raw)

        # ClawBench-KO 결과 탐색
        ko_raw = find_latest_result(RAW_KOREAN, model_id)
        ko = parse_korean(ko_raw)

        # 타임스탬프 추적
        for raw in [pb_raw, ab_raw, ko_raw]:
            if raw and 'timestamp' in raw:
                ts = raw['timestamp']
                if latest_update is None or ts > latest_update:
                    latest_update = ts

        entry = {
            'id': model_id,
            'name': info['name'],
            'provider': info.get('provider', ''),
            'free': info.get('free', False),
            'cost_per_run_usd': estimate_run_cost(info, pb),
            'scores': {
                'pinchbench': pb,
                'agentbench': ab,
                'korean': ko,
            },
        }
        models.append(entry)

    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    runs_with_data = sum(1 for m in models if m['scores']['pinchbench'] is not None)

    return {
        'meta': {
            'last_updated': latest_update or now,
            'total_runs': runs_with_data,
            'generated_at': now,
            'note': '' if runs_with_data > 0 else '샘플 데이터 — 벤치마크 실행 전 UI 프리뷰용. 실제 측정값이 아님',
        },
        'models': models,
    }


def estimate_run_cost(info: dict, pb: dict | None) -> float:
    """모델 정보 + PinchBench 결과에서 실행 비용 추정

    실제 비용이 결과에 포함되어 있으면 그 값을 사용.
    없으면 models.json의 가격 정보로 대략 추정 (23 태스크, 평균 50K tokens 가정).
    """
    if info.get('free', False):
        return 0.0

    # 대략적 추정: PinchBench 23태스크 × 평균 2K input + 3K output tokens/태스크
    input_per_1m = info.get('input_price_per_1m', 0)
    output_per_1m = info.get('output_price_per_1m', 0)
    est_input_tokens = 23 * 2000
    est_output_tokens = 23 * 3000
    cost = (est_input_tokens / 1_000_000 * input_per_1m) + (est_output_tokens / 1_000_000 * output_per_1m)
    return round(cost, 2)


def main():
    print('=== normalize.py: 결과 정규화 ===')
    print(f'원본 경로: {RAW_PINCHBENCH}')
    print(f'모델 레지스트리: {MODELS_FILE}')
    print(f'출력: {OUTPUT_FILE}')
    print()

    registry = load_models_registry()
    print(f'등록 모델: {len(registry)}개')

    # 원본 결과 파일 수 확인
    pb_files = glob.glob(os.path.join(RAW_PINCHBENCH, '*.json'))
    ab_files = glob.glob(os.path.join(RAW_AGENTBENCH, '*.json'))
    ko_files = glob.glob(os.path.join(RAW_KOREAN, '*.json'))
    print(f'PinchBench 원본: {len(pb_files)}개')
    print(f'AgentBench 원본: {len(ab_files)}개')
    print(f'ClawBench-KO 원본: {len(ko_files)}개')
    print()

    leaderboard = build_leaderboard(registry)

    # 결과 요약
    models = leaderboard['models']
    pb_count = sum(1 for m in models if m['scores']['pinchbench'])
    ab_count = sum(1 for m in models if m['scores']['agentbench'])
    ko_count = sum(1 for m in models if m['scores']['korean'])
    print(f'PinchBench 측정 완료: {pb_count}/{len(models)}')
    print(f'AgentBench 측정 완료: {ab_count}/{len(models)}')
    print(f'ClawBench-KO 측정 완료: {ko_count}/{len(models)}')

    if pb_count > 0:
        scored = [m for m in models if m['scores']['pinchbench']]
        scored.sort(key=lambda m: m['scores']['pinchbench']['score'], reverse=True)
        print()
        print('--- PinchBench 순위 ---')
        for i, m in enumerate(scored, 1):
            s = m['scores']['pinchbench']
            print(f'  {i}. {m["name"]}: {s["score"]}점 ({s["completed"]}/{s["total"]} 태스크)')

    # 저장
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(leaderboard, f, ensure_ascii=False, indent=2)

    print()
    print(f'저장 완료: {OUTPUT_FILE}')
    print(f'크기: {os.path.getsize(OUTPUT_FILE):,} bytes')


if __name__ == '__main__':
    main()
