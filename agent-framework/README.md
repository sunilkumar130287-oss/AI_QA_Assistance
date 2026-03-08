# Autonomous AI Coding Agent Framework

Enterprise-grade autonomous coding agent that follows the "Human-Architect, Agent-Implementer" paradigm. Given a Jira story ID and Git repository, the system autonomously understands the task, scans the codebase, plans the work, writes tests, implements code, verifies everything, and creates a pull request.

## Architecture

```
User Input (Jira ID + Repo URL + Branch + Task Type)
        |
        v
+--------------------------------------------------+
|              ORCHESTRATOR (orchestrator.py)        |
|   Loads skill -> Runs agents in sequence/loop      |
|   Manages state, retries, error recovery           |
+------------------------+-------------------------+
                         |
    +--------------------+--------------------+
    v                    v                    v
+--------+        +----------+         +----------+
| TOOLS  |        |  AGENTS  |         |  SKILLS  |
| (Det.) |        | (LLM)    |         | (YAML)   |
+--------+        +----------+         +----------+
                       |
                       v
              +---------------+
              |  LLM CLIENT   |
              | (Torri Proxy) |
              +---------------+
```

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your Torri URL, Jira credentials, Git token

# 3. Run
python main.py \
  --jira PROJ-1234 \
  --repo https://git.company.com/team/service.git \
  --branch main \
  --task spring_boot_upgrade
```

## Task Types

| Task Type | Description |
|-----------|-------------|
| `spring_boot_upgrade` | Upgrade Spring Boot version (javax to jakarta, Security, etc.) |
| `java_upgrade` | Upgrade Java version (11 to 17, 17 to 21) |
| `angular_upgrade` | Upgrade Angular version |
| `story_implementation` | Implement a Jira feature or bug fix |
| `write_tests` | Write developer tests for existing code |

## Pipeline Flow

1. **Context Agent** - Fetches and parses the Jira story
2. **Repo Agent** - Scans codebase, detects tech stack, builds dependency graph
3. **Planner Agent** - Creates step-by-step execution plan
4. **Test Agent** - Writes tests first (TDFlow - tests must fail initially)
5. **Coder Agent** - Implements code changes with build/test verification
6. **Reviewer Agent** - QA review, creates commit and PR

## Configuration

All configuration in `config.yaml` with environment variable interpolation:

- **torri**: LLM proxy connection (base_url, api_key, model)
- **jira**: Jira REST API credentials
- **git**: Git provider settings (GitHub/Bitbucket)
- **execution**: Agent iteration limits, timeouts
- **logging**: Log level, format, output file

## Adding New Skills

Create a YAML file in `skills/`:

```yaml
name: my_new_skill
description: "What this skill does"
applicable_when:
  story_type: upgrade
  tech_stack_contains: react
context: |
  Migration guide and patterns...
steps:
  - name: "Step 1"
    agent: coder_agent
    instruction: "What to do"
    validation: "build_passes"
```

## Testing

```bash
pytest tests/ -v
```

## Key Design Principles

- **Single LLM Gateway**: All LLM calls route through `core/llm_client.py`
- **Tools are Deterministic**: No LLM calls inside tools
- **TDFlow**: Tests written before code, must fail first
- **Fail Fast**: Agents escalate after 3 failed attempts
- **Skills are Data**: YAML files, no Python changes needed
- **Observability**: Every call logged with correlation IDs
- **Security**: File ops sandboxed, no force pushes, timeouts on all commands
