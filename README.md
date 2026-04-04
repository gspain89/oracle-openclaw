# Oracle OpenClaw

Automated benchmarking and leaderboard system for [OpenClaw](https://github.com/openclaw) AI agents. Runs multiple LLM models through standardized benchmarks on an Oracle Cloud ARM server and publishes results to a public leaderboard.

## What This Does

This project answers one question: **how well do different LLM agents perform on real tasks?**

It runs two benchmarks:

- **[PinchBench](https://github.com/pinchbench/skill)** &mdash; 24 software engineering tasks (file manipulation, code generation, debugging, etc.)
- **ClawBench-KO** &mdash; 10 Korean-language agent tasks (address parsing, document generation, financial processing, legal analysis)

ClawBench-KO is a custom benchmark built for this project. It tests capabilities that standard English benchmarks miss entirely: Korean number systems, EUC-KR legacy encoding, Korean business document formats, and Korean legal text comprehension.

Results are normalized into a unified leaderboard and deployed as a static site via GitHub Pages.

## Architecture

```
Oracle ARM Server (4 OCPU / 24 GB)
├── OpenClaw gateway (systemd service, ws://127.0.0.1:18789)
├── PinchBench (~/pinchbench-skill/)
└── ClawBench-KO (~/oracle-openclaw/server/claw-bench-ko/)
        │
        ├── Test agent ── sends tasks to ──→ LLM under test
        └── Judge agent ── grades output ──→ GPT-5.2 / Claude

GitHub Pages
└── Astro static site (leaderboard, charts, comparisons)
```

## Benchmarks

### PinchBench

Third-party benchmark with 24 tasks across three grading types:

| Grading Type | Tasks | Method |
|---|---|---|
| Automated | 9 | File existence, content matching, code execution |
| LLM Judge | 7 | Judge model evaluates output quality against rubric |
| Hybrid | 8 | Automated checks (50%) + LLM judge (50%) |

### ClawBench-KO

Custom Korean-language benchmark with 10 tasks:

| # | Task | Type | What It Tests |
|---|---|---|---|
| 1 | `addr_parse` | automated | Parse 20 Korean addresses (abbreviated/full, road/lot, special regions) into structured JSON |
| 2 | `num_convert` | automated | Convert 15 Korean number expressions (삼천이백만, 2조 5600억, etc.) to integers |
| 3 | `phone_normalize` | automated | Normalize 25 Korean phone numbers (mobile, landline, toll-free, special) to standard format |
| 4 | `csv_transform` | hybrid | Convert EUC-KR bank transaction CSV to UTF-8 with date/amount normalization |
| 5 | `meeting_minutes` | llm_judge | Transform informal Korean conversation transcript into formal corporate meeting minutes |
| 6 | `biz_email` | llm_judge | Draft a formal Korean business partnership proposal email |
| 7 | `news_summary` | llm_judge | Synthesize 3 Korean news articles into an executive briefing (400-600 chars) |
| 8 | `invoice_gen` | hybrid | Generate a Korean tax invoice (세금계산서) with correct VAT calculations |
| 9 | `resume_parse` | hybrid | Parse a Korean resume with mixed date formats into structured JSON |
| 10 | `regulation_extract` | hybrid | Extract obligations and prohibitions from Korean privacy law (개인정보 보호법) |

All tasks interact through the OpenClaw agent CLI &mdash; reading input files from a workspace, processing them, and writing output files. No direct API calls.

Detailed documentation for each task: [`docs/claw-bench-ko.md`](docs/claw-bench-ko.md)

## Project Structure

```
oracle-openclaw/
├── .github/workflows/
│   └── deploy-pages.yml        # GitHub Pages auto-deploy on results change
├── docs/
│   ├── openclaw-architecture.md # OpenClaw gateway + agent internals
│   ├── pinchbench-internals.md  # PinchBench execution flow and grading
│   └── claw-bench-ko.md        # ClawBench-KO task specifications
├── server/
│   ├── config/
│   │   ├── models.json          # Model registry (pricing, context window, provider)
│   │   └── benchmarks.json      # Benchmark definitions
│   ├── claw-bench-ko/
│   │   ├── manifest.json        # Task registry (10 tasks)
│   │   ├── runner.py            # Orchestrator (agent creation, task execution, scoring)
│   │   ├── grader.py            # Grading engine (13 automated checks + LLM judge)
│   │   └── tasks/               # 10 task directories, each with task.json + input data
│   ├── scripts/
│   │   ├── setup-server.sh      # One-time server initialization
│   │   ├── run-pinchbench.sh    # Single-model PinchBench runner
│   │   ├── run-claw-bench-ko.sh # Single-model ClawBench-KO runner
│   │   ├── run-all.sh           # Full orchestrator (all models × all benchmarks)
│   │   └── deploy-results.sh    # Push results to trigger Pages rebuild
│   └── python/
│       └── normalize.py         # Raw results → unified leaderboard.json
├── results/
│   ├── raw/                     # Per-run benchmark output (gitignored)
│   └── normalized/
│       └── leaderboard.json     # Unified scores for the frontend
├── site/                        # Astro static site (leaderboard UI)
│   ├── src/pages/
│   │   ├── index.astro          # Main leaderboard table + bar chart
│   │   ├── compare.astro        # A/B model comparison (radar chart)
│   │   ├── cost.astro           # Cost-efficiency scatter plot
│   │   ├── history.astro        # Score trends over time
│   │   └── korean.astro         # ClawBench-KO results
│   └── package.json
└── key/                         # SSH keys, .env (gitignored, never committed)
```

## Models Under Test

| Model | Provider | Free | Notes |
|---|---|---|---|
| Nemotron 3 Super 120B | OpenRouter | Yes | Default test model, PinchBench 97.7% (automated-only) |
| GLM-5 | DashScope (Z.AI) | No | First-ever PinchBench measurement for this model |
| Qwen 3.5 Plus | DashScope | No | Vision-capable, 1M context window |
| GPT-5.2-chat | Azure OpenAI | No | Used as judge model for LLM-graded tasks |

## Running Benchmarks

### Prerequisites

- Oracle ARM server with OpenClaw installed and gateway running
- Server access via SSH

### Quick Start

```bash
# SSH into the server
ssh -i key/ssh-key.key ubuntu@168.107.51.82

# Run ClawBench-KO (automated tasks only, no judge cost)
cd ~/oracle-openclaw
bash server/scripts/run-claw-bench-ko.sh nvidia/nemotron-3-super-120b-a12b:free \
  --task addr_parse,num_convert,phone_normalize

# Run ClawBench-KO (all 10 tasks, 3 runs for best/average)
bash server/scripts/run-claw-bench-ko.sh nvidia/nemotron-3-super-120b-a12b:free --runs 3

# Run PinchBench (automated-only, 9 tasks)
bash server/scripts/run-pinchbench.sh nvidia/nemotron-3-super-120b-a12b:free

# Normalize results and generate leaderboard
python3 server/python/normalize.py
```

### Scoring

Each benchmark produces per-task scores (0.0 to 1.0). With `--runs N`, both **best** (highest across N runs) and **average** (mean across N runs) scores are reported.

The judge model (default: `azure-openai/gpt-5.2-chat`) evaluates `llm_judge` and `hybrid` tasks using detailed rubrics with weighted criteria.

## Dependencies

| Component | Requirements |
|---|---|
| Server scripts | Bash, Python 3.8+ (stdlib only), OpenClaw CLI |
| PinchBench | Python 3.10+, `uv` (auto-manages its own deps) |
| ClawBench-KO | Python 3.8+ (stdlib only), OpenClaw CLI |
| Leaderboard site | Node.js 22+, npm |
| Deployment | GitHub Actions (automatic on push to main) |

**No pip packages required.** All Python code uses the standard library only.

## Documentation

| Document | Contents |
|---|---|
| [`docs/openclaw-architecture.md`](docs/openclaw-architecture.md) | OpenClaw gateway/agent architecture, model routing, provider system, auth |
| [`docs/pinchbench-internals.md`](docs/pinchbench-internals.md) | PinchBench execution flow, agent lifecycle, task format, judge mechanism |
| [`docs/claw-bench-ko.md`](docs/claw-bench-ko.md) | ClawBench-KO task specifications, grading system, input data, expected outputs |

## License

[MIT](LICENSE)
