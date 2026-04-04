# OpenClaw LLM 백엔드 선정 조사: GLM-5 · Qwen 3.5 · Nemotron

> 조사 일자: 2026-04-03
> 목적: OpenClaw에서 GLM-5 / Qwen 3.5 / Nemotron을 LLM 백엔드로 사용한 24시간 구동의 기술적 타당성 검증 및 성능·비용 비교

---

## 1. OpenClaw + GLM-5 호환성

### 1.1 공식 지원 여부

OpenClaw은 v2026.2.21부터 GLM-5를 **공식 지원**한다. 내장 `zai` provider를 통해 Z.AI(智谱AI, Zhipu AI) 모델에 접근하며, 지원 모델 목록은 다음과 같다.

| 모델 ID | 용도 |
|---------|------|
| `zai/glm-5.1` | GLM-5 후속 업그레이드 (2026-03-27 출시, 코딩 28% 향상) |
| `zai/glm-5` | 플래그십 기반 모델 |
| `zai/glm-5v-turbo` | 멀티모달(이미지/비디오) 지원 |
| `zai/glm-4.7` | 경량 모델 |
| `zai/glm-4.6` | 경량 모델 |

출처: [OpenClaw Provider Docs](https://docs.openclaw.ai/providers/glm), [릴리스 노트](https://blog.meetneura.ai/openclaw-2026-2-21/)

### 1.2 API 호환성

GLM-5는 OpenAI SDK의 `chat.completions` 인터페이스와 **완전 호환**된다.

- `system`/`user`/`assistant` 역할 구분
- 스트리밍 출력
- Function calling / tool 호출 (OpenAI `tools` 파라미터 형식)
- 구조화된 JSON 출력

API 엔드포인트: `https://api.z.ai/api/paas/v4/chat/completions` (Bearer 토큰 인증)

출처: [Z.AI 개발자 문서](https://docs.z.ai/guides/llm/glm-5)

### 1.3 설정 방법

```bash
# Step 1: Z.AI API 키 발급 (https://bigmodel.cn 가입)
# GLM-5 접근에는 GLM Coding Plan Pro 이상 구독 필요

# Step 2: OpenClaw 온보딩
openclaw onboard --auth-choice zai-api-key

# Step 3: ~/.openclaw/openclaw.json 설정
```

```json
{
  "env": { "ZAI_API_KEY": "sk-..." },
  "agents": {
    "defaults": {
      "model": {
        "primary": "zai/glm-5"
      }
    }
  }
}
```

```bash
# Step 4: 재시작 및 확인
openclaw gateway restart
openclaw tui
```

OpenRouter 경유도 가능하다. 모델 ID는 `z-ai/glm-5-turbo`를 사용한다.

출처: [Z.AI OpenClaw 연동 문서](https://docs.z.ai/devpack/tool/openclaw), [OpenRouter 가이드](https://blog.wordupr.com/post/openclaw-connect-kimi-glm-5-minimax-via-openrouter/)

### 1.4 알려진 이슈

| 이슈 | 설명 | 상태 |
|-----|------|------|
| [#15716](https://github.com/openclaw/openclaw/issues/15716) | 메인 에이전트를 GLM-5로 전환 시 요청에 5 토큰만 전송되는 버그. 서브 에이전트에서는 정상 동작 | 미해결 (2026-04 기준) |
| [#14352](https://github.com/openclaw/openclaw/issues/14352) | `Unknown model: zai/glm-5` — 모델 목록 하드코딩 문제 | v2026.2.21에서 해결 |
| [#14589](https://github.com/openclaw/openclaw/issues/14589) | 동적 모델 디스커버리 미지원 (새 GLM 버전 출시 시 코드 업데이트 필요) | 진행 중 |

**#15716이 현재 가장 심각한 블로커**다. 메인 에이전트로 GLM-5 사용이 불안정할 수 있으며, `openclaw doctor --deep --yes` 실행으로 일부 설정 문제를 자동 수정할 수 있다.

출처: [GitHub Issues](https://github.com/openclaw/openclaw/issues/15716), [haimaker.ai](https://haimaker.ai/blog/glm-5-openclaw/)

---

## 2. GLM-5 모델 사양

### 2.1 모델 패밀리

GLM-5는 Z.AI(智谱AI)가 2026-02-11에 출시한 MoE(Mixture of Experts) 아키텍처 모델이다. 256개 전문가 중 토큰당 8개 활성화(5.9% 희소성), 사전학습 데이터 28.5T 토큰, Huawei Ascend 칩에서 학습(NVIDIA GPU 미사용), MIT 라이선스로 공개.

| 변형 | 파라미터 | 활성 파라미터 | 컨텍스트 윈도우 | 최대 출력 | 입력 타입 | 출시일 |
|-----|---------|------------|-------------|---------|---------|-------|
| **GLM-5** | 744B | 40B | 200K 토큰 | 128K 토큰 | 텍스트 | 2026-02-11 |
| **GLM-5-Turbo** | 744B | 40B | 203K 토큰 | 128K 토큰 | 텍스트 | 2026-02-11 |
| **GLM-5-Code** | 744B | 40B | 200K 토큰 | 128K 토큰 | 텍스트 | 2026-02-11 |
| **GLM-5.1** | 744B | 40B | 200K 토큰 | 128K 토큰 | 텍스트 | 2026-03-27 |
| **GLM-5V-Turbo** | 744B | 40B | 200K 토큰 | 128K 토큰 | 텍스트+이미지+비디오 | 2026-04-01 |

출처: [Hugging Face GLM-5](https://huggingface.co/zai-org/GLM-5), [arXiv 논문](https://arxiv.org/html/2602.15763v1)

### 2.2 API 가격 (USD, 1M 토큰 기준)

| 모델 | 입력 | 캐시 입력 | 출력 |
|-----|------|---------|------|
| GLM-5 | $1.00 | $0.20 | $3.20 |
| GLM-5-Turbo | $1.20 | $0.24 | $4.00 |
| GLM-5-Code | $1.20 | $0.30 | $5.00 |
| GLM-4.7-Flash | 무료 | — | 무료 |
| GLM-4.5-Flash | 무료 | — | 무료 |

GLM-5 API 접근 경로는 2가지다:

| 방식 | 월 고정비 | 토큰당 비용 | OpenClaw 설정 |
|-----|---------|-----------|-------------|
| **GLM Coding Plan Pro** (구독) | ~$20/월 | $0 (한도 내) | `zai-coding-global` |
| **일반 API** (종량제) | $0 | $1.00 입력 / $3.20 출력 | `zai-global` |

Coding Plan은 OpenClaw 작업에 대해 Coding Agent보다 낮은 우선순위를 적용하며, 부하 시 동적 큐잉/속도 제한이 발생한다. 일반 API는 이 제약이 없다. 초기에는 종량제로 시작해 사용량 확인 후 결정하는 것이 합리적이다.

출처: [Z.AI 가격 페이지](https://docs.z.ai/guides/overview/pricing), [OpenRouter](https://openrouter.ai/z-ai/glm-5), [Serenities AI 리뷰](https://serenitiesai.com/articles/glm-5-1-coding-plan-review-2026)

---

## 3. Qwen 3.5/3.6 모델 패밀리

### 3.1 버전 구분

Qwen(通义千问)은 Alibaba Cloud의 LLM 시리즈다. 2026-04 기준 최신 세대는 **Qwen 3.5**(2026-02-16 출시)와 **Qwen 3.6-Plus Preview**(2026-03-30 출시)다.

혼동하기 쉬운 명칭을 정리하면:

| 이름 | 정체 | 가중치 공개 | 라이선스 |
|-----|------|-----------|---------|
| **Qwen 3.5** | 오픈 웨이트 모델 세대 (0.8B~397B, 8종) | O | Apache 2.0 |
| **Qwen 3.5-Plus** | 비공개 API 전용 모델. 3.5 세대의 상위 변형 | X | API 전용 |
| **Qwen 3.6-Plus Preview** | 비공개 API 전용 모델. 3.6 세대의 Preview 버전. 오픈 웨이트 3.6은 미출시 | X | API 전용 (Preview 기간 무료) |

Qwen 3 → 3.5 → 3.6은 소수점 증분이며, 정수 점프(4.0 등)는 2026-04 기준 없다.

출처: [GitHub QwenLM/Qwen3.5](https://github.com/QwenLM/Qwen3.5), [Wikipedia - Qwen](https://en.wikipedia.org/wiki/Qwen)

### 3.2 Qwen 3.5 오픈 웨이트 모델

| 모델 | 총 파라미터 | 활성 파라미터 | 아키텍처 | 컨텍스트 윈도우 | 출시일 |
|-----|---------|------------|---------|-------------|-------|
| Qwen3.5-397B-A17B | 397B | 17B | MoE | 262K 토큰 | 2026-02-16 |
| Qwen3.5-122B-A10B | 122B | 10B | MoE | 262K 토큰 | 2026-02-24 |
| Qwen3.5-35B-A3B | 35B | 3B | MoE | 262K 토큰 | 2026-02-24 |
| **Qwen3.5-27B** | **27B** | **27B (전체 활성)** | **Dense** | **262K 토큰** | **2026-02-24** |
| Qwen3.5-9B | 9B | 9B | Dense | 262K 토큰 | 2026-03-02 |
| Qwen3.5-4B | 4B | 4B | Dense | 262K 토큰 | 2026-03-02 |
| Qwen3.5-2B | 2B | 2B | Dense | 262K 토큰 | 2026-03-02 |
| Qwen3.5-0.8B | 0.8B | 0.8B | Dense | 262K 토큰 | 2026-03-02 |

공통 특성: GDN(Gated Delta Networks, 선형 어텐션) + 표준 어텐션 하이브리드, SwiGLU 활성화, RMSNorm, 사전학습 단계부터 비전 통합(early-fusion multimodal), 201개 언어 지원.

출처: [Hugging Face Qwen3.5-27B](https://huggingface.co/Qwen/Qwen3.5-27B), [Hugging Face Qwen3.5-397B-A17B](https://huggingface.co/Qwen/Qwen3.5-397B-A17B)

### 3.3 PinchBench 4위: Qwen3.5-27B

PinchBench 리더보드에서 **Qwen3.5-27B는 90.0% 최고 점수로 4위**를 기록했다. 27B Dense 모델이 397B MoE 플래그십(89.1%, 7위)보다 높은 점수를 기록한 점이 주목할 만하다.

| 지표 | Qwen3.5-27B | Qwen3.5-397B-A17B | Qwen3.6-Plus Preview |
|-----|------------|-------------------|---------------------|
| PinchBench 최고 점수 | 90.0% (4위) | 89.1% (7위) | 88.6% (9위) |
| PinchBench 평균 점수 | 78.5% | 80.4% | 84.0% |
| 실행 시간 | 1,184 sec | 1,110 sec | 1,356 sec |
| 실행 비용 | $0.50 | $0.99 | $0 (Preview 무료) |
| SWE-bench Verified | 72.4% | — | — |
| MMLU-Pro | 86.1% | — | — |

비용 효율 관점: Qwen3.5-27B는 $0.50/run으로 상위 4개 모델 중 가장 저렴하다. Claude Opus 4.6($4.08) 대비 8.2배 저렴하면서 3.3%p 차이.

출처: [PinchBench Leaderboard](https://pinchbench.com/)

### 3.4 Qwen3.5-Plus와 Qwen3.6-Plus Preview

| 지표 | Qwen3.5-Plus | Qwen3.6-Plus Preview |
|-----|-------------|---------------------|
| 파라미터 | 비공개 (397B-A17B 이상으로 추정) | 비공개 |
| 컨텍스트 윈도우 | 1,000,000 토큰 | 1,000,000 토큰 |
| 최대 출력 | 65,536 토큰 | 65,536 토큰 |
| 모달리티 | 텍스트 + 도구 호출 | 텍스트 전용 |
| 추론 모드 | 선택적 | 상시 CoT(Chain of Thought) |
| 가중치 공개 | X | X |
| 가격 (입력/출력 per 1M tokens) | $0.40 / $2.40 (글로벌) | 무료 (Preview) |

Qwen3.6-Plus Preview는 에이전틱 코딩에 최적화되었으나, Preview 상태이므로 API 안정성·가격 확정이 미정이다.

출처: [OpenRouter Qwen3.5-Plus](https://openrouter.ai/qwen/qwen3.5-plus-02-15), [BuildFastWithAI Qwen 3.6 Review](https://www.buildfastwithai.com/blogs/qwen-3-6-plus-preview-review)

### 3.5 OpenClaw 호환성

OpenClaw은 Qwen을 **공식 지원**한다. `qwen` provider를 통해 Alibaba Cloud Model Studio(DashScope) API에 접속한다.

```bash
# 온보딩 (글로벌 엔드포인트)
openclaw onboard --auth-choice modelstudio-api-key

# ~/.openclaw/openclaw.json 설정
```

```json
{
  "env": { "MODELSTUDIO_API_KEY": "sk-..." },
  "agents": {
    "defaults": {
      "model": {
        "primary": "qwen/qwen3.5-27b"
      }
    }
  }
}
```

**DashScope OpenAI 호환 엔드포인트**: `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` — OpenAI SDK `chat.completions` 형식과 호환. 스트리밍, Function calling(`tools` 파라미터), JSON 출력 지원.

**대안 접속 경로**: OpenRouter(`qwen/qwen3.5-plus`), Together AI, Fireworks AI, 셀프 호스팅(vLLM/Ollama/SGLang).

출처: [OpenClaw Qwen Provider Docs](https://docs.openclaw.ai/providers/qwen), [Alibaba Cloud Model Studio OpenClaw Guide](https://www.alibabacloud.com/help/en/model-studio/openclaw), [Alibaba Cloud OpenAI Compatibility](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope)

### 3.6 API 가격 (USD, 1M 토큰 기준)

| 모델 | 입력 | 출력 | 비고 |
|-----|------|------|------|
| Qwen3.5-Plus (글로벌/싱가포르) | $0.40 | $2.40 | Non-thinking, ≤256K 토큰 |
| Qwen3.5-Plus (중국/베이징) | $0.115 | $0.688 | Non-thinking, ≤128K 토큰 |
| Qwen3.5-Flash (글로벌) | $0.10 | $0.40 | ≤1M 토큰 |
| Qwen3.5-Flash (미국/독일) | $0.029 | $0.287 | ≤128K 토큰 |
| Qwen3.6-Plus Preview | 무료 | 무료 | Preview 기간 한정. 프로덕션 가격 미정 |
| Qwen3.5-27B (셀프 호스팅) | — | — | 하드웨어 비용만 발생 |

DashScope 신규 가입 시 글로벌 모델에 대해 1M 토큰 무료 크레딧(90일 유효)이 제공된다.

출처: [Alibaba Cloud Model Studio Pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing), [OpenRouter Qwen3.5-Plus Pricing](https://openrouter.ai/qwen/qwen3.5-plus-02-15/pricing)

### 3.7 알려진 이슈

| 이슈 | 설명 | 대응 |
|-----|------|------|
| `reasoning` 파라미터 버그 | 모든 Qwen 모델에서 `reasoning`을 `true`로 설정하면 응답이 빈 문자열로 반환됨 | OpenClaw 설정에서 `reasoning: false` 명시 필수 |
| Qwen OAuth 제거 (#49557) | `portal.qwen.ai` 경유 인증(qwen-portal) 방식이 폐지됨 | Model Studio API 키 방식 사용 |
| 메인 에이전트 안정성 | GLM-5의 #15716과 유사하게, 비-OpenAI provider를 메인 에이전트로 설정 시 토큰 전송 불완전 가능성 | 서브 에이전트로 우선 테스트 후 메인 에이전트 전환 |

출처: [GitHub Gist - Qwen empty response fix](https://gist.github.com/TheAIHorizon/37c30e375f2ce08e726e4bb6347f26b1), [OpenClaw Qwen Provider Docs](https://docs.openclaw.ai/providers/qwen)

---

## 4. NVIDIA NemoClaw

### 3.1 NemoClaw의 정체

NemoClaw은 별도의 AI 모델이나 경쟁 에이전트가 **아니다**. OpenClaw 위에 NVIDIA가 보안/거버넌스/배포 제어를 추가한 **오픈소스 참조 스택**(Apache 2.0 라이선스)이다.

- 발표: 2026-03-16, NVIDIA GTC(GPU Technology Conference)에서 Jensen Huang이 발표
- 상태: Alpha / Early Preview (프로덕션 미준비, API/동작 변경 가능)
- GitHub: [NVIDIA/NemoClaw](https://github.com/NVIDIA/NemoClaw)

NemoClaw이 만들어진 배경: OpenClaw의 ClawHub 마켓플레이스에서 **900개 악성 패키지(전체 게시 Skills의 20%)** 가 발견됨(Bitdefender 보고). "ClawHavoc" 캠페인만으로 335개 악성 Skill이 API 키 탈취 및 원격 코드 실행을 수행. NemoClaw의 샌드박스가 이 위험을 차단한다.

출처: [NVIDIA NemoClaw 공식](https://www.nvidia.com/en-us/ai/nemoclaw/), [TechCrunch](https://techcrunch.com/2026/03/16/nvidias-version-of-openclaw-could-solve-its-biggest-problem-security/)

### 3.2 NemoClaw의 기능

| 기능 | 설명 |
|-----|------|
| **OpenShell 런타임** | 각 OpenClaw 에이전트를 격리된 Docker 컨테이너(Landlock + seccomp + netns)에서 실행 |
| **프라이버시 라우터** | 정책 기반으로 로컬 Nemotron 모델 vs 클라우드 프론티어 모델 자동 라우팅 |
| **YAML 정책 제어** | 파일시스템 접근, 네트워크 송신(허용목록), 프로세스 권한 세밀 제어 |

### 3.3 Nemotron 모델 패밀리

| 모델 | 파라미터 | 활성 파라미터 | 컨텍스트 | 아키텍처 | 출시 |
|-----|---------|------------|---------|---------|------|
| **Nemotron 3 Nano** | 31.6B | 3.2B | 1M 토큰 | Hybrid Mamba-Transformer MoE | 2025-12-15 |
| **Nemotron 3 Super** | 120B | 12B | 1M 토큰 | Hybrid Mamba-Transformer MoE | 2026-03 (GTC) |
| **Nemotron 3 Ultra** | 550B | ~55B | 1M 토큰 | Hybrid Mamba-Transformer MoE | 2026 H1 예정 |

Nemotron 3 Super 특징: NVFP4로 25T 토큰 학습, Multi-token Prediction(구조화 생성 3배 속도), Latent MoE(동일 연산 비용으로 전문가 4배 확장), 442 tokens/sec 처리 속도.

출처: [NVIDIA Developer Blog](https://developer.nvidia.com/blog/introducing-nemotron-3-super-an-open-hybrid-mamba-transformer-moe-for-agentic-reasoning/), [NVIDIA Newsroom](https://nvidianews.nvidia.com/news/nvidia-debuts-nemotron-3-family-of-open-models)

---

## 5. 벤치마크 체계

### 5.1 OpenClaw 특화 벤치마크

OpenClaw 에이전트의 LLM(Large Language Model) 백엔드 성능을 측정하는 데 사용할 수 있는 벤치마크는 3단계로 나뉜다.

#### Tier 1: PinchBench (권장, 1순위)

Kilo.ai가 개발한 OpenClaw 에이전트 전용 벤치마크. 23개 실제 작업(파일 조작, 데이터 분석, 웹 조사, 스케줄링, 코딩 등)을 측정하며, 성공률/실행 시간/비용을 동시에 추적한다.

**2026년 3~4월 기준 PinchBench 리더보드 (상위 10):**

| 순위 | 모델 | 최고 점수 | 평균 점수 | 실행 시간(sec) | 비용(USD) |
|-----|------|---------|---------|-------------|----------|
| 1 | Claude Opus 4.6 | 93.3% | 83.1% | 1,357 | $4.08 |
| 2 | Arcee Trinity Large Thinking | 91.9% | 91.9% | 678 | $0 |
| 3 | GPT-5.4 | 90.5% | 81.7% | 1,247 | $1.57 |
| **4** | **Qwen3.5-27B** | **90.0%** | **78.5%** | **1,184** | **$0.50** |
| 5 | MiniMax M2.7 | 89.8% | 83.2% | 1,397 | $0 |
| 6 | Claude Haiku 4.5 | 89.5% | 78.1% | 838 | $0.72 |
| **7** | **Qwen3.5-397B-A17B** | **89.1%** | **80.4%** | **1,110** | **$0.99** |
| 8 | Xiaomi Mimo V2 Flash | 88.8% | 70.2% | 1,368 | $0.27 |
| **9** | **Qwen3.6-Plus Preview** | **88.6%** | **84.0%** | **1,356** | **$0** |
| 10 | Nemotron 3 Super 120B | 88.6% | 75.5% | 2,373 | $0 |

Qwen 모델이 상위 10에 3개 진입(4위, 7위, 9위). GLM-5는 PinchBench 상위 10에 없으나, GLM 4.7이 커뮤니티 투표 2위를 차지하고 있다. GLM-5의 PinchBench 성능은 직접 측정이 필요하다.

출처: [PinchBench](https://pinchbench.com/), [GitHub](https://github.com/pinchbench/skill)

#### Tier 2: WildClawBench (난이도 최상)

InternLM이 개발한 60개 실전 작업 기반 벤치마크. 실제 OpenClaw 환경에서 bash, 파일시스템, 브라우저, 이메일, 캘린더를 사용한다. 모든 프론티어 모델이 0.55/1.0 미만을 기록하며, Claude Opus 4.6가 복잡한 멀티스텝 코딩 작업에서 선두.

출처: [InternLM/WildClawBench](https://github.com/InternLM/WildClawBench)

#### Tier 3: AgentBench Skill (내장)

OpenClaw에 내장된 벤치마크 Skill. 40개 작업, 4계층 채점(구조 검증 → 메트릭 분석 → 행동 분석 → 출력 품질). `/benchmark` 명령으로 실행.

출처: [DEV.to 가이드](https://dev.to/aloycwl/understanding-the-agentbench-skill-benchmarking-your-openclaw-ai-agents-41nd)

### 5.2 범용 AI Agent 벤치마크

| 벤치마크 | 측정 대상 | 규모 | 비고 |
|---------|---------|------|------|
| **SWE-bench Verified** | 소프트웨어 엔지니어링 (GitHub 이슈 해결) | 2,294개 | 코딩 능력의 사실상 표준. 오염(contamination) 우려 존재 |
| **GAIA** | 범용 AI 어시스턴트 (멀티스텝 추론, 도구 사용) | 466개 | 인간 92%, 최고 AI 85%+ (Level 1) |
| **BFCL v4** | Function Calling / 도구 호출 정확도 | ~2,000개 | AST 기반 평가. 멀티턴 컨텍스트 관리에서 모델 간 격차 큼 |
| **WebArena** | 웹 기반 작업 (전자상거래, CMS 등) | 812개 | 인간 78%, 최고 AI 61.7% |
| **OSWorld** | OS 수준 GUI 작업 (Ubuntu/Windows) | 369개 | 인간 72%, 최고 AI 38% |
| **TAU-bench** | 멀티턴 에이전트-사용자-도구 상호작용 | 다양 | 단일 턴 90%+ → 전체 대화 성공률 10-15%로 급락 |

### 5.3 종합 리더보드

| 리더보드 | 방법론 | 측정 항목 |
|---------|-------|---------|
| **Chatbot Arena (LMSys)** | 크라우드소싱 쌍대 비교, Bradley-Terry 모델 + Elo 레이팅 | 인간 선호도 |
| **Artificial Analysis** | 72시간 동안 일 8회 자동 측정 | 지능(복합 벤치마크), 속도(tokens/sec), 레이턴시(TTFT), 가격 |
| **SEAL (Scale AI)** | 전문가 주도 비공개 평가 | 도구 사용, 코딩, 수학, 지시 따르기 |

---

## 6. GLM-5 vs Qwen 3.5 vs Nemotron 3 Super: 3자 비교

### 6.1 벤치마크 점수 비교

| 지표 | GLM-5 | Qwen3.5-27B | Nemotron 3 Super | 선두 |
|-----|-------|------------|-----------------|------|
| **Artificial Analysis 지능 지수** | 50 | — | 36 | GLM-5 |
| **SWE-bench Verified** | 77.8% | 72.4% | 60.47% | GLM-5 |
| **PinchBench 최고 점수** | 미측정 (~85% 추정) | **90.0% (4위)** | 88.6% (10위) | Qwen3.5-27B |
| **PinchBench 평균 점수** | 미측정 | 78.5% | 75.5% | Qwen3.5-27B |
| **PinchBench 실행 비용** | 미측정 | **$0.50** | $0 (셀프 호스팅) | Nemotron |
| **MMLU / MMLU-Pro** | 91.7% (MMLU) | 86.1% (MMLU-Pro) | 82.88% (MMLU, Nano) | GLM-5 |
| **HumanEval** | 99.0% | — | 78.05% (Nano) | GLM-5 |
| **RULER 1M 컨텍스트** | 미측정 (200K) | 미측정 (262K) | 91.75% (1M) | Nemotron |
| **Chatbot Arena Elo** | 1,451 (최상위) | — | 미등재 | GLM-5 |

### 6.2 운영 지표 비교

| 지표 | GLM-5 | Qwen3.5-27B | Nemotron 3 Super | Claude Opus 4.6 (참고) |
|-----|-------|------------|-----------------|----------------------|
| **처리 속도** | 67.7 tokens/sec | — | 163 tokens/sec | 42 tokens/sec |
| **TTFT(Time To First Token)** | 1.64 sec | — | 0.77 sec | 12.93 sec |
| **가격 (입력/출력 per 1M tokens)** | $1.00 / $3.20 | $0.40 / $2.40 (Plus 기준) | ~$0 (셀프 호스팅) | $5.00 / $25.00 |
| **파라미터** | 744B (40B 활성) | 27B (전체 활성, Dense) | 120B (12B 활성) | 비공개 |
| **컨텍스트 윈도우** | 200K 토큰 | 262K 토큰 | 1M 토큰 | 200K 토큰 |
| **오픈소스** | MIT | Apache 2.0 | Apache 2.0 | 비공개 |

### 6.3 비교 요약

**GLM-5의 강점**: SWE-bench 77.8%, HumanEval 99.0%, Chatbot Arena Elo 1,451 — 원시 코딩·추론 벤치마크에서 3자 중 최고. 단, PinchBench 공식 점수가 없어 OpenClaw 에이전트 성능은 직접 측정 필요.

**Qwen3.5-27B의 강점**: PinchBench 90.0%로 4위, 실행 비용 $0.50/run으로 상위 모델 중 최저. 27B Dense라 셀프 호스팅 시 GPU 1장(24GB VRAM)으로 구동 가능. Oracle ARM 인스턴스에서 CPU 추론도 이론적으로 가능(단, 속도 저하). Apache 2.0 라이선스.

**Nemotron 3 Super의 강점**: 처리 속도 163 tokens/sec(GLM-5 대비 2.4배), 1M 토큰 컨텍스트, 셀프 호스팅으로 API 비용 0.

**$9 예산 기준 권장 순서**:
1. **Qwen3.6-Plus Preview** — 현재 무료(Preview). PinchBench 88.6%, 평균 84.0%로 일관성 높음. Preview 종료 전까지 무비용 테스트 가능.
2. **Qwen3.5-27B** (DashScope) — $0.40/$2.40로 GLM-5($1.00/$3.20)보다 입력 60%, 출력 25% 저렴. PinchBench 점수도 상위.
3. **GLM-5** (종량제) — 원시 능력은 최고이나 PinchBench 미측정. 직접 벤치마크로 에이전트 성능 확인 후 판단.

출처: 6.1, 6.2 테이블 데이터 기준 종합 판단

---

## 7. 권장 벤치마크 측정 계획

### 7.1 측정 프레임워크

OpenClaw에서 LLM 백엔드를 교체할 때, 에이전트 프레임워크(OpenClaw)는 고정되므로 순수 모델 성능 비교가 가능하다. 다음 3단계를 권장한다.

**Phase 1: 내장 테스트로 기본 호환성 검증**

```bash
# GLM-5, Qwen, Nemotron을 동시에 라이브 테스트
OPENCLAW_LIVE_MODELS="zai/glm-5,qwen/qwen3.5-27b,nvidia/nemotron-3-super" pnpm test:live
OPENCLAW_LIVE_GATEWAY_MODELS="zai/glm-5,qwen/qwen3.5-27b,nvidia/nemotron-3-super" pnpm test:live
```

측정 항목: 모델 응답 성공률, 도구 호출 정확도, 이미지 OCR 정확도

**Phase 2: PinchBench로 실전 성능 측정**

```bash
# PinchBench 설치 및 실행 (23개 실전 작업)
git clone https://github.com/pinchbench/skill
# 각 백엔드별로 PinchBench 실행 (GLM-5, Qwen3.5-27B, 비용 허용 시 Qwen3.6-Plus Preview)
```

측정 항목 (PinchBench 5대 차원):
1. **작업 완료율** (Task Completion Rate)
2. **도구 호출 정확도** (Tool Call Accuracy)
3. **멀티스텝 추론 일관성** (Multi-step Reasoning Coherence)
4. **턴 간 컨텍스트 유지율** (Cross-turn Context Retention)
5. **환각률** (Hallucination Rate)

추가 측정: 실행 시간(sec), 총 비용(USD)

**Phase 3: WildClawBench로 한계 성능 확인**

```bash
git clone https://github.com/InternLM/WildClawBench
# 60개 고난도 실전 작업
```

### 7.2 통계적 비교 방법론

- 동일 프롬프트에 대한 쌍대 비교: **Wilcoxon signed-rank test**
- 최소 검출 효과 크기(MDE, Minimum Detectable Effect) 사전 계산
- 단일 점수 최적화 금지: 성공률 + 비용 + 레이턴시 + 평균 점수를 **동시에** 추적 (PinchBench 방식)
- 베이지안 A/B 테스팅으로 누적 신뢰도 갱신

출처: [Statsig](https://www.statsig.com/blog/llm-optimization-online-experimentation), [Maxim](https://www.getmaxim.ai/articles/a-b-testing-strategies-for-ai-agents-how-to-optimize-performance-and-quality/)

### 7.3 참고: 현재 GLM-5 PinchBench 점수 부재

GLM-5는 2026-04-03 기준 PinchBench 공식 리더보드에 등재되어 있지 않다. 따라서 직접 측정이 이 프로젝트의 핵심 산출물이 된다. 측정 후 PinchBench 리더보드의 기존 모델 점수와 비교하면 GLM-5의 OpenClaw 에이전트 성능 포지션을 객관적으로 확인할 수 있다.

---

## 8. 실행 전 체크리스트

| 항목 | 상태 | 비고 |
|-----|------|------|
| Oracle Cloud ARM 인스턴스 생성 | 대기 중 | PAYG 전환 승인 대기 또는 Free Tier 재시도 중 |
| OpenClaw 설치 | 미착수 | 인스턴스 생성 후 진행 |
| Z.AI API 키 발급 | 미착수 | [bigmodel.cn](https://bigmodel.cn) 가입. 종량제(`zai-global`) 또는 Coding Plan(`zai-coding-global`) 선택 |
| Alibaba Cloud Model Studio API 키 발급 | 미착수 | [aliyun.com](https://www.aliyun.com) 가입 → DashScope 글로벌 엔드포인트. 신규 1M 토큰 무료 |
| Qwen3.6-Plus Preview 테스트 | 미착수 | Preview 기간 무료. `reasoning: false` 설정 필수 |
| Qwen3.5-27B 연동 테스트 | 미착수 | DashScope 또는 OpenRouter 경유. `reasoning: false` 설정 필수 |
| GLM-5 연동 테스트 | 미착수 | Issue #15716 (메인 에이전트 버그) 확인 필요 |
| PinchBench 실행 | 미착수 | Qwen3.5-27B (기존 점수 90.0% 검증), GLM-5 (최초 측정) |
| 결과 비교 분석 | 미착수 | Qwen3.5-27B (90.0%), Nemotron 3 Super (88.6%), Claude Opus 4.6 (93.3%) 대비 |

---

## 부록: 전체 출처 목록

### OpenClaw + GLM-5
- [OpenClaw Provider Docs - GLM](https://docs.openclaw.ai/providers/glm)
- [Z.AI 개발자 문서 - GLM-5](https://docs.z.ai/guides/llm/glm-5)
- [Z.AI OpenClaw 연동](https://docs.z.ai/devpack/tool/openclaw)
- [OpenClaw GitHub Issue #15716](https://github.com/openclaw/openclaw/issues/15716)
- [haimaker.ai - GLM-5 OpenClaw](https://haimaker.ai/blog/glm-5-openclaw/)
- [arXiv GLM-5 기술 보고서](https://arxiv.org/html/2602.15763v1)
- [Hugging Face GLM-5](https://huggingface.co/zai-org/GLM-5)

### Qwen 3.5/3.6
- [GitHub QwenLM/Qwen3.5](https://github.com/QwenLM/Qwen3.5)
- [Hugging Face Qwen3.5-27B](https://huggingface.co/Qwen/Qwen3.5-27B)
- [Hugging Face Qwen3.5-397B-A17B](https://huggingface.co/Qwen/Qwen3.5-397B-A17B)
- [OpenClaw Qwen Provider Docs](https://docs.openclaw.ai/providers/qwen)
- [Alibaba Cloud Model Studio - OpenClaw 연동](https://www.alibabacloud.com/help/en/model-studio/openclaw)
- [Alibaba Cloud DashScope - OpenAI 호환 API](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope)
- [Alibaba Cloud Model Studio Pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing)
- [OpenRouter Qwen3.5-Plus](https://openrouter.ai/qwen/qwen3.5-plus-02-15)
- [BuildFastWithAI - Qwen 3.6 Plus Review](https://www.buildfastwithai.com/blogs/qwen-3-6-plus-preview-review)
- [Caixin Global - Qwen 3.6 발표](https://www.caixinglobal.com/2026-04-02/alibaba-releases-qwen-36-plus-ai-model-with-enhanced-coding-capabilities-102430395.html)
- [AMD - OpenClaw + Qwen3.5 + SGLang 가이드](https://www.amd.com/en/developer/resources/technical-articles/2026/openclaw-on-amd-developer-cloud-qwen-3-5-and-sglang.html)
- [GitHub Gist - Qwen 빈 응답 수정](https://gist.github.com/TheAIHorizon/37c30e375f2ce08e726e4bb6347f26b1)
- [Wikipedia - Qwen](https://en.wikipedia.org/wiki/Qwen)

### NVIDIA NemoClaw / Nemotron
- [NVIDIA NemoClaw 공식](https://www.nvidia.com/en-us/ai/nemoclaw/)
- [NVIDIA NemoClaw GitHub](https://github.com/NVIDIA/NemoClaw)
- [NVIDIA Developer Blog - Nemotron 3 Super](https://developer.nvidia.com/blog/introducing-nemotron-3-super-an-open-hybrid-mamba-transformer-moe-for-agentic-reasoning/)
- [NVIDIA Newsroom - NemoClaw 발표](https://nvidianews.nvidia.com/news/nvidia-announces-nemoclaw)
- [NVIDIA Newsroom - Nemotron 3 패밀리](https://nvidianews.nvidia.com/news/nvidia-debuts-nemotron-3-family-of-open-models)
- [TechCrunch - NemoClaw 보안 분석](https://techcrunch.com/2026/03/16/nvidias-version-of-openclaw-could-solve-its-biggest-problem-security/)
- [Nemotron 3 Super 기술 보고서 (PDF)](https://research.nvidia.com/labs/nemotron/files/NVIDIA-Nemotron-3-Super-Technical-Report.pdf)

### 벤치마크
- [PinchBench 리더보드](https://pinchbench.com/)
- [PinchBench GitHub](https://github.com/pinchbench/skill)
- [InternLM/WildClawBench](https://github.com/InternLM/WildClawBench)
- [BFCL v4 리더보드](https://gorilla.cs.berkeley.edu/leaderboard.html)
- [SWE-bench Verified 리더보드](https://llm-stats.com/benchmarks/swe-bench-verified)
- [Chatbot Arena (LMSys)](https://huggingface.co/spaces/lmarena-ai/arena-leaderboard)
- [Artificial Analysis 리더보드](https://artificialanalysis.ai/leaderboards/models)
- [Scale AI SEAL 리더보드](https://labs.scale.com/leaderboard)
- [OpenClaw Testing Docs](https://docs.openclaw.ai/help/testing)
- [o-mega.ai - AI Agent 벤치마크 가이드](https://o-mega.ai/articles/the-best-ai-agent-evals-and-benchmarks-full-2025-guide)
- [GitHub - AI Agent Benchmark Compendium](https://github.com/philschmid/ai-agent-benchmark-compendium)
