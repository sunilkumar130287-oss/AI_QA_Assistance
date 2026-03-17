​
# Autonomous AI Coding Agent Framework

 

> **Human Architects. Agent Implements.**

 

Enterprise-grade autonomous coding agent that takes a Jira story ID + Git repository, then autonomously: understands the task → scans the codebase → plans the work → writes tests (TDFlow) → implements code → verifies everything → creates a pull request.

 

---

 

## Architecture

 

```

┌─────────────────────────────────────────────────┐

│                   main.py (CLI)                 │

│          argparse → config → orchestrator       │

└────────────────────┬────────────────────────────┘

                     │

        ┌────────────▼────────────────────┐

        │   bootstrap/lumin8_bootstrap.py │

        │   iConfig + feature flags init  │

        └────────────┬────────────────────┘

                     │

┌────────────────────▼────────────────────────────┐

│            core/orchestrator.py                  │

│  State → Skill → Context → Repo → Plan →        │

│  Test → Code → Review (loop) → PR               │

│  + env-only failure detection (early exit)       │

│  + skip_stages support (from skill YAML)         │

│  + agent branch → PR workflow                    │

└──┬────┬────┬────┬────┬────┬────┬────────────────┘

   │    │    │    │    │    │    │

   ▼    ▼    ▼    ▼    ▼    ▼    ▼

 Context Repo Planner Test Coder Review   ← agents/

 Agent   Agent Agent  Agent Agent Agent

   │    │    │    │    │    │

   └────┴────┴────┴────┴────┘

              │

   ┌──────────▼──────────┐

   │   tools/ (9 tools)  │     perception/

   │  jira git file build│     repo_map

   │  test ast search lsp│     skeleton_generator

   └──────────┬──────────┘     context_compressor

              │

   ┌──────────▼──────────┐

   │  core/llm_client.py │ ← ALL LLM calls

   │   (Torri Proxy)     │   credentials via iConfig / pyconfig / env

   └─────────────────────┘

```

 

## Features

 

- **CodeAct Loop** — Think → Act → Observe → Reflect → Repeat (every agent)

- **Required-Tool Enforcement** — Agents declare `required_tools`; COMPLETE is blocked until all are called, with exact-format nudges and auto-execute fallback after 3 consecutive blocks

- **TDFlow** — Tests written *before* implementation; reviewer verifies they pass

- **Skills as Data** — YAML-based skill definitions; new capability = new YAML file

- **9 Tools** — Jira, Git, File, Build, Test, AST, Search, LSP (fallback), plus base

- **Perception Engine** — Repo map with PageRank, skeleton generation, context compression

- **Single LLM Gateway** — All calls route through `core/llm_client.py` → Torri proxy (GPT-5 via Azure)

- **Smart Review Loops** — Failed reviews trigger re-implementation with review feedback injected; retry reviews are iteration-budgeted and context-aware

- **Environment-Aware Reviews** — Reviewer distinguishes env issues (Maven not found) from code issues; orchestrator auto-exits retry loops for env-only failures

- **Agent Branch Workflow** — Agent creates `agent/<jira>_<task>` branch, works there, PRs back to user's input branch for human review

- **Skill Step Injection** — Coder receives mandatory step-by-step checklists from skill YAML; reviewer verifies all steps were implemented

- **Retry Intelligence** — On retry loops: coder skips completed steps, reviewer gets previous comments, iteration budgets are reduced

- **Build Pre-flight Checks** — `build_tool check_available` and `test_tool` pre-flight binary detection prevent wasted iterations when build tools are absent

- **Structured Logging** — JSON file output + rich console, correlation IDs throughout

- **Security** — File ops sandboxed, no force pushes, subprocess timeouts, path traversal blocked

- **Credential Resolution** — 4-tier priority: config.yaml → iConfig singleton → pyconfig → env vars

 

## Project Structure

 

