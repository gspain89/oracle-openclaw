# ClawBench-KO — 한국어 에이전트 능력 벤치마크

최종 수정: 2026-04-04
버전: 1.0.0
위치: `server/claw-bench-ko/`

---

## 1. 개요

ClawBench-KO는 OpenClaw 에이���트가 한국어 환경에서 실무 작업을 수행하는 능력을 측정하는 자체 제작 벤치마크다. PinchBench가 범용 소프트웨어 엔지니어링 능력을 측정한다면, ClawBench-KO는 한국어 데이터 처리, 한국식 문서 생성, 한국 고유 시스템에 대한 이해도를 측정한다.

10개 태스크, 3가지 채점 유형:

| 채점 유형 | 태스크 수 | 방식 |
|-----------|-----------|------|
| automated | 4 | 출력 파일의 JSON 구조, 필드 값, 인코딩 등을 프로그래밍적으로 검증 |
| llm_judge | 3 | judge 모델(GPT-5.3)이 루브릭 기반으로 100점 만점 채점 |
| hybrid | 3 | automated 50% + judge 50% 가중 결합 |


## 2. 실행 방법

```bash
# 서버에서 실행 (OpenClaw CLI 필요)
cd ~/oracle-openclaw

# 전체 10개 태스크, 1회 실행
bash server/scripts/run-claw-bench-ko.sh nvidia/nemotron-3-super-120b-a12b:free

# automated 태스크만 (judge 비용 없음)
bash server/scripts/run-claw-bench-ko.sh nvidia/nemotron-3-super-120b-a12b:free \
  --task addr_parse,num_convert,phone_normalize

# 3회 반복 실행 (best/average 산출)
bash server/scripts/run-claw-bench-ko.sh nvidia/nemotron-3-super-120b-a12b:free --runs 3

# judge 모델 변경
bash server/scripts/run-claw-bench-ko.sh nvidia/nemotron-3-super-120b-a12b:free \
  --judge modelstudio/glm-5

# dry-run (실제 실행 없이 태스크 목록만 확인)
bash server/scripts/run-claw-bench-ko.sh nvidia/nemotron-3-super-120b-a12b:free --dry-run
```

### CLI 옵션

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `<model_id>` | (필수) | 테스트 대상 모델. models.json의 ID 사용 |
| `--judge` | `azure-openai/gpt-5.3-chat` | judge 모델 (llm_judge/hybrid 태스크 채점용) |
| `--runs` | `1` | 반복 실행 횟수. 3회 이상 권장 (best/average 산출) |
| `--task` | 전체 | 특정 태스크만 실행 (쉼표 구분) |
| `--dry-run` | - | 태스크 목록만 출력, 실행하지 않음 |


## 3. 아키텍처

```
run-claw-bench-ko.sh
  │
  ├─ 모델 ID → OpenClaw 프로바이더 접두어 해석
  │   (nvidia/nemotron... → openrouter/nvidia/nemotron...)
  │
  └─ python3 runner.py --model ... --judge ... --runs ...
       │
       ├─ [1회] 에이전트 생성
       │   openclaw agents add clawbench-{model-slug}
       │     --model {model} --workspace /tmp/claw-bench-ko/{run_id}/workspace
       │
       ├─ [태스크 N × runs회 반복]
       │   ├─ 워크스페이스 초기화 (기존 파일 삭제 → 입력 파일 복사)
       │   │   └─ EUC-KR 인코딩 변환이 필요한 파일은 이 시점에 변환
       │   │
       │   ├─ 에이전트에 태스크 전송
       │   │   openclaw agent --agent clawbench-{slug}
       │   │     --session-id clawbench_{task_id}_{run}_{uuid}
       │   │     --message "{prompt}"
       │   │
       │   └─ 채점 (grader.py)
       │       ├─ automated → 체크 항목별 pass/fail → 통과율
       │       ├─ llm_judge → judge 에이전트 호출 → 0~100점
       │       └─ hybrid → automated×0.5 + judge×0.5
       │
       └─ 결과 집계 → results.json
           ├─ 태스크별: best_score, average_score, scores_per_run
           └─ 전체: overall_best_score, overall_average_score
```

