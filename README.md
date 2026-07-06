# ADAL — Autonomous Discovery & Analysis Lab

<div align="center">

**Model-Agnostic Multi-Agent Scientific Discovery Framework**

*Planner → Proposer → Verifier — an FSM-driven research loop*

[Textual TUI](#tui-reference) · [REST API](#api-reference) · [Docker](#docker-deployment) · [5 LLM Providers](#installation)

</div>

---

## Table of Contents

1. [What is ADAL?](#what-is-adal)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [How It Works](#how-it-works)
5. [TUI Reference](#tui-reference)
6. [Settings Guide](#settings-guide)
7. [API Reference](#api-reference)
8. [Docker Deployment](#docker-deployment)
9. [Supported Domains](#supported-domains)
10. [Tips & Tricks](#tips--tricks)
11. [Troubleshooting](#troubleshooting)
12. [Contributing](#contributing)

---

## What is ADAL?

ADAL is a **model-agnostic multi-agent framework** for autonomous scientific discovery. It orchestrates three specialized agents — a Planner, a Proposer, and a Verifier — in a finite-state-machine (FSM) loop to generate, validate, and refine scientific hypotheses across four domains.

### Architecture

```
┌────  RESEARCH LOOP (per iteration)  ────┐
│                                          │
│   PLANNER ──► PROPOSER ──► VERIFIER      │
│   (decides)   (generates)   (validates)  │
│       ▲                           │      │
│       └───── verdict ─────────────┘      │
│                                          │
│   Actions: CONTINUE · PIVOT · CONVERGE   │
└──────────────────────────────────────────┘
```

- **Planner** — Classifies the query domain, generates research directives, and decides whether to CONTINUE, PIVOT, CONVERGE, or FAIL based on verification results
- **Proposer** — Generates scientific hypotheses with synthesis procedures, writes and executes Python analysis scripts in an isolated sandbox, runs self-critique
- **Verifier** — Validates hypotheses against domain-specific physical/chemical laws using both deterministic numerical checks (pre-LLM) and LLM-powered reasoning with 14 fatal-flaw rules

### Key Features

| Feature | Detail |
|---------|--------|
| **Dual-mode** | Rich Textual TUI + headless FastAPI REST server |
| **Model-agnostic** | DeepSeek (default), OpenAI, OpenRouter, Ollama, custom endpoints |
| **4 science domains** | Chemistry, Astrophysics, Physics, Particle/Nuclear |
| **Live reasoning** | Streaming chain-of-thought previews in the TUI |
| **Deterministic validation** | Domain validators run before the LLM — catching arithmetic and physical-law violations instantly |
| **Vector memory** | LanceDB-powered episodic memory with chaff pruning + cross-session global lessons |
| **Sandbox execution** | Isolated Python subprocess with 28 allowed imports, security audit |
| **Web search** | DDG search with Wikipedia fallback, fetch with HTML extraction, PubChem blocked by default |
| **Session library** | Browse, search, and export validated procedures across all past sessions |
| **Docker-ready** | Multi-stage Dockerfile, docker-compose with persistent volumes and health checks |

### Supported LLM Providers

| Provider | Config Key | Default Model | Notes |
|----------|-----------|---------------|-------|
| **DeepSeek** | `deepseek` | `deepseek-v4-pro` | Default. Supports `reasoning_effort` (max/high/medium/low) |
| **OpenAI** | `openai` | `gpt-4o` | Also used for embeddings (vector memory) |
| **OpenRouter** | `openrouter` | (user-specified) | Multi-model gateway |
| **Ollama** | `ollama` | (user-specified) | Local, no API key needed |
| **Custom** | `custom` | (user-specified) | Any OpenAI-compatible endpoint |

---

## Installation

### Prerequisites
- **Python 3.11+** (tested on 3.13)
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager
- **Docker** (optional — for containerized deployment)

### Setup

```bash
git clone https://github.com/anomalyco/ADAL.git
cd ADAL

# Install dependencies with uv
cp .env.example .env
# Edit .env with your API keys (at minimum DEEPSEEK_API_KEY)
uv sync

# Launch the TUI
uv run adal
```

### API Keys

ADAL reads configuration from `.env` via pydantic-settings. Minimum required:

```ini
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-your-key-here
```

For other providers, set the corresponding key and model. See [Settings Guide](#installation) for all options.

> **No API key?** Run with Ollama locally: `LLM_PROVIDER=ollama OLLAMA_BASE_URL=http://localhost:11434/v1 OLLAMA_MODEL=llama3.1`

---

## Quick Start

### 5-Minute Walkthrough

**1. Launch the TUI:**
```bash
uv run adal
```
You'll see the welcome screen with the ADAL ASCII logo and four navigation buttons.

**2. Start a new session:**
Press **↓** then **Enter** on "New Research Session" — or press **F2** to open the command palette and type "new."

**3. Enter a research question:**
```
Synthesize 2,5-dimethoxybenzaldehyde from 1,4-dimethoxybenzene
```
Press **Enter** to submit.

**4. Watch the loop:**
- The **Planner** classifies the domain (Chemistry) and issues a directive
- The **Proposer** generates a synthesis procedure, writes analysis code, runs it in the sandbox
- The **Verifier** checks stoichiometry, yield realism, thermodynamics, equipment constraints, and precursor accessibility

**5. See the result:**
When the loop converges, you'll see the final answer with action buttons:
- **Continue Research** — ask a follow-up question
- **Export Markdown** — save result to `adal_export.md`

**6. Browse past work:**
Press **F9** to go back, then choose **Past Sessions** to view and resume any previous session.

---

## How It Works

### The FSM Loop

ADAL uses a **Python-controlled finite state machine**, not LLM-driven routing. The orchestration logic in `orchestrator.py` evaluates typed enum values (`PlannerAction`) from the planner's JSON output.

#### Per-Iteration Flow

```
Iteration N:
  1. PLANNER issues directive → "Investigate reductive amination of ketone 3"
  2. PROPOSER generates hypothesis → synthesis procedure + analysis script
       ├── Runs Python script in sandbox (numpy, scipy, rdkit, etc.)
       └── Self-critique: checks stoichiometry, yield, feasibility
  3. VERIFIER validates:
       ├── Deterministic checks (pre-LLM): math, conservation laws, thermodynamics
       ├── LLM check: 14 fatal-flaw rules, equipment era, precursor availability
       └── Verdict: PASS / PARTIAL / FAIL / INCONCLUSIVE
  4. PLANNER decides next action:
       ├── PASS + no new flaws → CONVERGE (stop, output result)
       ├── FAIL with fatal flaws → PIVOT (change direction)
       ├── PARTIAL → CONTINUE (iterate with feedback)
       └── 3+ consecutive identical flaws → auto-PIVOT
```

#### FSM Actions

| Action | Trigger | Effect |
|--------|---------|--------|
| **CONTINUE** | PARTIAL verdict, fixable flaws | Next iteration with verifier suggestions |
| **PIVOT** | FAIL verdict, fatal flaws, or 3+ consecutive identical failures | Change research direction |
| **CONVERGE** | PASS verdict ≥ 0.80 confidence, no new fatal flaws | Stop loop, output final answer |
| **FAIL** | Max iterations reached, unrecoverable errors | Stop loop, report failure |

### Agent Details

| Agent | Temperature | Role | Tools |
|-------|------------|------|-------|
| **Planner** | 0.4 | Domain classification, directive generation, action decisions | `web_search`, `fetch_url`, `calculate` |
| **Proposer** | 0.7 | Hypothesis generation, sandbox execution, self-critique | `web_search`, `fetch_url`, `calculate` |
| **Verifier** | 0.3 | Numerical validation, fatal-flaw checks, verdict issuance | `web_search`, `fetch_url`, `calculate` |

The Planner is queried **twice**: once for initial domain classification, then per-iteration for action decisions.

### Deterministic Pre-LLM Validation

Before the Verifier calls the LLM, domain-specific validators run numerically:

- **Chemistry**: Reaction thermodynamics (ΔG = ΔH − TΔS), yield realism bounds (amination 60-88%, general 50-95%), bond enthalpy estimation
- **Astrophysics**: Kepler's third law, transit depth physicality (0.1 M⊕ to 2.5 RJ), mass-radius relation (M^0.8 for M<1 M⊙), habitable zone bounds
- **Physics**: Energy conservation (ΣE_in = ΣE_out), ideal gas law (PV = nRT)
- **Particle/Nuclear**: Charge conservation, decay kinematics (energy-momentum)

If a fatal flaw is found deterministically, the LLM call is **skipped entirely** — saving tokens and time.

### Tool Call Limits

Each agent gets up to **6 tool turns** (configurable via `LLM_MAX_TOOL_TURNS`). After exhausting turns without producing content:
- Tool messages are stripped from the context
- Thinking mode is disabled (no `reasoning_effort`, no `extra_body`)
- A hard prompt forces a JSON response at `forced_answer_temperature` (default 0.1)

### Memory System

ADAL uses **LanceDB** for vector memory with OpenAI embeddings:

- **Episodic memory** — Records agent outputs per session. Queried during planning to provide context.
- **Chaff pruning** — Failed hypotheses are stored as "failure vectors." Cosine similarity > 0.85 to any failure vector drops an episodic result, preventing cognitive death spirals.
- **Global lessons** — Post-mortem hook at session end summarizes what was learned. Loaded at session start as cross-session knowledge.
- **Context cap** — Maximum 3 memories injected per agent prompt to prevent prompt bloat.

Memory gracefully degrades if `OPENAI_API_KEY` is not set — agents operate without memory enrichment.

---

## TUI Reference

### Launch

```bash
uv run adal          # Opens welcome screen
```

### Keybindings

| Key | Action |
|-----|--------|
| **F1** | Help — keybinding reference |
| **F2** | Command palette — search all actions |
| **F5** | Stop current research run |
| **F9** | Go back to previous screen |
| **Ctrl+D** | Cycle through 9 themes |
| **Ctrl+,** | Open settings hub |
| **Q** | Quit |

### Screens

#### Welcome Screen
ASCII ADAL logo with four navigation buttons: **New Research Session**, **Browse Library**, **Past Sessions**, **Settings**. Arrow keys (↑↓/Tab/Shift+Tab) navigate; Enter activates.

#### Dashboard
The main research interface.

- **Chat History** — Scrollable feed of agent iteration cards. Each card shows:
  - Agent icon + role + iteration number
  - **Reasoning preview** — streaming chain-of-thought text in italics
  - **Pulsing dots** (●○○○ → ○●○○ → ...) during agent thinking
  - **▸/▾ toggle** — click to expand/collapse card detail
- **Query Input** — Bottom-docked text input. Enter to submit, Shift+Enter for newline
- **Loading Spinner** — Animated rainbow ring (◜◝◞◟) during research
- **Status Bar** — Current agent, elapsed time, iteration count

**Continue Research** enables follow-up questions that carry forward the previous session's context.

#### Session Detail
View and resume past research sessions. Loads full interaction history, shows all agent cards with reasoning, supports follow-up queries via the same input. Access via Past Sessions → "View Session."

#### History
Lists all past sessions with status icons (✓ converged, ✗ failed, ⏳ active), query preview, domain, iteration count, and timestamp. Click "View Session →" to open.

#### Library
Browse all **verified procedures** across all sessions. Filter by domain (All Domains, Chemistry, Physics, Astrophysics, Particle/Nuclear). Each entry shows the hypothesis statement, yield, and confidence. Click to open.

#### Procedure Detail
Full "paper" view of a verified procedure with:

- **Banner** — Statement, domain, yield, status (✓/✗), confidence bar (▁▂▃▄▅▆▇█)
- **10 Semantic Sections** — Synthesis Procedure, Workup Procedure, Analysis Summary, Execution Output (stdout/stderr), Fatal Flaws, Suggestions, Corrected Values, Yield Details, Citations, Features Detected
- **Action Buttons** — View Full Session, Export Markdown

### Command Palette (F2)

The command palette provides fuzzy-search access to all actions:

- New Session
- Session History
- Research Library
- Settings → Agents, Models, Loop Control, Memory, Search, General, Theme, Pricing, Advanced
- Toggle Theme
- Export Last Result
- Quit

---

## Settings Guide

Access settings via **Ctrl+,** or the command palette. All settings persist to `.env` and take effect on restart.

### Agents (3 tabs: Proposer / Verifier / Planner)

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| Temperature | 0.7 / 0.3 / 0.4 | 0.0–2.0 | Higher = more creative, lower = more deterministic |
| Top-P | 0.95 / 0.9 / 0.9 | 0.0–1.0 | Nucleus sampling cutoff |
| Top-K | 0 (disabled) | 0–100 | Limit sampling to top-K tokens |
| Frequency Penalty | 0.3 / 0.0 / 0.0 | −2.0–2.0 | Penalize repeated tokens |
| Presence Penalty | 0.2 / 0.0 / 0.1 | −2.0–2.0 | Penalize tokens already present |
| Seed | (none) | integer | Set for reproducible outputs |
| Forced Answer Temp | 0.1 | 0.0–1.0 | Temperature for forced final answer |

### Models

| Setting | Default | Description |
|---------|---------|-------------|
| Provider | DeepSeek | DeepSeek / OpenAI / OpenRouter / Ollama / Custom |
| API Key | (from .env) | Provider-specific API key |
| Model Name | deepseek-v4-pro | Model identifier |
| Base URL | api.deepseek.com/v1 | API endpoint |
| Max Tokens | 65536 | Max tokens per LLM call (DeepSeek supports ~350K) |
| Reasoning Effort | max | DeepSeek chain-of-thought depth (max/high/medium/low) |

### Loop Control

| Setting | Default | Description |
|---------|---------|-------------|
| Max Tool Turns | 6 | Web search + tool cycles before forced answer |
| LLM Retry Count | 2 | Retries when LLM returns empty or bad output |
| Pivot Threshold | 3 | Consecutive identical failures before auto-PIVOT |

### Memory

| Setting | Default | Description |
|---------|---------|-------------|
| Memory Enabled | On | Toggle LanceDB vector memory |
| Database Path | `./memory_vault.lance` | LanceDB storage location |
| OpenAI API Key | (from .env) | Required for embeddings |
| Embedding Model | text-embedding-3-small | OpenAI embedding model |
| Prune Threshold | 0.85 | Cosine similarity threshold for chaff pruning |
| Max Episodic | 5 | Max episodic memories per query |
| Max Global | 3 | Max global lessons returned |
| Context Cap | 3 | Max memories injected per agent prompt |

### Search

| Setting | Default | Description |
|---------|---------|-------------|
| Throttle Delay | 2.0s | Seconds between search requests |
| Max Retries | 3 | DDG search retry count |
| Blocked Hosts | pubchem.ncbi.nlm.nih.gov | Comma-separated blocked fetch hosts |

### Advanced

| Setting | Default | Description |
|---------|---------|-------------|
| Max Iterations | 10 | Total research loop iterations |
| Sandbox Timeout | 120s | Script execution time limit |
| Memory Context Cap | 3 | Max memories per prompt |
| Memory Index Min Rows | 256 | Rows before LanceDB creates vector index |
| Search Max Results | 5 | Results per web_search call |
| Search Timeout | 20s | DDG request timeout |
| Fetch Max Chars | 10000 | Truncation for fetched page content |
| Fetch Timeout | 25s | Fetch request timeout |
| Fetch Max Retries | 3 | Fetch retry count |
| Search Backoff Base | 2.0 | Exponential backoff multiplier |

### Theme

8 built-in Textual themes: `textual-dark` (default), `textual-light`, `dracula`, `gruvbox`, `nord`, `monokai`, `solarized-light`, `flexoki`. Changes apply immediately; Save makes it persistent.

### Pricing

| Setting | Default | Description |
|---------|---------|-------------|
| Input Price | $0.435/M tok | Cost per 1M input tokens |
| Cached Input Price | $0.003625/M tok | Cost per 1M cached input tokens |
| Output Price | $0.87/M tok | Cost per 1M output tokens |

Defaults match DeepSeek V4 Pro pricing. Adjust for your provider.

---

## API Reference

Start the headless API server:

```bash
uv run adal api --host 0.0.0.0 --port 8000
```

Or via Docker:

```bash
docker compose up -d
```

### Endpoints

#### `GET /api/health`

Health check.

```json
{"status": "ok"}
```

#### `GET /api/sessions`

List all sessions. Query: `?limit=50` (1-200).

```json
[
  {
    "id": "a1b2c3d4...",
    "query": "Synthesize 2,5-dimethoxybenzaldehyde...",
    "domain": "chemistry",
    "status": "converged",
    "iteration": 3,
    "created_at": "2025-07-06T22:00:00+00:00"
  }
]
```

#### `GET /api/sessions/{id}`

Full session detail including hypotheses, interactions, and validations.

```json
{
  "id": "...",
  "query": "...",
  "domain": "chemistry",
  "status": "converged",
  "iteration": 3,
  "hypotheses": [
    {
      "id": "...",
      "iteration": 1,
      "agent_role": "proposer",
      "status": "verified",
      "content": {
        "hypothesis": {
          "statement": "...",
          "synthesis_procedure": "...",
          "expected_yield_range": "60-75%"
        },
        "execution_result": {...}
      }
    }
  ],
  "interactions": [
    {
      "id": "...",
      "agent_role": "verifier",
      "direction": "verifier_to_planner",
      "content": {
        "_reasoning": "...",
        "verdict": "PASS",
        "confidence": 0.92
      }
    }
  ],
  "validations": [
    {
      "passed": true,
      "confidence": 0.92,
      "proof": {"fatal_flaws": [], "suggestions": []}
    }
  ]
}
```

#### `POST /api/run`

Start a new research session.

**Request:**
```json
{
  "query": "Design a synthesis for 4-fluoroamphetamine from benzaldehyde",
  "domain": "chemistry",
  "model": null
}
```

**Response:**
```json
{
  "session_id": "e5f6g7h8...",
  "status": "converged",
  "domain": "chemistry",
  "iterations": 4,
  "validated_count": 1,
  "final_answer": {
    "synthesis_procedure": "...",
    "workup_procedure": "...",
    "expected_yield_range": "55-70%",
    "safety_notes": "..."
  },
  "cost": {"total_cost": 0.0234}
}
```

#### `GET /api/sessions/{id}/stream`

SSE event stream for a session being continued. Events:

```
data: {"type":"status","name":"proposer","status":"thinking","detail":""}
data: {"type":"reasoning","name":"proposer","text":"Let me analyze..."}
data: {"type":"status","name":"proposer","status":"done","detail":"..."}
data: {"type":"result","data":{...}}
data: {"type":"done"}
```

Ping events (`{"type":"ping"}`) sent every 30 seconds to keep the connection alive.

#### `POST /api/sessions/{id}/continue`

Continue a past session with a follow-up query.

**Request:**
```json
{
  "query": "What if we use NaBH4 instead of LiAlH4?",
  "model": null
}
```

#### `GET /api/library`

Browse validated procedures. Query: `?domain=chemistry&limit=50`.

```json
{
  "stats": {"chemistry": 15, "astrophysics": 3},
  "procedures": [
    {
      "hypothesis_id": "...",
      "domain": "chemistry",
      "content": {...},
      "validation": {"passed": true, "confidence": 0.95, "proof": {...}}
    }
  ]
}
```

#### `POST /api/stop/{session_id}`

Stop a running session.

```json
{"status": "stopped", "session_id": "e5f6g7h8..."}
```

### Client Examples

**Python (httpx):**
```python
import httpx

async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
    # Start research
    resp = await client.post("/api/run", json={"query": "Synthesize aspirin"})
    result = resp.json()
    print(f"Session: {result['session_id']}, Status: {result['status']}")

    # Browse library
    resp = await client.get("/api/library", params={"domain": "chemistry"})
    library = resp.json()
    print(f"Verified procedures: {len(library['procedures'])}")
```

**curl:**
```bash
# Health
curl http://localhost:8000/api/health

# Start research
curl -X POST http://localhost:8000/api/run \
  -H "Content-Type: application/json" \
  -d '{"query": "Calculate the orbital period of Kepler-22b"}'

# Stream session (use -N for no buffering)
curl -N http://localhost:8000/api/sessions/{id}/stream

# Browse library
curl "http://localhost:8000/api/library?domain=chemistry&limit=10"
```

---

## Docker Deployment

### Quick Start

```bash
# Build and start the API server
docker compose up -d

# Check health
curl http://localhost:8000/api/health

# Run the TUI (interactive terminal)
docker compose run --rm -it adal tui
```

### Configuration

All environment variables from `.env` are passed through:

```yaml
# docker-compose.yml (excerpt)
environment:
  - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}
  - LLM_PROVIDER=${LLM_PROVIDER:-deepseek}
  - DATABASE_URL=sqlite+aiosqlite:////app/data/adal.db
  - MEMORY_DB_PATH=/app/data/memory_vault.lance
```

### Data Persistence

- **Named volume** `adal_data` mounted at `/app/data` — stores `adal.db` (SQLite) and `memory_vault.lance` (LanceDB)
- **Read-only** `.env` mount at `/app/.env` — configuration without baking secrets into the image

### TUI in Docker

The TUI requires a real terminal. Run with:

```bash
docker compose run --rm -it adal tui
```

The `-it` flags allocate a pseudo-TTY and keep stdin open. `TERM` and `COLORTERM` are set in the Dockerfile for true-color support.

### Building from Source

```bash
docker build -t adal:latest .
```

Multi-stage build: ~1.2 GB final image (includes all scientific packages: numpy, scipy, rdkit, astropy, etc.).

### Architecture Support

The Dockerfile builds on both `amd64` and `arm64` via:

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t adal:latest .
```

---

## Supported Domains

### Chemistry

The most fully-featured domain with 14 verifier rules:

| Rule | Check |
|------|-------|
| **1** | Stoichiometry balances exactly for all atoms |
| **2** | Yield claims are in realistic ranges for the reaction class |
| **3** | Reaction thermodynamics are feasible (ΔG < 0 or driven by conditions) |
| **4** | Activation energy is surmountable at the reaction temperature |
| **5** | Reagents are compatible — no mutually destructive combinations |
| **6** | Conservation of mass holds |
| **7** | Physical constants are within known ranges |
| **8** | Equations are dimensionally consistent |
| **9** | Numerical values are arithmetically correct |
| **10** | Procedural steps are in correct logical order |
| **11** | Safety hazards are acknowledged (explosive, toxic, exothermic) |
| **12** | Workup/isolation procedure is described (no "evaporate and get pure product") |
| **13** | **Equipment is mid-1900s compatible** — no rotovap, HPLC, GC-MS, microwave reactor. This is a FATAL FLAW unless the user explicitly requests modern equipment. |
| **14** | **Restricted precursor syntheses are provided** — any monitored/controlled precursor must have an accessible synthesis from common starting materials. FATAL FLAW if missing. |

**Deterministic validators:**
- Reaction thermodynamics: ΔG = ΔH − TΔS
- Yield realism bounds: amination 60-88%, general 50-95%
- Bond-enthalpy estimation
- Workup description presence detection

### Astrophysics

**Deterministic validators:**
- Kepler's third law: P² ∝ a³
- Transit depth calculation and physicality check (0.1 M⊕ to 2.5 RJ)
- Stellar density from transit parameters
- Mass-radius relation (M^0.8 for M<1 M⊙, M^0.57 for M≥1 M⊙)
- Orbital resonance detection (up to 5:5)
- Habitable zone bounds (inner/outer based on stellar luminosity)

### Physics

**Deterministic validators:**
- Energy conservation: ΣE_in = ΣE_out (within 1% tolerance)
- Ideal gas law: PV = nRT

### Particle / Nuclear

**Deterministic validators:**
- Charge conservation across reactions/decays
- Decay kinematics: energy-momentum conservation

---

## Tips & Tricks

### Use-Case Recipes

#### Maximum Creativity — Exploring Novel Syntheses

For brainstorming novel reaction pathways or unconventional approaches:

```ini
PROPOSER_TEMPERATURE=0.9
VERIFIER_TEMPERATURE=0.5
PLANNER_TEMPERATURE=0.6
PROPOSER_TOP_P=0.98
MAX_ITERATIONS=8
REASONING_EFFORT=max
```

Explanation: Higher temperatures encourage divergent thinking. The verifier stays moderately strict to filter truly impossible ideas.

#### Conservative / Safety-First — Validating Known Reactions

For verifying established procedures or safety-critical syntheses:

```ini
PROPOSER_TEMPERATURE=0.4
VERIFIER_TEMPERATURE=0.2
PLANNER_TEMPERATURE=0.3
PROPOSER_TOP_P=0.85
PROPOSER_SEED=42
VERIFIER_SEED=42
PLANNER_SEED=42
```

Explanation: Low temperatures produce deterministic, consistent output. Setting seeds ensures reproducibility.

#### Budget-Conscious — Minimizing API Costs

```ini
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=deepseek/deepseek-chat
LLM_MAX_TOOL_TURNS=4
MAX_ITERATIONS=5
REASONING_EFFORT=low
MEMORY_ENABLED=false
```

Explanation: OpenRouter can be cheaper. Reducing tool turns and iterations caps token usage. Disabling memory skips embedding API calls. Lower reasoning effort reduces chain-of-thought tokens.

#### Local-Only — No Cloud Dependencies

```ini
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3.1:8b
MEMORY_ENABLED=false
```

Explanation: Runs entirely locally. Disable memory (requires OpenAI embeddings). The 8B model works for simpler queries; use `llama3.1:70b` for better results.

#### Deep Analysis Mode — Maximum Thoroughness

```ini
REASONING_EFFORT=max
MAX_ITERATIONS=15
LLM_MAX_TOOL_TURNS=10
LLM_MAX_TOKENS=65536
SEARCH_MAX_RESULTS=10
SEARCH_TIMEOUT=30
FETCH_MAX_CHARS=20000
VERIFIER_TEMPERATURE=0.2
```

Explanation: Maximizes research depth. More iterations, more web search results, longer fetched content, and stricter verification. Costs more in tokens and time.

#### High-Precision Physics — Reproducible Calculations

```ini
PLANNER_TEMPERATURE=0.3
PROPOSER_TEMPERATURE=0.4
VERIFIER_TEMPERATURE=0.15
PROPOSER_SEED=0
VERIFIER_SEED=0
PLANNER_SEED=0
PROPOSER_TOP_K=10
VERIFIER_TOP_K=5
MAX_ITERATIONS=20
```

Explanation: Physics calculations benefit from precision over creativity. Top-K limits the sampling space. Low verifier temperature ensures strict numerical checks. Increase iterations for convergence on precise values.

#### Rapid Exploration — Speed Over Depth

```ini
REASONING_EFFORT=low
MAX_ITERATIONS=3
LLM_MAX_TOOL_TURNS=3
SEARCH_MAX_RESULTS=3
SEARCH_TIMEOUT=10
FETCH_MAX_CHARS=5000
PROPOSER_TEMPERATURE=0.6
```

Explanation: Fast iteration for initial exploration. Low reasoning effort skips deep chain-of-thought. Fewer turns and iterations keep things quick. Use this to survey possibilities before committing to a deep run.

### Pro Tips

1. **Continue Research is your friend** — Instead of starting over, use follow-up queries to refine a result. Each follow-up carries forward the previous context.

2. **Library is cumulative** — Verified procedures from all sessions are accessible via the Library. Browse by domain to find proven syntheses and experimental procedures.

3. **Export early, export often** — Use Export Markdown to save results. Markdown files are human-readable and version-control friendly.

4. **Tune per-agent temperatures independently** — The Proposer (0.7) is warmer than the Planner (0.4) and Verifier (0.3) by design. Don't set them all to the same value — each agent has a distinct role.

5. **Seeds for reproducibility** — If you're comparing approaches or writing a paper, set all three agent seeds to the same integer. Identical queries + identical seeds = identical outputs.

6. **Watch the reasoning previews** — The streaming reasoning text in the TUI shows you what the LLM is "thinking." It's the best debugging tool for understanding why a hypothesis was generated or rejected.

7. **Blocked hosts are configurable** — PubChem is blocked by default to avoid fetching massive pages. Add your own blocked hosts as a comma-separated list if certain sites are problematic.

8. **The sandbox is real Python** — The Proposer's analysis scripts execute in an isolated subprocess with numpy, scipy, rdkit, sklearn, and 24 other libraries. The script output (stdout/stderr) is captured and shown in the procedure detail view.

---

## Troubleshooting

### Common Issues

#### "DeepSeek max tokens not 8K"

ADAL sets `LLM_MAX_TOKENS=65536` by default. DeepSeek V4 Pro supports ~350K context. If you're using a different model, adjust accordingly. Check your provider's context window.

#### "RDKit import fails"

RDKit requires compilation from source on some systems. If `uv sync` fails:

```bash
# Debian/Ubuntu
sudo apt install libboost-all-dev libeigen3-dev

# macOS
brew install rdkit
```

On Docker, build dependencies are included automatically.

#### "LanceDB index creation warning"

This is expected when the memory table has fewer than 256 rows. The warning is caught and logged — it doesn't affect functionality. Memory works without an index; it just does full scans for small datasets.

#### "Docker TUI shows garbled output"

The TUI needs a real terminal. Ensure you're running with `-it`:

```bash
docker compose run --rm -it adal tui
```

Not `docker compose exec` or `docker run` without `-it`.

#### "Command palette settings don't show values"

This is a known Textual rendering issue with certain terminal configurations. Use **Ctrl+,** to open the Settings Hub directly, then navigate to the desired category. All values are pre-filled from `.env`.

#### ".env changes not taking effect"

Settings changes in the TUI are written to `.env` on Save. A restart is required for pydantic to re-read the file. Docker containers need a rebuild or restart.

#### "Refusal detected" in agent output

ADAL has built-in anti-refusal detection. If an agent refuses a query (e.g., citing ethical concerns about chemical synthesis), the system automatically retries with a debiased prompt. If refusals persist:

1. Check the query wording — avoid phrasing that triggers content filters
2. Increase `LLM_RETRY_COUNT` (default 2)
3. Try a different LLM provider — some providers have stricter content policies

#### "Forced final answer" appearing frequently

This means agents are hitting their tool-turn limit without producing content. Solutions:

1. Increase `LLM_MAX_TOOL_TURNS` (default 6)
2. Reduce `SEARCH_MAX_RESULTS` to speed up web searches
3. Try a more capable model
4. Simplify the query

#### Ollama connection errors

Ensure Ollama is running:

```bash
ollama serve
ollama pull llama3.1
```

Default base URL is `http://localhost:11434/v1`. If running Ollama inside Docker, use `host.docker.internal` or the host's IP:

```ini
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
```

#### SQLite "database is locked"

SQLite only supports one writer at a time. If running multiple ADAL instances, use a different database path per instance:

```bash
DATABASE_URL=sqlite+aiosqlite:///adal_instance2.db uv run adal
```

---

## Contributing

### Development Setup

```bash
git clone https://github.com/anomalyco/ADAL.git
cd ADAL
cp .env.example .env
uv sync                      # core deps
uv sync --group dev           # + test/lint tools
```

### Dev Commands

```bash
uv run ruff check src/ tests/ --ignore E501,N806   # lint
uv run pytest tests/ -q                               # 47 tests, asyncio auto mode
```

No typecheck, no pre-commit hooks in CI. `ruff` with `--ignore E501,N806` is the only gate.

### Running Tests

Tests need no external services (no API keys, no DB). They mock LLM calls and run in isolated environments.

```bash
uv run pytest tests/ -v
```

### PR Workflow

1. Create a feature branch
2. Make changes, ensure `ruff check` passes
3. Run `uv run pytest tests/ -q` — all 47 tests must pass
4. Submit PR — Greptile reviews all changes

### Architecture Notes

- **FSM is Python-controlled**, not LLM-driven. `PlannerAction` is a typed enum evaluated by a `try/except ValueError` in the orchestrator.
- **Always use `parse_json_block(response)`** — 7-stage extraction with `strict=False`. DeepSeek outputs literal `\n` in JSON strings.
- **Prompt engineering rules**: Every prompt starts with an anti-bias 1-liner. Equipment defaults to mid-1900s. Proposer must include precursor syntheses.
- **Memory injection requires two changes**: add `{_session_memory}` to the prompt template AND pass it in `build_prompt()`.
- **Tool names in prompts**: Explicitly say `web_search(query="...")` not `search_web`, `fetch_url(url="...")` not `fetch`.
- **Sandbox**: `ALLOWED_IMPORTS` is defined in `execution/sandbox.py`. Add new libraries there (not in prompts).

### Project Structure

```
src/adal/
├── agents/          # Planner, Proposer, Verifier + base
├── api/             # FastAPI REST server
├── cli.py           # Typer CLI (adal tui / adal api)
├── config.py        # Pydantic settings from .env
├── db/              # SQLAlchemy models + session
├── domains/         # Domain-specific validators
│   ├── astrophysics/
│   ├── chemistry/
│   ├── physics/
│   └── particle_nuclear/
├── execution/       # Sandbox execution
├── llm/             # Provider-agnostic LLM client
├── loop/            # Orchestrator FSM
├── memory/          # LanceDB vector memory
├── prompts/         # Agent system prompts
├── tools/           # Web search + fetch + calculate
└── tui/             # Textual interface
    ├── screens/     # All screens (welcome, dashboard, settings, etc.)
    └── widgets/     # Reusable widgets (chat_history, spinner, input)
```

---

## License

MIT

---

*ADAL v1.0 — Built for independent researchers and scientific enthusiasts.*