```

Autonomous-AI-Coding-Agent-Framework/

├── main.py                    # CLI entry-point

├── config.yaml                # Configuration (env var interpolation)

├── config.env                 # Alternative env file for overrides

├── .env.example               # Environment variable template

├── requirements.txt           # Python dependencies

├── setup.py                   # Package setup

│

├── bootstrap/

│   ├── __init__.py

│   └── lumin8_bootstrap.py    # Lumin8 / iConfig / feature-flag init

│

├── config/

│   ├── __init__.py

│   ├── iconfig_loader.py      # IConfigLoader singleton for secrets

│   ├── git_token_provider.py  # Git token resolution from iConfig

│   ├── torri_proxy_config.py  # Torri proxy URL/env mapping

│   └── feature_flag_client.py # Feature flag evaluation

│

├── core/

│   ├── __init__.py

│   ├── exceptions.py          # Full exception hierarchy

│   ├── logger.py              # Structured logging + correlation IDs

│   ├── state.py               # PipelineState dataclass (audit trail + review_attempt tracking)

│   ├── llm_client.py          # Torri proxy gateway (retry, timeout, 4-tier cred resolution)

│   └── orchestrator.py        # Pipeline controller + env-only failure detection + agent branch workflow

│

├── services/

│   ├── __init__.py

│   └── llm_proxy_client.py    # Low-level HTTP client for LLM proxy

│

├── tools/

│   ├── __init__.py

│   ├── base_tool.py           # BaseTool ABC + ToolResult

│   ├── jira_tool.py           # Jira CRUD + acceptance criteria parsing

│   ├── git_tool.py            # Clone, branch, commit, push, PR, diff, stage_all, robust filename parsing

│   ├── file_tool.py           # Read, write, search, replace (sandboxed)

│   ├── build_tool.py          # Detect + build + check_available (Maven/Gradle/npm/Python)

│   ├── test_tool.py           # Run tests + pre-flight binary check, parse JUnit XML

│   ├── ast_tool.py            # Parse AST, dependency graph, skeletons

│   ├── search_tool.py         # Regex + TF-IDF semantic search

│   └── lsp_tool.py            # Fallback LSP via AST + search

│

├── perception/

│   ├── __init__.py

│   ├── repo_map.py            # Scan → parse → graph → PageRank → skeleton

│   ├── skeleton_generator.py  # Python/Java/JS skeleton extraction

│   └── context_compressor.py  # Token budget management

│

├── agents/

│   ├── __init__.py

│   ├── base_agent.py          # CodeAct loop + required-tool enforcement + auto-execute fallback

│   ├── context_agent.py       # Agent 1: Jira story understanding

│   ├── repo_agent.py          # Agent 2: Codebase analysis (capped at 12 iterations)

│   ├── planner_agent.py       # Agent 3: Execution planning (output_only, capped at 3 iterations)

│   ├── test_agent.py          # Agent 4: Write failing tests (TDFlow)

│   ├── coder_agent.py         # Agent 5: Implementation + skill step injection + review feedback

│   └── reviewer_agent.py      # Agent 6: Environment-aware QA + retry-aware iteration budgets

│

├── skills/

│   ├── __init__.py

│   ├── skill_loader.py        # YAML skill discovery + validation

│   ├── java_21_upgrade.yaml   # Java 21 upgrade skill (9-step, org-specific)

│   ├── story_implementation.yaml

│   ├── spring_boot_upgrade.yaml

│   ├── java_upgrade.yaml

│   ├── angular_upgrade.yaml

│   └── write_tests.yaml

│

├── iconfig/                   # iConfig assembly + env descriptor files

│   ├── assembly/

│   └── env/

│

├── workspace/                 # Agent working directory (cloned repos + checkpoints)

│

└── tests/

    ├── __init__.py

    ├── test_llm_client.py     # Torri proxy gateway tests

    ├── test_tools.py          # All 9 tools tested

    ├── test_agents.py         # CodeAct loop + all 6 agents

    ├── test_orchestrator.py   # Full pipeline with mocked agents

    └── test_perception.py     # Repo map, skeleton gen, compression

```

 

## Quick Start

 

### 1. Prerequisites

 

- Python 3.11+

- Access to a Torri-compatible LLM proxy endpoint (corporate GPT-5 via Azure)

- Jira and Git credentials (via iConfig, pyconfig, or env vars)

 

### 2. Install

 

```bash

git clone <repo-url>

cd Autonomous-AI-Coding-Agent-Framework

pip install -e ".[dev]"

```

 

### 3. Configure

 

Copy the environment template and fill in your values:

 

```bash

cp .env.example .env

```

 

Key environment variables:

 

| Variable | Description | Default |

|---|---|---|

| `TORRI_PROXY_ENV` | Torri environment (`sbx`, `dev`, `qa`, `npd`, `prd`) | `dev` |