### 에이전트 생성 시점

- **테스트 에이전트**: runner.py 시작 시 1회 생성. 모든 태스크가 이 에이전트를 공유하되, 태스크마다 세션 ID가 다르고 워크스페이스를 초기화하므로 태스크 간 간섭은 없다.
- **judge 에이전트**: 첫 번째 llm_judge/hybrid 태스크 채점 시점에 lazy 생성. automated-only 실행 시에는 생성되지 않는다.


## 4. 태스크 상세

### 4.1 addr_parse — 한국 주소 파싱

| 항목 | 값 |
|------|-----|
| 카테고리 | data_processing |
| 채점 | automated (체크 13개) |
| 타임아웃 | 120초 |
| 입력 | `addresses.txt` — 한국 주소 20개 |
| 출력 | `result.json` — 구조화된 주소 JSON 배열 |

에이전트가 비정형 한국 주소 텍스트를 읽고, 시/도·시군구·도로명·상세주소로 분리한 구조화 JSON을 생성해야 한다.

**입력 데이터 특성:**
- 시/도 약어 혼재: "서울시", "경기", "부산", "대전", "인천시" 등 → 모두 정식 명칭("서울특별시", "경기도" 등)으로 통일 요구
- 도로명주소와 지번주소 혼재: "테헤란로 152" vs "노형동 925-6"
- 복합 시군구: "성남시 분당구", "수원시 영통구", "창원시 성산구"
- 특별자치 행정구역: 세종특별자치시(시군구 없음), 제주특별자치도, 전북특별자치도
- 상세주소 다양성: 건물명, 동/호수, 층수, 쉼표 구분 등

**출력 스키마:**
```json
[
  {
    "original": "서울시 강남구 테헤란로 152 강남파이낸스센터",
    "sido": "서울특별시",
    "sigungu": "강남구",
    "road_or_dong": "테헤란로 152",
    "detail": "강남파이낸스센터"
  }
]
```

**채점 체크 항목:**
- `result.json` 존재, 유효한 JSON, 배열 길이 20
- 시/도 정식 명칭 변환 검증 (7개 샘플): 서울특별시, 경기도, 부산광역시, 대전광역시, 제주특별자치도, 세종특별자치시
- 시군구 검증 (2개 샘플): "성남시 분당구", "연수구"
- 첫 번째 요소가 5개 필수 필드를 모두 보유하는지

---

### 4.2 num_convert — 한글 숫자 변환

| 항목 | 값 |
|------|-----|
| 카테고리 | data_processing |
| 채점 | automated (체크 18개) |
| 타임아웃 | 120초 |
| 입력 | `numbers.txt` — 한국어 숫자 표현 15개 |
| 출력 | `result.json` — 정수 변환 결과 JSON 배열 |

한글 숫자, 아라비아-한글 혼합 표기, 단위 조합 등 다양한 한국어 숫자 표현을 정수로 변환한다.

**입력 데이터와 기대 정답:**

| # | 입력 | 기대 정수 | 난이도 |
|---|------|-----------|--------|
| 1 | 삼천이백만 | 32,000,000 | 순한글, 만 단위 |
| 2 | 1억 5천만 | 150,000,000 | 아라비아+한글 혼합, 억·만 |
| 3 | 오백삼십이 | 532 | 순한글, 소수 |
| 4 | 칠십구 | 79 | 순한글, 소수 |
| 5 | 3억 | 300,000,000 | 아라비아+한글 단위 |
| 6 | 백이십삼만 사천오백육십칠 | 1,234,567 | 순한글, 만 이하 세분화 |
| 7 | 이십일만 | 210,000 | 순한글, 만 단위 |
| 8 | 3만 5천 | 35,000 | 혼합, 천 단위 |
| 9 | 천 | 1,000 | 단일 단위 |
| 10 | 2조 3천억 | 2,300,000,000,000 | 조·억 대단위 |
| 11 | 12만 3천 | 123,000 | 아라비아+만+천 |
| 12 | 오천육백칠십팔만 | 56,780,000 | 순한글, 만 단위 |
| 13 | 팔만 구천 | 89,000 | 순한글, 만+천 |
| 14 | 사백오 | 405 | 순한글, 소수 |
| 15 | 2조 5600억 | 2,560,000,000,000 | 아라비아+조+억 |