| `TORRI_PROXY_USERNAME` | Torri proxy client ID (or set via iConfig) | — |

| `TORRI_PROXY_PASSWORD` | Torri proxy client secret (or set via iConfig) | — |

| `TORRI_MODEL` | Model name | `amt-gpt_5-2025-08-07-pyg-1` |

| `AGENT_APP_ID` | Application ID for Torri routing | `ap178392` |

| `JIRA_BASE_URL` | Jira REST API URL | `https://jira.fmr.com/rest/api/2/search` |

| `JIRA_API_TOKEN` | Jira auth token (Basic or Bearer) | — |

| `JIRA_USERNAME` | Jira username | — |

| `GIT_PROVIDER` | Git provider (`github` or `bitbucket`) | `github` |

| `GIT_API_URL` | Git API base URL | `https://github.fmr.com/api/v3` |

| `GIT_API_TOKEN` | Git provider token | — |

 

**Credential resolution order** (for Torri):

1. Explicit values in `config.yaml` → 2. `IConfigLoader` singleton → 3. `pyconfig` → 4. Env vars

 

### 4. Run

 

```bash

# Implement a Jira story

python main.py --jira PROJ-1234 --repo https://github.com/org/repo --branch feature/xyz

 

# Write tests only (TDFlow)

python main.py --jira PROJ-1234 --repo https://github.com/org/repo --branch develop --task write_tests

 

# Specific skill (e.g., Java 21 upgrade)

python main.py --jira PROJ-1234 --repo https://github.com/org/repo --branch main --task java_21_upgrade

 

# Dry run (validate config only)

python main.py --jira PROJ-1234 --repo https://github.com/org/repo --branch main --dry-run

 

# Verbose logging

python main.py --jira PROJ-1234 --repo https://github.com/org/repo --branch main -v

```

 

### 5. Test

 

```bash

pytest tests/ -v

```

 

## Pipeline Flow

 

```

 1. Bootstrap          iConfig, feature flags, credential resolution

                       │

 2. Load Skill         Match --task to YAML skill → set skip_stages, steps, context

                       │

 3. Context Agent      Fetch Jira story → extract requirements + acceptance criteria

                       │

 4. Clone Repo         Clone to workspace/<JIRA_ID>/, create agent/<jira>_<task> branch

                       │

 5. Repo Agent         Scan codebase: tech stack, file map, dependencies

                       │                   (capped at 12 iterations)

 6. Planner Agent      Generate ordered execution plan from skill steps

                       │                   (output_only mode, capped at 3 iterations)

 7. Test Agent         Write failing tests per plan (TDFlow)

                       │                   (skippable via skill skip_stages)

                       │

                       ▼

        ┌──────── Review Loop (max 3 attempts) ────────┐

        │                                               │

        │  8. Coder Agent                               │

        │     • Receives mandatory skill step checklist │

        │     • On retry: gets review feedback,         │

        │       skips completed steps, lists            │

        │       already-modified files                  │

        │                                               │

        │  9. Reviewer Agent                            │

        │     • Checks build availability first         │

        │     • Verifies diff against skill steps       │

        │     • On retry: max 12 iters, focused on      │

        │       verifying previous issues fixed         │

        │     • Env-only failures → exit immediately    │

        │                                               │

        └── PASS → continue  │  FAIL → back to step 8 ─┘

                              │

10. Commit, Pull & Push   Idempotent stage_all + commit, then always pull latest remote changes before push to agent branch (prevents non-fast-forward errors)

                          │

11. PR Creation           Auto-create PR: agent/<jira>_<task> → user's input branch

```

 

## Required-Tool Enforcement & Auto-Execute

 

The CodeAct loop in `base_agent.py` implements a three-tier enforcement mechanism for agents that declare `required_tools`:

 

| Tier | Trigger | Behavior |

|---|---|---|

| **Nudge** | COMPLETE emitted but required tools unused | Block completion; inject exact-format tool call template (THINKING/ACTION/ARGS) the LLM can copy verbatim |

| **Urgent Warning** | ≥60% iterations consumed, tools still unused | Append `⚠️ WARNING` to every tool result: "Stop exploring and call the required tool(s) NOW" |

| **Auto-Execute** | 3 consecutive COMPLETE-blocked attempts | Framework auto-executes the missing tool with sensible defaults, injects result as `[AUTO-EXECUTED]`, resets counter |

 

This prevents the worst-case scenario observed in earlier runs where the LLM wasted 14 consecutive iterations trying to emit COMPLETE without calling `git_tool`.

 

## Environment-Aware Review System

 

The framework intelligently handles environments where build tools (Maven, Gradle, etc.) may not be installed locally:

 

| Component | Behavior |

|---|---|

| **`build_tool check_available`** | Pre-flight check: detects build system and reports availability without attempting execution |

| **`test_tool` pre-flight** | Checks for Maven/Gradle binary (`mvnw`, `mvn`, `MAVEN_HOME`) before running tests; returns "proceed with static review" if absent |

| **`reviewer_agent`** | Always calls `check_available` first; performs static-only review when build tools are unavailable |

| **`orchestrator._is_env_only_failure()`** | Pattern-matches review comments against ~20 environment-issue keywords; short-circuits retry loop if no code issues found |

 

This prevents the framework from wasting iteration cycles retrying builds/tests that will always fail in the local environment.

 

## Smart Review Loop

 

### Coder Agent — Retry Intelligence

 

When a review fails due to actual code issues, the coder agent receives:

 

1. **Filtered review feedback** — Environmental/informational comments are stripped; only actionable issues are shown in a prominent `╔══ REVIEW FEEDBACK — YOU MUST FIX THESE ISSUES ══╝` block

2. **Already-modified files list** — Files changed in previous loops are listed with "do NOT re-read" guidance

3. **Skip-completed directive** — "SKIP any skill step that was already completed in a previous loop. Focus ONLY on the review fixes and any MISSING steps."

 

### Reviewer Agent — Retry Optimization

 

On retry review loops (attempt 2+):

 

- **Reduced iteration budget** — Capped at 12 iterations (vs 35 for first review)

- **Previous comments injected** — Numbered list of prior review issues so the reviewer verifies fixes, not re-discovers problems

- **Diff-focused directive** — "Use `git_tool diff` to see what changed" instead of re-reading every file

 

## Skill Step Injection

 

Both coder and reviewer agents receive full skill step details from the YAML definition:

 

- **Coder** — Mandatory checklist with `⚠️ You MUST execute EVERY step` directive; each step rendered as `### Step N: <name>` with full instructions

- **Reviewer** — Expected steps with instruction previews for completeness verification against the diff

- **Planner** — Skill playbook with step names, agents, and instruction previews; directive to include ALL in the plan

 

## Agent Branch Workflow

 

```

user's input branch (e.g., feature/agent_java21_upgrade)

    │

    ├── agent creates: agent/gaacd-15938_java-21-upgrade

    │       │

    │       ├── coder makes changes

    │       ├── reviewer verifies

    │       ├── commit + push

    │       │

    │       └── PR created: agent/gaacd-15938_java-21-upgrade → feature/agent_java21_upgrade

    │

    └── human reviews PR and merges

```

 

## Adding a New Skill

 

Create a YAML file in `skills/`:

 

```yaml

name: my_new_skill

description: What this skill does

applicable_when:

  story_type: [ "feature", "enhancement" ]

  tech_stack: [ "python" ]

 

# Optional: skip stages that don't apply to this skill

skip_stages:

  - test_agent

 

# Optional: context block injected into coder agent

context: |

  Background information, migration patterns, org-specific conventions...

 

steps:

  - name: Step 1

    agent: coder_agent

    description: What this step does

    instruction: |

      Detailed instructions for the LLM, including code examples,

      file paths to modify, and expected outcomes.

    validation: How to verify this step was done correctly

 

  - name: Step 2

    agent: coder_agent

    description: Another step

    instruction: |

      More detailed instructions...

    validation: Expected outcome

```

 

No code changes needed — the skill loader auto-discovers new YAML files.

 

## Configuration

 

All configuration in `config.yaml` supports `${ENV_VAR:default}` interpolation:

 

```yaml

torri:

  env: ${TORRI_PROXY_ENV:dev}

  app_id: ${AGENT_APP_ID:ap178392}

  model: ${TORRI_MODEL:amt-gpt_5-2025-08-07-pyg-1}

  temperature: 0

  max_tokens: 32768                # increased from 16384 to avoid truncation on large files

  timeout_seconds: 180

  max_retries: 3

 

execution:

  max_agent_iterations: 35         # global per-agent iteration cap (agents can override lower)

  max_review_loops: 3              # coder → reviewer retry cap

  command_timeout_seconds: 300     # subprocess timeout

 

perception:

  max_files_to_scan: 500

  max_depth: 10

```

 