**채점:** 15개 값 전부 정확히 일치해야 만점. 파일 존재·JSON 유효성·배열 길이 3개 + 값 비교 15개 = 총 18개 체크.

---

### 4.3 phone_normalize — 전화번호 정규화

| 항목 | 값 |
|------|-----|
| 카테고리 | data_processing |
| 채점 | automated (체크 13개) |
| 타임아웃 | 120초 |
| 입력 | `phones.txt` — 한국 전화번호 25개 |
| 출력 | `result.json` — 정규화된 전화번호 JSON 배열 |

한국 전화번호 체계를 이해하고, 다양한 입력 형식을 표준 형식으로 변환한다.

**정규화 규칙:**

| 번호 유형 | 식별 기준 | 출력 형식 | 예시 |
|-----------|-----------|-----------|------|
| 휴대폰 | 010 | +82-10-XXXX-XXXX | +82-10-1234-5678 |
| 서울 유선 | 02 | +82-2-XXXX-XXXX 또는 +82-2-XXX-XXXX | +82-2-1234-5678 |
| 지역 유선 | 031~064 | +82-XX-XXX(X)-XXXX | +82-31-123-4567 |
| 인터넷전화 | 070 | +82-70-XXXX-XXXX | +82-70-1234-5678 |
| 수신자부담 | 080 | +82-80-XXX-XXXX | +82-80-123-4567 |
| 대표번호 | 1588, 1577 등 | XXXX-XXXX (국제코드 없음) | 1588-1234 |

**입력 형식 다양성 (25개):**
- 하이픈 구분: `010-1234-5678`
- 붙여쓰기: `01012345678`
- 국제번호: `+82-10-1234-5678`, `+821012345678`, `82-10-...`
- 괄호: `02)1234-5678`, `(02) 1234-5678`
- 마침표: `010.1234.5678`
- 공백: `010 1234 5678`
- em dash: `010–1234��5678` (유니코드 U+2013)
- 대표번호: `1588-1234`, `1577-0000`, `1544-9999`, `1600-1234`

**채점:** 파일·JSON·배열 길이 3개 + 대표 샘플 값 비교 8개 + 필드 존재 1개 = 13개 체크.

---

### 4.4 csv_transform — 은행 거래 CSV 변환

| 항목 | 값 |
|------|-----|
| 카테고리 | data_processing |
| 채점 | **hybrid** (automated 50% + judge 50%) |
| 타임아웃 | 180초 |
| 입력 | `transactions.csv` — EUC-KR 인코딩 은행 거래 15건 |
| 출력 | `result.csv` — UTF-8 정규화된 CSV |

한국 레거시 시스템에서 흔한 EUC-KR 인코딩 CSV를 처리하는 태스크. 인코딩 변환, 날짜 형식 통일, 금액 정규화, 파생 컬럼 추가까지 복합적인 데이터 변환을 수행한다.

**입력 데이터 특성:**
- 인코딩: EUC-KR (runner가 UTF-8 원본을 EUC-KR로 변환하여 워크스페이스에 배치)
- 날짜 형식 3가지 혼재:
  - `2024.03.15` (마침표 구분)
  - `24/03/18` (2자리 연도, 슬래시)
  - `2024년 3월 20일` (한국어)
- 금액: `"3,500,000원"` (쉼표+원, 따옴표로 감싸짐)
- 빈 값: 입금 또는 출금 중 하나가 비어 있음