### Per-Agent Iteration Budgets

 

| Agent | Iterations | Notes |

|---|---|---|

| `context_agent` | 35 (global) | Jira fetch is typically 2-3 iterations |

| `repo_agent` | **12** (override) | `list_files` + `read build file` + `rank_modules` + skeletons + COMPLETE |

| `planner_agent` | **3** (override) | `output_only` mode — usually completes in 1 iteration |

| `test_agent` | 35 (global) | Skippable via `skip_stages` in skill YAML |

| `coder_agent` | 35 (global) | Needs full budget for multi-step skills |

| `reviewer_agent` | 35 / **12** (retry) | Full budget on first review; capped at 12 on retry loops |

 

## Tool Reference

 

| Tool | Actions | Description |

|---|---|---|

| `jira_tool` | `get_issue`, `search`, `add_comment` | Jira CRUD + acceptance criteria parsing |

| `git_tool` | `clone`, `branch`, `commit`, `pull`, `push`, `create_pr`, `diff`, `get_changed_files`, `reset_file`, `stage_all` | Git operations; robust filename parsing (ANSI stripping, rename handling, quoted paths). Always pulls before push to avoid remote update conflicts. |

| `file_tool` | `read`, `write`, `replace`, `search`, `list` | Sandboxed file operations with path traversal protection |

| `build_tool` | `detect`, `compile`, `build`, `clean`, `check_available` | Auto-detect build system; `check_available` validates without executing |

| `test_tool` | `run_tests`, `run_single_test`, `list_tests` | Pre-flight binary check; JUnit XML parsing |

| `ast_tool` | `parse`, `dependencies`, `skeleton`, `find_symbol`, `rank_modules`, `get_file_skeleton` | Language-aware AST analysis (Python, Java, JS/TS); PageRank module ranking |

| `search_tool` | `regex`, `semantic`, `find_files` | Codebase search with TF-IDF semantic matching |

| `lsp_tool` | `definition`, `references`, `hover` | Fallback LSP via AST + search |

 

## Robustness Features

 

| Feature | Description |

|---|---|

| **Safe JSON Parsing** | `_safe_json_loads` with brace-depth counting handles trailing content, markdown fences, and double JSON objects |

| **Flexible ARGS Parsing** | Accepts any language tag on code fences (`json`, `java`, `python`, bare), plus inline JSON fallback |

| **Auto-Inject Args** | Auto-injects `jira_id` into `jira_tool` calls when the LLM omits it |

| **Stage Retry** | Each agent stage gets up to 2 automatic retries on `AgentFrameworkError` |

| **HITL Resume** | `orchestrator.resume()` enables human-in-the-loop: inject feedback or approve directly |

| **Escalation** | Auto-escalates to human when review fails repeatedly or errors accumulate (≥5) |

| **Windows Cleanup** | `shutil.rmtree` with `chmod` handler for read-only `.git/objects/pack` files on Windows |

| **Git Safety** | Force pushes blocked; subprocess timeouts enforced; path traversal protection |

 

## Design Principles

 

1. **No frameworks** — Pure Python with dataclasses and type hints

2. **Tools are dumb** — Tools execute; agents decide

3. **Skills as data** — All domain knowledge in YAML

4. **Single LLM gateway** — Every call through `LLMClient`

5. **Fail loudly** — Rich exception hierarchy with context

6. **Audit everything** — `PipelineState` is the full audit trail

7. **Security first** — Sandboxed file ops, no force push, subprocess limits

8. **Environment resilience** — Gracefully degrade when build tools are unavailable

9. **Iteration efficiency** — Required-tool enforcement, auto-execute fallback, retry-aware budgets, review feedback injection

10. **Professional git workflow** — Agent branch → PR → human review

 

## Changelog

### v3.1 (2026-03-13)

 

**Workflow Robustness: Always Pull Before Push**

 

- **`git_tool.py`**: Added `pull` action and `_pull` method for branch sync.

- **`orchestrator.py`**: Now always pulls latest remote changes before pushing agent branch, preventing non-fast-forward push errors when remote has diverged.

- **README.md**: Updated Pipeline Flow and Tool Reference to document pull-before-push workflow.

 