**변환 요구사항:**
1. EUC-KR → UTF-8
2. 날짜 → `YYYY-MM-DD` (ISO 8601)
3. 금액 → 정수 (쉼표·원 제거, 빈 칸→0)
4. `유형` 컬럼 추가 (입금 > 0이면 "입금", 출금 > 0이면 "출금")
5. 거래일자 기준 오름차순 정렬

**automated 체크 (7개, 50%):**
- 파일 존재, UTF-8 인코딩, 헤더 일치, 행 수 15, 날짜 패턴 정규식, 입금·출금 정수 여부

**judge 루브릭 (100점, 50%):**
- 인코딩 변환 정확성 25점, 날짜 형식 통일 25점, 금액 처리 25점, 유형 분류·정렬 25점

---

### 4.5 meeting_minutes — 회의록 작성

| 항목 | 값 |
|------|-----|
| 카테고리 | document_generation |
| 채점 | **llm_judge** (100점) |
| 타임아웃 | 180초 |
| 입력 | `transcript.txt` — 3인 비격식 대화 녹취록 |
| 출력 | `minutes.md` — 정식 한국 기업 회의록 |

비격식 한국어 구어체 대화를 읽고, 한국 기업에서 실제 사용하는 정식 회의록 형식으로 변환한다.

**대화 상황:**
- 참석자: 김민수(PM), 이지은(백엔드 리드), 박준혁(마케팅)
- 일시: 2024년 4월 3일 오후 2시, 본사 3층 회의실 B
- 안건: 모바일 앱 출시일, QA 일정, 마케팅 계획

**대화에서 도출되는 결정사항 (채점 핵심):**

| 결정사항 | 세부 |
|----------|------|
| 출시일 확정 | 4월 28일 (월) |
| QA 인력 보강 | 기존 2명 → 4명 (2명 추가 투입) |
| 마케팅 티저 시작 | 4월 14일부터 인스타그램+유튜브 숏츠 |

**후속 조치 (담당자/기한):**

| 담당자 | 조치 | 기한 |
|--------|------|------|
| 김민수 | QA 인력 투입 관련 팀장 보고 + 계획서 | 4월 8일 |
| 이지은 | 서버 부하테스트 일정 수립 및 결과 공유 | 4월 10일 |
| 박준혁 | 마케팅 티저 시안 준비 | 4월 7일 |

**judge 루브릭 (100점):**
- 형식 준수 25점: 회의록 필수 항목(일시, 장소, 참석자, 안건, 논의내용, 결정사항, 후속조치) 포함 여부
- 내용 완결성 30점: 3가지 결정사항 + 3명 후속조치 담당자/기한 + 우려사항(서버 용량, 결제 모듈)
- 한국어 품질 25점: 존댓말 일관성, 공문서체, 번역투 배제, 한국식 날짜 표기
- 구조화 수준 20점: 안건별 분리, 결정사항과 후속조치 구분, 레이아웃

---

### 4.6 biz_email — 비즈니스 이메일 작성

| 항목 | 값 |
|------|-----|
| 카테고리 | document_generation |
| 채점 | **llm_judge** (100점) |
| 타임아웃 | 180초 |
| 입력 | `context.txt` — 협력 제안 배경 정보 |
| 출력 | `email.txt` — 한국식 비즈니스 협력 제안 이메일 |

AI 물류 솔루션 회사(스마트플로우)가 빅데이터 분석 회사(한국데이터솔루션)에 공동 개발을 제안하는 비즈니스 이메일을 작성한다.

**context.txt에 제공되는 정보:**
- 우리 회사: 스마트플로우, 수요 예측 AI 정확도 94.2%, 시리즈 B 150억원 유치
- 파트너 회사: 한국데이터솔루션, 데이터 분석 10년 경력, AI사업부 최서영 부장
- 제안 배경: 물류 시장 AI 도입률 23%, 대형 물류사 3곳 수요 문의
- 단계별 계획: PoC(Proof of Concept, 2개월) → 고도화(4개월) → 시장 출시
- 기대 효과: 물류비 15~25% 절감, 2025년 공동 매출 30억원
- 일정: 1~2주 내 미팅, PoC 착수 6월 목표