### v3.0 (2026-03-11)

 

**Performance Optimization & Iteration Efficiency**

 

- **`base_agent.py`**: Required-tool enforcement rewritten with three-tier system:

  1. **Exact-format nudge** — When COMPLETE is blocked, injects copy-paste-ready THINKING/ACTION/ARGS template with concrete example args (not just "please call X")

  2. **Iteration-aware warning** — At 60% budget consumed, appends ⚠️ to every tool result

  3. **Auto-execute fallback** — After 3 consecutive COMPLETE-blocked attempts, auto-executes the missing tool with sensible defaults and injects results. Eliminates infinite loops entirely.

- **`base_agent.py`**: `_consecutive_complete_blocked` counter tracks and resets on successful tool calls or completion

- **`reviewer_agent.py`**: Added `run()` override — retry reviews (attempt 2+) capped at 12 iterations instead of 35

- **`reviewer_agent.py`**: Retry loops now receive previous review comments + "this is review attempt #N" context + "use git_tool diff" directive

- **`coder_agent.py`**: Retry loops now list already-modified files with "do NOT re-read" guidance + "SKIP completed steps" directive

- **`repo_agent.py`**: Stronger required-tool directives with ⚠️ inline annotations at critical steps

- **`git_tool.py`**: `_get_changed_files()` now strips ANSI escape sequences, handles renamed files (`old -> new`), unquotes paths with special characters, and skips empty paths

- **`core/state.py`**: Added `review_attempt: int` field for retry-aware agent behavior

- **`core/orchestrator.py`**: Sets `state.review_attempt` before each reviewer run

 

**Estimated Impact**: ~1100s saved per pipeline run. The 14-iteration COMPLETE-blocked deadlock (625s) is now capped at 3 blocked + 1 auto-execute (~140s max).

 

### v2.1 (2026-03-10)

 

**Skill Step Injection & Review Intelligence**

 

- **`coder_agent.py`**: Mandatory skill step checklist injected from skill YAML with `⚠️ You MUST execute EVERY step` directive

- **`coder_agent.py`**: Review feedback filtering — env/informational comments suppressed; actionable issues highlighted in `╔══ REVIEW FEEDBACK ══╝` box

- **`reviewer_agent.py`**: Skill step names + instruction previews passed to reviewer for completeness verification

- **`reviewer_agent.py`**: Clearer pass/fail rules — advisory suggestions ≠ failure; only fail for build-breaking issues

- **`planner_agent.py`**: Skill step pass-through to planner under **Skill Playbook** section

- **`config.yaml`**: `max_agent_iterations` increased from 25 → 35

 

### v2.0 (2026-03-09)

 

**Environment-Aware Pipeline Improvements**

 

- **`config.yaml`**: Increased `max_tokens` from 16384 → 32768 to prevent `finish_reason='length'` truncation on large file generation

- **`build_tool.py`**: Added `check_available` action — pre-flight build system detection without execution

- **`test_tool.py`**: Added `_check_build_binary()` pre-flight check for Maven/Gradle binaries before attempting test runs

- **`git_tool.py`**: Added `stage_all` action (`git add -A`) so new/untracked files appear in diffs and commits

- **`reviewer_agent.py`**: Rewritten system prompt to check build availability first; skip build/test steps when unavailable; distinguish environment vs code failures

- **`coder_agent.py`**: Added iteration efficiency rules ("don't re-read files", "skip build if Maven not found"); review feedback from previous cycles now injected into initial message

- **`orchestrator.py`**: Added `_is_env_only_failure()` pattern matcher (20+ env-issue keywords); review loop now exits immediately for environment-only failures instead of exhausting all retries

 

### v1.0 (2026-03-08)

 

**Initial Release**

 

- Full CodeAct loop implementation with 6 specialized agents

- 9-tool toolkit (Jira, Git, File, Build, Test, AST, Search, LSP)

- Perception engine with PageRank module ranking

- YAML skill system with auto-discovery

- TDFlow test-first pipeline

- 4-tier credential resolution (config → iConfig → pyconfig → env)

- Structured logging with correlation IDs

- Human-in-the-loop resume capability

 

## License

 

Internal use. See SECURITY.md for security policies.

 

# To run as a REST API with OpenAPI docs (FastAPI):

#   pip install fastapi uvicorn pydantic

#   python fastapi_app.py

#

# The CLI remains available via main.py as before.