**이메일 발신/수신:**
- 발신: 스마트플로우 AI기획팀 정하윤 과장
- 수신: 한국데이터솔루션 AI사업부 최서영 부장

**judge 루브릭 (100점):**
- 형식/구조 20점: 제목, 발수신 정보, 인사말→배경→제안→기대효과→일정→마무리 구조, 서명
- 내용 적절성 30점: context.txt 정보 반영, 구체적 제안, 수치 근거, 현실적 일정
- 한국어 비즈니스 어투 30점: 존댓말 일관성, "귀사"/"당사", 적절한 공손함, 직함 호칭
- 설득력 20점: 상호 이익 명시, 논리적 흐름, 다음 단계 제안

---

### 4.7 news_summary — 뉴스 브리핑 요약

| 항목 | 값 |
|------|-----|
| 카테고리 | document_generation |
| 채점 | **llm_judge** (100점) |
| 타임아웃 | 180초 |
| 입력 | `articles.txt` — 한국 반도체 산업 뉴스 3건 |
| 출력 | `summary.md` — 경영진 대상 통합 브리핑 (400~600자) |

동일 주제(한국 반도체 산업)의 뉴스 기사 3건을 읽고, 중복을 통합하여 경영진 보고서 문체로 요약한다.

**3개 기사 핵심 내용:**

| 기사 | 주제 | 핵심 수치 |
|------|------|-----------|
| 기사 1 | 정부 반도체 특별법 시행령 개정 | 투자세액공제 25%→35%, 중기 최대 40%, 7월 시행 |
| 기사 2 | 삼성·SK 올해 투자 | 삼성 50조원(평택 4기, 2nm GAA), SK 25조원(용인, HBM), 시장 2027년 1,200조원 |
| 기사 3 | HBM 경쟁 | SK 53% + 삼성 45% = 98% 점유, 마이크론·CXMT 추격, HBM4 양산 |

**채점에서 반드시 확인하는 수치:** 삼성 50조원, SK 25조원, 2027년 시장 규모 1,200조원, 세제 혜택 25%→35%, HBM(High Bandwidth Memory, 고대역폭 메모리) 점유율 98%.

**judge 루브릭 (100점):**
- 정확성 30점: 수치 왜곡/환각 없음, 고유명사 정확
- 완전성 25점: 3개 기사 핵심이 모두 반영됨
- 간결성 25점: 400~600자 준수, 중복 통합, 핵심만 전달
- 한국어 품질 20점: 존댓말 일관성, 보고서체, 번역투 없음

---

### 4.8 invoice_gen — 세금계산서 생성

| 항목 | 값 |
|------|-----|
| 카테고리 | korean_system |
| 채점 | **hybrid** (automated 50% + judge 50%) |
| 타임아웃 | 180초 |
| 입력 | `order.json` — 주문 데이터 (공급자/공급받는자 + 품목 3건) |
| 출력 | `invoice.json` — 한국 전자세금계산서 형식 JSON |

한국 세금계산서(부가가치세법 기반)의 필수 항목을 이해하고, 주문 데이터로부터 정확한 계산을 수행하여 세금계산서를 생성한다.

**주문 데이터:**

| 품목 | 규격 | 수량 | 단가(원) | 공급가액(원) | 세액(원) |
|------|------|------|----------|-------------|---------|
| IoT 센서 모듈 (온습도) | SHT-40A | 500 | 8,500 | 4,250,000 | 425,000 |
| GPS 트래커 | GT-200K | 200 | 12,000 | 2,400,000 | 240,000 |
| 산업용 게이트웨이 | GW-LTE-100 | 50 | 25,000 | 1,250,000 | 125,000 |
| **합계** | | | | **7,900,000** | **790,000** |

합계금액 = 7,900,000 + 790,000 = **8,690,000원**

계산 규칙: 공급가액 = 수량 × 단가, 세액 = 공급가액 × 10% (원 미만 절사)

**automated 체크 (9개, 50%):**
- 파일 존재, JSON 유효, 4개 필수 키(supplier, buyer, items, total) 존재
- 합계 수치 3개 정확히 일치: supply_amount=7,900,000, tax_amount=790,000, total_amount=8,690,000

**judge 루브릭 (100점, 50%):**
- 계산 정확성 40점, 세금계산서 형식 준수 30점, 데이터 정합성 30점

---

### 4.9 resume_parse — 이력서 파싱

| 항목 | 값 |
|------|-----|
| 카테고리 | korean_system |
| 채점 | **hybrid** (automated 50% + judge 50%) |
| 타임아웃 | 180초 |
| 입력 | `resume.txt` — 한국식 이력서 텍스트 |
| 출력 | `result.json` — 구조화된 이력서 JSON |

한국식 이력서의 비정형 텍스트(━ 구분선, 띄어쓰기 정렬, 한국식 날짜 등)를 파싱하여 구조화된 JSON으로 변환한다.

**이력서 주인공: 이서준**
- 생년월일: 1995-03-22
- 연락처: 010-9876-5432
- 학력: 한양대 컴퓨터소프트웨어학부 학사(졸업), KAIST 전산학부 석사(수료)
- 경력: 네이버 AI Lab 연구원(2021.03~2023.06), 카카오 AI 플랫폼팀 시니어 엔지니어(2023.07~현재)
- 자격증: 정보처리기사, SQLD(SQL Developer, SQL 개발자), TOEIC 935점, AWS SAA(Solutions Architect Associate)
- 병역: 육군 병장 만기전역

**날짜 표기 다양성 (파싱 난이도):**
- `2014.03 ~ 2018.08` — 마침표 구분
- `2019년 3월 ~ 2021년 2월` — 한국어 표기
- `2023년 7월 ~ 현재` — "현재" 처리 필요

**automated 체크 (11개, 50%):**
- 파일 존재, JSON 유효
- name="이서준", birth_date="1995-03-22"
- education/experience/certifications/skills 필드 존재
- education 2건 이상, experience 2건 이상, certifications 3건 이상

**judge 루브릭 (100점, 50%):**
- 추출 정확도 40점, 날짜 처리 20점, 한국 이력서 이해 20점, 데이터 품질 20점

---

### 4.10 regulation_extract — 법규 요구사항 추출

| 항목 | 값 |
|------|-----|
| 카테고리 | korean_system |
| 채점 | **hybrid** (automated 50% + judge 50%) |
| 타임아웃 | 180초 |
| 입력 | `regulation.txt` — 개인정보 보호법 제15·17·20·21·22조 |
| 출력 | `checklist.json` — 의무사항/금지사항 체크리스트 |

한국 법률의 조항 구조(조·항·호)를 이해하고, 의무사항(obligation)과 금지사항(prohibition)을 분류하여 구조화된 체크리스트를 생성한다.

**제공되는 법률 조항과 추출 대상:**

| 조항 | 추출 대상 | 분류 |
|------|-----------|------|
| 제15조 ① | 개인정보 수집 시 정보주체 동의 획득 | obligation |
| 제15조 ② | 동의 시 4가지 사항(목적, 항목, 기간, 거부권) 고지 | obligation |
| 제17조 ① | 제3자 제공 시 정보주체 동의 획득 | obligation |
| 제17조 ② | 제3자 제공 동의 시 5가지 사항 고지 | obligation |
| 제20조 ① | 정보주체 이외 수집 시 출처·목적·정지요구권 고지 | obligation |
| 제21조 ① | 불필요한 개인정보 지체 없이 파기 | obligation |
| 제21조 ② | 파기 시 복구 불가능하도록 조치 | obligation |
| 제22조 ① | 동의 사항 각각 구분하여 명확히 고지 후 개별 동의 | obligation |
| 제22조 ④ | 선택 동의 거부를 이유로 서비스 제공 거부 금지 | prohibition |
| 제22조 ⑤ | 동의 거부 가능하다는 사실 고지 | obligation |

**출력 스키마:**
```json
{
  "items": [
    {
      "article": "제15조 제1항",
      "type": "obligation",
      "subject": "개인정보처리자",
      "requirement": "개인정보 수집·이용 시 정보주체의 동의를 받아야 한다",
      "condition": "법률에 특별한 규정이 있는 경우 등 예외 존재",
      "penalty_reference": null
    }
  ]
}
```

**automated 체크 (5개, 50%):**
- 파일 존재, JSON 유효, items 필드 존재
- items 배열 8개 이상 (최소 기대 추출 수)
- 모든 항목이 필수 필드(article, type, subject, requirement) 보유

**judge 루브릭 (100점, 50%):**
- 추출 완전성 35점, 분류 정확도 25점, 요약 품질 20점, 구조화 수준 20점


## 5. 파일 구조

```
server/claw-bench-ko/
├── manifest.json          ← 태스크 레지스트리 (10개 태스크 메타데이터)
├── runner.py              ← 메인 실행기 (에이전트 생성, 태스크 실행, 결과 집계)
├── grader.py              ← 채점 엔진 (automated 13종 체크 + judge 호출 + hybrid 결합)
├── tasks/
│   ├── addr_parse/
│   │   ├── task.json      ← 태스크 정의 (프롬프트, 채점 기준, 기대 정답)
│   │   └── input/
��   │       └── addresses.txt
│   ├── num_convert/
│   │   ├── task.json
│   │   └── input/
│   │       └── numbers.txt
│   ├── phone_normalize/
│   │   ├── task.json
│   │   └── input/
│   │       └── phones.txt
│   ├── csv_transform/
│   │   ├── task.json
│   │   └── input/
│   │       └── transactions.csv   ← UTF-8 저장, runner가 EUC-KR로 변환하여 제공
│   ├── meeting_minutes/
│   │   ├── task.json
│   │   └── input/
│   │       └── transcript.txt
│   ├── biz_email/
│   │   ├── task.json
│   │   └── input/
│   │       └── context.txt
│   ├── news_summary/
│   │   ├── task.json
│   │   └── input/
│   │       └── articles.txt
│   ├── invoice_gen/
│   │   ├── task.json
│   │   └── input/
│   │       └── order.json
│   ├── resume_parse/
│   │   ├── task.json
│   │   └── input/
│   │       └── resume.txt
│   └── regulation_extract/
│       ├── task.json
│       └── input/
│           └── regulation.txt
└── results/               ← 실행 결과 (gitignored)

server/scripts/
└── run-claw-bench-ko.sh   ← 셸 래퍼 (모델 ID 해석, 환경 설정)
```


## 6. 채점 시스템 상세

### 6.1 automated 체크 타입

grader.py에 구현된 13종 체크:

| 체크 타입 | 용도 | 파라미터 |
|-----------|------|----------|
| `file_exists` | 출력 파일 존재 확인 | `path` |
| `json_valid` | JSON 파싱 가능 여부 | `path` |
| `json_array_length` | 배열 길이 정확히 N | `path`, `expected` |
| `json_array_min_length` | 배열 길이 최소 N | `path`, `field`, `min` |
| `json_field_equals` | 특정 필드 값 일치 | `path`, `field`, `expected` |
| `json_field_exists` | 특정 필드 존재 | `path`, `field` |
| `json_has_fields` | 배열 첫 요소가 필수 필드 보유 | `path`, `fields[]` |
| `json_items_have_fields` | 배열 전체 요소가 필수 필드 보유 | `path`, `field`, `required_fields[]` |
| `encoding_is` | 파일 인코딩 확인 | `path`, `expected` |
| `csv_header_equals` | CSV 첫 행(헤더) 일치 | `path`, `expected` |
| `csv_row_count` | CSV 데이터 행 수 (헤더 제외) | `path`, `expected` |
| `csv_field_matches_pattern` | CSV 특정 컬럼이 정규식 패턴 만족 | `path`, `column`, `pattern` |
| `csv_field_is_integer` | CSV 특정 컬럼이 정수 파싱 가능 | `path`, `column` |

`json_field_equals`의 `field` 파라미터는 경로 표현을 지원한다: `[0].sido`, `total.supply_amount`, `items[2].name` 등.

### 6.2 llm_judge 프로세스

1. 워크스페이스의 모든 출력 파일 내용을 수집 (파일당 최대 5,000자)
2. 에이전트 응답 텍스트 수집 (최대 3,000자)
3. 태스크별 루브릭 + 수집된 내용으로 judge 프롬프트 구성
4. judge 에이전트(`clawbench-judge-{slug}`)에 전송
5. 응답에서 JSON 추출: `{"score": 0~100, "breakdown": {...}, "feedback": "..."}`
6. score를 100으로 나누어 0.0~1.0으로 변환

JSON 추출 실패 시 fallback: ```json``` 블록 → 중괄호 블록 → "score" 숫자만 추출 → 0점

### 6.3 hybrid 결합

`combined_score = automated_score × weight_auto + judge_score × weight_judge`

모든 hybrid 태스크의 가중치는 automated 0.5, judge 0.5이다.

### 6.4 best/average 산출

`--runs N`으로 N회 반복 실행 시:
- **best_score**: N회 중 최고 점수
- **average_score**: N회 평균 점수
- 태스크별로 독립 산출, 전체 점수는 태스크별 best/average의 평균


## 7. 결과 JSON 형식

```json
{
  "benchmark": "claw-bench-ko",
  "version": "1.0.0",
  "model": "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
  "judge": "azure-openai/gpt-5.3-chat",
  "timestamp": "2026-04-05T10:00:00Z",
  "runs_per_task": 3,
  "overall_best_score": 0.72,
  "overall_average_score": 0.65,
  "total_duration_seconds": 1847.3,
  "tasks": [
    {
      "task_id": "addr_parse",
      "name": "한국 주소 파싱",
      "category": "data_processing",
      "grading_type": "automated",
      "best_score": 0.846,
      "average_score": 0.769,
      "scores_per_run": [0.769, 0.846, 0.692],
      "runs": 3,
      "best_run": { "..." },
      "average_duration_seconds": 45.2
    }
  ],
  "summary": {
    "total": 10,
    "by_category": {
      "data_processing": 4,
      "document_generation": 3,
      "korean_system": 3
    },
    "by_grading_type": {
      "automated": 4,
      "llm_judge": 3,
      "hybrid": 3
    }
  }
}
```

이 결과는 `normalize.py`가 읽어서 리더보드에 통합한다. `results/raw/korean/` 디렉토리에 `{model_slug}_{timestamp}.json` 형식으로 저장된다.


## 8. PinchBench와의 비교

| 항목 | PinchBench | ClawBench-KO |
|------|------------|-------------|
| 태스크 수 | 24 | 10 |
| 언어 | 영어 | 한국어 |
| 도메인 | 범용 소프트웨어 엔지니어링 | 한국어 데이터·문서·시스템 |
| 채점 유형 | automated 9 + llm_judge 7 + hybrid 8 | automated 4 + llm_judge 3 + hybrid 3 |
| runner | PinchBench 자체 (benchmark.py) | 자체 구현 (runner.py) |
| 에이전트 | `openclaw agent` 서브프로세스 | 동일 |
| judge | OpenClaw judge 에이전트 | 동일 |
| 기본 judge 모델 | claude-opus-4.5 | GPT-5.3-chat |
| 예상 소요 시간 | 40~60분 (24 태스크) | 15~40분 (10 태스크) |
| 비용 (무료 모델) | judge 호출만 발생 | 동일 |
