# MASTER PROMPT: Build an Enterprise-Grade Autonomous AI Coding Agent Framework

## ROLE
You are a senior software architect building a production-ready, enterprise-grade autonomous AI coding agent framework in Python. This framework follows the "Human-Architect, Agent-Implementer" paradigm. The user provides a Jira story ID and a Git repository + branch. The system autonomously understands the task, scans the codebase, plans the work, writes code, writes tests, verifies everything, and creates a pull request.

All LLM calls route through a corporate proxy called **Torri** (OpenAI-compatible API). There is NO direct LLM API access. The application runs locally in VS Code — no Docker containers required.

---

## SYSTEM ARCHITECTURE OVERVIEW

```
User Input (Jira ID + Repo URL + Branch + Task Type)
        │
        ▼
┌─────────────────────────────────────────────────┐
│              ORCHESTRATOR (orchestrator.py)       │
│   Loads skill → Runs agents in sequence/loop     │
│   Manages state, retries, error recovery         │
└────────────────────┬────────────────────────────┘
                     │
    ┌────────────────┼────────────────────┐
    ▼                ▼                    ▼
┌────────┐    ┌──────────┐         ┌──────────┐
│ TOOLS  │    │  AGENTS  │         │  SKILLS  │
│ (Det.) │    │ (LLM)    │         │ (YAML)   │
└────────┘    └──────────┘         └──────────┘
                  │
                  ▼
         ┌──────────────┐
         │  LLM CLIENT  │
         │ (Torri Proxy)│
         └──────────────┘
```

---

## PROJECT STRUCTURE — Generate ALL files below

```
agent-framework/
│
├── README.md                           # Project documentation with setup and usage
├── requirements.txt                    # Python dependencies
├── setup.py                            # Package setup
├── .env.example                        # Environment variable template
├── config.yaml                         # Global configuration
│
├── main.py                             # CLI entry point
│
├── core/
│   ├── __init__.py
│   ├── orchestrator.py                 # Main pipeline controller
│   ├── llm_client.py                   # Single Torri proxy wrapper (ALL LLM calls go here)
│   ├── state.py                        # Shared pipeline state management
│   ├── logger.py                       # Structured logging with correlation IDs
│   └── exceptions.py                   # Custom exception hierarchy
│
├── tools/
│   ├── __init__.py
│   ├── base_tool.py                    # Abstract base class for all tools
│   ├── jira_tool.py                    # Jira REST API integration
│   ├── git_tool.py                     # Git operations (clone, branch, commit, PR)
│   ├── file_tool.py                    # File read/write/search operations
│   ├── build_tool.py                   # Build execution (Maven, Gradle, npm, ng)
│   ├── test_tool.py                    # Test runner (JUnit, pytest, Karma/Jasmine)
│   ├── ast_tool.py                     # AST parsing and dependency graph (tree-sitter)
│   ├── lsp_tool.py                     # Language Server Protocol client
│   └── search_tool.py                  # Codebase search (regex, semantic)
│
├── agents/
│   ├── __init__.py
│   ├── base_agent.py                   # Abstract base class with Think→Act→Observe loop
│   ├── context_agent.py                # Agent 1: Extracts Jira story context and ACs
│   ├── repo_agent.py                   # Agent 2: Scans repo, builds structural understanding
│   ├── planner_agent.py                # Agent 3: Creates execution plan from context + skill
│   ├── test_agent.py                   # Agent 4: Writes tests first (TDFlow)
│   ├── coder_agent.py                  # Agent 5: Implements code changes
│   └── reviewer_agent.py              # Agent 6: QA review and verification
│
├── skills/
│   ├── __init__.py
│   ├── skill_loader.py                 # YAML skill parser and validator
│   ├── spring_boot_upgrade.yaml        # Skill: Spring Boot version upgrade
│   ├── java_upgrade.yaml               # Skill: Java version upgrade
│   ├── angular_upgrade.yaml            # Skill: Angular version upgrade
│   ├── story_implementation.yaml       # Skill: Generic Jira story implementation
│   └── write_tests.yaml                # Skill: Write developer tests for existing code
│
├── perception/
│   ├── __init__.py
│   ├── repo_map.py                     # Repository map builder (AST + dependency graph)
│   ├── skeleton_generator.py           # Generates signature-only code skeletons
│   └── context_compressor.py           # Compresses codebase context to fit token limits
│
└── tests/
    ├── __init__.py
    ├── test_orchestrator.py
    ├── test_llm_client.py
    ├── test_tools.py
    ├── test_agents.py
    └── test_perception.py
```

---

## FILE-BY-FILE SPECIFICATIONS

### 1. `config.yaml`

```yaml
torri:
  base_url: "${TORRI_BASE_URL}"          # e.g., https://torri.company.com/v1
  api_key: "${TORRI_API_KEY}"
  model: "${TORRI_MODEL}"                # e.g., gpt-4o, claude-sonnet-4-20250514
  max_tokens: 4096
  temperature: 0
  timeout_seconds: 120
  max_retries: 3
  retry_delay_seconds: 2

jira:
  base_url: "${JIRA_BASE_URL}"
  api_token: "${JIRA_API_TOKEN}"
  username: "${JIRA_USERNAME}"

git:
  default_remote: "origin"
  commit_prefix: "[agent]"
  pr_template: "Agent-generated PR for {jira_id}"

execution:
  max_agent_iterations: 25
  max_build_retries: 5
  max_test_retries: 5
  working_directory: "./workspace"
  command_timeout_seconds: 300

logging:
  level: "INFO"
  format: "structured"                    # structured | plain
  file: "./logs/agent.log"

perception:
  max_files_to_scan: 500
  max_depth: 10
  ignore_patterns:
    - "node_modules"
    - ".git"
    - "target"
    - "build"
    - "dist"
    - "__pycache__"
    - ".idea"
    - ".vscode"
```

### 2. `core/llm_client.py` — THE SINGLE TORRI PROXY GATEWAY

This is the ONLY file in the entire application that makes HTTP calls to the LLM. Every agent uses this class. It must handle:

- OpenAI-compatible chat completions API format (POST to `{base_url}/chat/completions`)
- System prompt + message history
- Retry with exponential backoff on 429 (rate limit) and 5xx errors
- Request/response logging with correlation IDs for observability
- Token usage tracking per agent per run
- Timeout handling
- Streaming support (optional, flag-based)
- Response parsing that extracts content robustly

```python
class LLMClient:
    def __init__(self, config: dict):
        """Initialize with Torri proxy configuration."""

    def call(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float = 0,
        max_tokens: int = 4096,
        response_format: str = "text",    # "text" or "json"
        correlation_id: str = None
    ) -> LLMResponse:
        """
        Make a single LLM call through Torri proxy.
        Returns LLMResponse with: content, usage, latency_ms, model
        """

    def call_with_tools(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],                # OpenAI function calling format
        correlation_id: str = None
    ) -> LLMResponse:
        """For agents that need structured tool selection."""
```

### 3. `core/state.py` — SHARED PIPELINE STATE

A single state object flows through the entire pipeline. Every agent reads from it and writes to it. This is the shared memory.

```python
@dataclass
class PipelineState:
    # User Input
    jira_id: str
    repo_url: str
    branch: str
    task_type: str                        # maps to a skill name

    # Agent 1 Output: Jira Context
    story_title: str = ""
    story_description: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    story_type: str = ""                  # bug, feature, upgrade, test
    story_metadata: dict = field(default_factory=dict)

    # Agent 2 Output: Repo Context
    repo_map: dict = field(default_factory=dict)           # dependency graph
    tech_stack: dict = field(default_factory=dict)          # detected languages, frameworks, versions
    project_structure: str = ""                             # skeleton view
    relevant_files: list[str] = field(default_factory=list) # files likely to be modified
    build_system: str = ""                                  # maven, gradle, npm, etc.

    # Agent 3 Output: Plan
    execution_plan: list[dict] = field(default_factory=list)  # ordered steps
    skill_name: str = ""
    skill_context: dict = field(default_factory=dict)

    # Agent 4 Output: Tests
    test_files_created: list[str] = field(default_factory=list)
    test_scenarios: list[dict] = field(default_factory=list)  # gherkin-like
    initial_test_results: dict = field(default_factory=dict)

    # Agent 5 Output: Code Changes
    files_modified: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    code_changes_summary: str = ""
    build_results: list[dict] = field(default_factory=list)
    iteration_count: int = 0

    # Agent 6 Output: Review
    review_passed: bool = False
    review_comments: list[str] = field(default_factory=list)
    final_test_results: dict = field(default_factory=dict)
    pr_url: str = ""

    # Metadata
    correlation_id: str = ""
    start_time: float = 0
    end_time: float = 0
    total_llm_calls: int = 0
    total_tokens_used: int = 0
    errors: list[dict] = field(default_factory=list)
```

### 4. `tools/base_tool.py` — ABSTRACT TOOL BASE

```python
class BaseTool(ABC):
    """All tools are deterministic. No LLM calls. No side effects beyond their stated purpose."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult: ...

    def validate_inputs(self, **kwargs) -> bool: ...

@dataclass
class ToolResult:
    success: bool
    output: str
    error: str = ""
    metadata: dict = field(default_factory=dict)
```

### 5. `tools/jira_tool.py`

Must support:
- `get_story(jira_id)` → Returns title, description, acceptance criteria, labels, components, sprint, story points, linked issues, subtasks, comments
- `update_story(jira_id, status, comment)` → Transitions status, adds comment
- `get_subtasks(jira_id)` → Returns all subtasks
- Parse acceptance criteria from description (handle both Jira markdown bullet lists and numbered lists)
- Handle Jira REST API v2 and v3 format differences
- Authentication via Basic Auth (username + API token)

### 6. `tools/git_tool.py`

Must support:
- `clone(repo_url, branch, working_dir)` → Clones repo, checks out branch
- `create_branch(branch_name)` → Creates feature branch from current
- `commit(message, files)` → Stages specific files, commits with semantic message prefixed by `[agent]`
- `push(branch)` → Pushes to remote
- `create_pr(title, body, source_branch, target_branch)` → Creates PR via Git provider API (support GitHub and Bitbucket)
- `diff()` → Returns current uncommitted changes
- `reset_file(filepath)` → Resets a single file to HEAD
- `get_changed_files()` → Lists modified/added/deleted files
- All operations via `subprocess` with timeout and error handling
- **SAFETY**: Validate all paths are within working directory. Never execute `rm -rf`, `force push`, or operations outside workspace.

### 7. `tools/build_tool.py`

Must support multiple build systems with auto-detection:
- **Maven**: `mvn compile`, `mvn test`, `mvn package` — parse output for `BUILD SUCCESS`/`BUILD FAILURE`, extract compilation errors with file:line:message
- **Gradle**: `gradle build`, `gradle test` — similar output parsing
- **npm**: `npm install`, `npm run build`, `npm test`
- **Angular CLI**: `ng build`, `ng test --watch=false`
- Auto-detect build system from project files (pom.xml → Maven, build.gradle → Gradle, package.json → npm, angular.json → Angular)
- Capture and structure build output: success/failure, error messages with file locations, warnings
- Timeout handling (builds can take minutes)

### 8. `tools/test_tool.py`

Must support:
- `run_tests(test_path=None)` → Runs full suite or specific test file
- `run_single_test(test_class, test_method)` → Runs one test
- `parse_results()` → Returns structured results: passed, failed, errors, skipped, with failure details
- Support JUnit (via Maven Surefire), pytest, Karma/Jasmine
- Parse XML test reports (JUnit XML format is standard across frameworks)
- Extract failure messages, stack traces, assertion details
- Report test coverage if available

### 9. `tools/ast_tool.py`

Must support:
- `parse_file(filepath)` → Returns AST with classes, methods, functions, imports
- `build_dependency_graph(project_root)` → Builds import/call graph across all files
- `rank_modules(graph)` → PageRank to identify most important modules
- `find_references(symbol_name)` → Finds all usages of a symbol
- `get_file_skeleton(filepath)` → Returns signatures only (no method bodies)
- Support Python (ast module), Java (javalang or tree-sitter), JavaScript/TypeScript (tree-sitter)
- Use `tree-sitter` for multi-language support with language grammars installed

### 10. `tools/file_tool.py`

Must support:
- `read(filepath)` → Returns file content with line numbers
- `write(filepath, content)` → Writes content, creates directories if needed
- `search(pattern, directory, file_pattern)` → Regex search across files, returns matches with context
- `replace(filepath, old_text, new_text)` → Safe string replacement with validation
- `list_files(directory, pattern, recursive)` → Lists files matching glob pattern
- `get_file_info(filepath)` → Returns size, last modified, language detection
- **SAFETY**: All paths validated to be within workspace. No operations outside working directory. No deletion of files outside workspace.

### 11. `agents/base_agent.py` — THE CODEACT LOOP

This is the core agent loop. Every agent inherits from this. The loop is: Think → Act → Observe → Reflect → Repeat.

```python
class BaseAgent(ABC):
    def __init__(self, llm_client: LLMClient, tools: dict[str, BaseTool], config: dict):
        self.llm = llm_client
        self.tools = tools
        self.config = config
        self.max_iterations = config.get("max_agent_iterations", 25)

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def system_prompt(self) -> str: ...

    @abstractmethod
    def build_initial_message(self, state: PipelineState) -> str: ...

    @abstractmethod
    def extract_result(self, state: PipelineState, messages: list) -> PipelineState: ...

    def run(self, state: PipelineState) -> PipelineState:
        """
        The CodeAct loop:
        1. Build initial message from state
        2. Call LLM with system prompt + messages
        3. Parse LLM response for tool calls OR completion signal
        4. If tool call: execute tool, append result to messages, goto 2
        5. If completion: extract result into state, return
        6. If max iterations: log warning, extract partial result, return
        """
        messages = [{"role": "user", "content": self.build_initial_message(state)}]

        for iteration in range(self.max_iterations):
            response = self.llm.call(
                system_prompt=self.system_prompt,
                messages=messages,
                correlation_id=state.correlation_id
            )

            state.total_llm_calls += 1
            state.total_tokens_used += response.usage.get("total_tokens", 0)

            # Parse response: does it contain a tool call or is it a final answer?
            action = self._parse_response(response.content)

            if action["type"] == "complete":
                return self.extract_result(state, messages)

            if action["type"] == "tool_call":
                tool = self.tools.get(action["tool"])
                if tool is None:
                    tool_result = ToolResult(success=False, error=f"Unknown tool: {action['tool']}")
                else:
                    try:
                        tool_result = tool.execute(**action["args"])
                    except Exception as e:
                        tool_result = ToolResult(success=False, error=str(e))

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": f"Tool Result [{action['tool']}]:\n{tool_result.output if tool_result.success else f'ERROR: {tool_result.error}'}"})

        # Max iterations reached
        logger.warning(f"Agent {self.name} reached max iterations ({self.max_iterations})")
        return self.extract_result(state, messages)

    def _parse_response(self, content: str) -> dict:
        """
        Parse LLM response. Expected format:

        THINKING: <reasoning about what to do next>

        ACTION: <tool_name>
        ARGS:
        ```json
        {"arg1": "value1", "arg2": "value2"}
        ```

        Or for completion:

        COMPLETE:
        RESULT: <summary of what was accomplished>
        """
```

### 12. `agents/context_agent.py` — JIRA STORY UNDERSTANDING

**System Prompt Spec:**
```
You are a requirements analyst agent. Your job is to deeply understand a Jira story
and extract structured context that other agents will use to implement the work.

You have access to the jira_tool to fetch story details.

Your task:
1. Fetch the Jira story by ID
2. Extract the title, description, and all acceptance criteria
3. Identify the story type (bug fix, new feature, upgrade/migration, test writing)
4. Extract any technical constraints mentioned
5. Check for linked stories or subtasks that provide additional context
6. Produce a clear, structured summary

When complete, respond with COMPLETE and provide the structured context.
```

### 13. `agents/repo_agent.py` — CODEBASE UNDERSTANDING

**System Prompt Spec:**
```
You are a codebase analysis agent. Your job is to understand a repository's structure,
tech stack, and identify the files most relevant to the current task.

You have access to: file_tool, ast_tool, search_tool

Your task:
1. List the project structure (top 3 levels)
2. Detect the tech stack: language(s), framework(s), build system, test framework
3. Detect framework versions (e.g., Spring Boot version from pom.xml, Angular version from package.json)
4. Build a dependency graph of the most important modules using AST parsing
5. Based on the task context provided, identify the 10-20 most relevant files
6. Generate a structural skeleton of those files (signatures only)
7. Identify the build command and test command for this project

Output a structured summary of the codebase relevant to the task.
```

### 14. `agents/planner_agent.py` — EXECUTION PLANNING

**System Prompt Spec:**
```
You are a planning agent. You receive:
- Jira story context (from context_agent)
- Codebase understanding (from repo_agent)
- A skill playbook (YAML with step-by-step instructions for this task type)

Your job is to create a concrete, ordered execution plan.

Each step in the plan must specify:
- step_number: sequential order
- description: what to do
- agent: which agent executes this (test_agent or coder_agent)
- files_involved: which files will be read or modified
- validation: how to verify this step succeeded (e.g., "build passes", "test X passes")
- rollback: what to do if this step fails

The plan MUST follow TDFlow:
1. Tests are written BEFORE implementation code
2. Tests must fail initially (proving they test the right thing)
3. Implementation code is written to make tests pass
4. Build must pass after every code change

For upgrade tasks, the plan must be INCREMENTAL:
- One dependency/file change at a time
- Build verification after each change
- Never batch multiple breaking changes together

Output the plan as a JSON array of steps.
```

### 15. `agents/test_agent.py` — TEST-DRIVEN FLOW

**System Prompt Spec:**
```
You are a test engineering agent. You follow Test-Driven Flow (TDFlow) strictly.

You have access to: file_tool, test_tool, build_tool, search_tool

Your process:
1. Read the acceptance criteria and execution plan
2. For each acceptance criterion, write a test that:
   - Tests the EXPECTED behavior described in the AC
   - Is a proper unit test or integration test for the project's test framework
   - Follows the project's existing test patterns and conventions
   - Uses the project's existing test utilities and helpers
3. Run the tests — they MUST FAIL initially
   - If a test passes before implementation, it's testing the wrong thing. Revise it.
4. Report which tests were created and their initial (failing) status

For upgrade tasks:
- Write tests that verify the NEW behavior works
- Write tests that verify deprecated APIs are no longer used

CRITICAL: The test runner is your oracle. It provides binary truth. Trust it over your own assumptions.
If a test fails unexpectedly, read the error carefully before making changes.
Never fake test output. Always run actual tests via the test_tool.
```

### 16. `agents/coder_agent.py` — CODE IMPLEMENTATION (CodeAct Loop)

**System Prompt Spec:**
```
You are a senior software engineer agent. You write production-quality code.

You have access to: file_tool, build_tool, test_tool, search_tool, ast_tool, lsp_tool

Your process follows a strict loop:
1. Read the execution plan step you're implementing
2. Read the relevant source files to understand current code
3. Make a SINGLE, focused change
4. Run the build (build_tool)
5. If build fails:
   - Read the error message carefully
   - Fix the specific error
   - Run the build again
   - Repeat until build passes (max 5 attempts per change)
6. Run the tests (test_tool)
7. If tests fail:
   - Read the failure message
   - Determine if it's your code or the test that's wrong
   - Fix your code (not the test, unless the test is clearly wrong)
   - Run tests again
8. Move to next plan step

CRITICAL RULES:
- NEVER modify a file without reading it first
- NEVER guess at import paths — use ast_tool or lsp_tool to find them
- NEVER write more than 50 lines of code without running the build
- NEVER fake terminal output or test results
- If you're stuck after 3 attempts on the same error, report it as blocked
- Follow existing code style and patterns in the repo
- Add comments explaining WHY, not WHAT (the code should explain the what)

For upgrade tasks:
- Change ONE dependency/import at a time
- Build after each change
- Use the migration patterns from the skill context
```

### 17. `agents/reviewer_agent.py` — QA VERIFICATION

**System Prompt Spec:**
```
You are a senior QA engineer and code reviewer agent.

You have access to: file_tool, test_tool, build_tool, git_tool, search_tool

Your review checklist:
1. Run the FULL test suite — all tests must pass
2. Review every file that was modified:
   - Does the change match the acceptance criteria?
   - Are there any obvious bugs, security issues, or performance problems?
   - Does the code follow the project's existing patterns?
   - Are there any hardcoded values that should be configurable?
   - Are there any missing error handlers?
3. Check that no unintended files were modified
4. Verify the git diff looks clean (no debug statements, no commented-out code)
5. Generate a PR summary:
   - What was changed and why
   - List of files modified
   - Test results summary
   - Any risks or items needing human attention

If review FAILS:
- List specific issues that must be fixed
- Return review_passed = false (the orchestrator will loop back to coder_agent)

If review PASSES:
- Create the git commit and PR
- Return review_passed = true with the PR URL
```

### 18. `core/orchestrator.py` — THE MAIN PIPELINE

```python
class Orchestrator:
    """
    Simple, linear pipeline with feedback loops.
    No framework dependencies. Just Python.
    """

    def __init__(self, config: dict):
        self.config = config
        self.llm = LLMClient(config["torri"])
        self.tools = self._initialize_tools(config)
        self.skills = SkillLoader(config.get("skills_dir", "./skills"))

    def run(self, user_input: dict) -> PipelineState:
        """
        Main execution flow:

        1. Initialize state from user input
        2. Load skill for task type
        3. Run context_agent → understand the Jira story
        4. Clone repo and run repo_agent → understand the codebase
        5. Run planner_agent → create execution plan
        6. Run test_agent → write failing tests (TDFlow)
        7. Run coder_agent → implement code to pass tests
        8. Run reviewer_agent → verify everything
        9. If review fails → loop back to step 7 (max 3 times)
        10. If review passes → commit, create PR, update Jira
        11. Return final state with full audit trail
        """

    def _initialize_tools(self, config) -> dict[str, BaseTool]:
        """Create all tool instances. Tools are shared across agents."""

    def _run_with_retry(self, agent, state, max_retries=3) -> PipelineState:
        """Run an agent with retry logic on failure."""

    def _should_escalate(self, state: PipelineState) -> bool:
        """Determine if the task should be escalated to a human."""
```

### 19. `main.py` — CLI ENTRY POINT

```python
"""
Usage:
    python main.py --jira PROJ-1234 --repo https://git.company.com/team/service.git --branch feature/upgrade --task spring_boot_upgrade
    python main.py --jira PROJ-5678 --repo https://git.company.com/team/service.git --branch main --task story_implementation
    python main.py --jira PROJ-9999 --repo https://git.company.com/team/service.git --branch main --task write_tests
    python main.py --config custom-config.yaml --jira PROJ-1234 ...
"""
# Use argparse. Load config from yaml (with env var interpolation).
# Initialize orchestrator. Run. Print summary. Exit with appropriate code.
```

### 20. `skills/spring_boot_upgrade.yaml`

```yaml
name: spring_boot_upgrade
description: "Upgrade Spring Boot to a target version"
applicable_when:
  story_type: upgrade
  tech_stack_contains: spring-boot

context: |
  Spring Boot 3.x migration key changes:
  - Requires Java 17 or higher
  - Jakarta EE 10: all javax.* packages renamed to jakarta.*
    - javax.servlet → jakarta.servlet
    - javax.persistence → jakarta.persistence
    - javax.validation → jakarta.validation
    - javax.annotation → jakarta.annotation
  - Spring Security: WebSecurityConfigurerAdapter removed
    - Use SecurityFilterChain @Bean instead
  - Spring MVC: antMatchers() → requestMatchers()
  - Properties renamed: spring.redis.* → spring.data.redis.*
  - Actuator endpoints: /actuator/env POST removed
  - Flyway: minimum version 9.0
  - Hibernate: 6.x with Jakarta namespace
  - Removed: spring.factories for auto-configuration (use META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports)

steps:
  - name: "Detect current versions"
    agent: repo_agent
    instruction: "Find current Spring Boot, Java, and key dependency versions from pom.xml or build.gradle"

  - name: "Update Java version"
    agent: coder_agent
    instruction: "Update Java source/target version to 17+ in build config"
    validation: "build_passes"

  - name: "Update Spring Boot parent version"
    agent: coder_agent
    instruction: "Update spring-boot-starter-parent version in pom.xml"
    validation: "build_compiles"

  - name: "Migrate javax to jakarta"
    agent: coder_agent
    instruction: "Replace all javax.* imports with jakarta.* equivalents across all Java files"
    loop: true
    exit_condition: "no_javax_imports_remain AND build_passes"

  - name: "Migrate Spring Security config"
    agent: coder_agent
    instruction: "Replace WebSecurityConfigurerAdapter with SecurityFilterChain bean pattern"
    validation: "build_passes"

  - name: "Update deprecated APIs"
    agent: coder_agent
    instruction: "Replace antMatchers with requestMatchers, update property names"
    loop: true
    exit_condition: "no_deprecation_warnings AND build_passes"

  - name: "Run full test suite"
    agent: test_agent
    instruction: "Run all tests, fix any failures caused by the upgrade"
    loop: true
    exit_condition: "all_tests_pass"
```

### 21. `skills/story_implementation.yaml`

```yaml
name: story_implementation
description: "Implement a Jira story (feature or bug fix)"
applicable_when:
  story_type: [feature, bug]

steps:
  - name: "Analyze requirements"
    agent: context_agent
    instruction: "Extract all acceptance criteria and identify edge cases"

  - name: "Identify affected code"
    agent: repo_agent
    instruction: "Find all files and modules that need modification"

  - name: "Write tests for each AC"
    agent: test_agent
    instruction: "Write one or more tests per acceptance criterion. Tests must fail initially."
    validation: "tests_exist AND tests_fail"

  - name: "Implement changes"
    agent: coder_agent
    instruction: "Write code to satisfy each acceptance criterion. Run build and tests after each change."
    loop: true
    exit_condition: "all_tests_pass AND build_passes"

  - name: "Handle edge cases"
    agent: coder_agent
    instruction: "Add error handling, input validation, and edge case coverage identified in step 1"
    validation: "build_passes AND all_tests_pass"
```

### 22. `skills/write_tests.yaml`

```yaml
name: write_tests
description: "Write developer tests for existing code based on a Jira story"
applicable_when:
  story_type: test

steps:
  - name: "Identify test targets"
    agent: repo_agent
    instruction: "Identify all classes/methods that need test coverage based on the story"

  - name: "Analyze existing tests"
    agent: repo_agent
    instruction: "Find existing test files, understand test patterns, frameworks, and utilities used"

  - name: "Generate test scenarios"
    agent: test_agent
    instruction: |
      For each target class/method, generate test scenarios covering:
      - Happy path for each public method
      - Error/exception cases
      - Boundary conditions
      - Null/empty input handling
      Write scenarios as Gherkin-style Given/When/Then

  - name: "Write test code"
    agent: coder_agent
    instruction: "Convert Gherkin scenarios into actual test code following existing project patterns"
    loop: true
    exit_condition: "all_new_tests_pass AND build_passes"

  - name: "Verify coverage"
    agent: reviewer_agent
    instruction: "Run tests with coverage report. Verify all ACs are covered."
```

### 23. `perception/repo_map.py` — REPOSITORY MAP BUILDER

```python
class RepoMap:
    """
    Builds a compressed structural map of a repository.

    Pipeline:
    1. Walk directory tree (respecting ignore patterns)
    2. Parse each file into AST (using tree-sitter for multi-language)
    3. Extract: classes, methods, functions, imports, calls
    4. Build directed dependency graph (file A imports file B → edge A→B)
    5. Run PageRank to rank files by importance
    6. Generate skeleton view of top-N files (signatures only, no bodies)

    Output: A token-efficient representation of the entire codebase
    that fits within LLM context limits while preserving structural understanding.
    """

    def build(self, project_root: str, ignore_patterns: list[str]) -> RepoMapResult:
        """Full pipeline: scan → parse → graph → rank → skeleton"""

    def get_relevant_files(self, query: str, top_n: int = 20) -> list[str]:
        """Given a task description, return the most relevant files"""

    def get_skeleton(self, filepath: str) -> str:
        """Return signatures-only view of a file"""

    def get_dependency_chain(self, filepath: str) -> list[str]:
        """Return all files that this file depends on (transitive)"""
```

### 24. `core/logger.py`

Structured JSON logging with:
- Correlation ID per pipeline run
- Agent name tagging
- LLM call logging (prompt length, response length, latency, tokens)
- Tool execution logging (tool name, duration, success/failure)
- Pipeline stage transitions
- Error tracking with full stack traces
- Console output (human-readable) + file output (JSON for parsing)

### 25. `core/exceptions.py`

```python
class AgentFrameworkError(Exception): ...
class LLMCallError(AgentFrameworkError): ...        # Torri proxy errors
class LLMRateLimitError(LLMCallError): ...          # 429 specifically
class LLMTimeoutError(LLMCallError): ...            # Timeout
class ToolExecutionError(AgentFrameworkError): ...   # Tool failures
class BuildFailedError(AgentFrameworkError): ...     # Build won't pass after retries
class TestFailedError(AgentFrameworkError): ...      # Tests won't pass after retries
class MaxIterationsError(AgentFrameworkError): ...   # Agent hit loop limit
class SkillNotFoundError(AgentFrameworkError): ...   # Unknown task type
class EscalationRequired(AgentFrameworkError): ...   # Agent needs human help
```

---

## CRITICAL DESIGN PRINCIPLES

1. **Single LLM Gateway**: Every LLM call in the entire application goes through `core/llm_client.py` → Torri proxy. No exceptions. No agent makes direct HTTP calls.

2. **Tools are Deterministic**: Tools never call the LLM. They execute filesystem operations, API calls, and subprocess commands. They always return the same output for the same input.

3. **Agents are Stateless**: Agents don't store state between runs. All shared state flows through `PipelineState`. An agent reads state, does work, updates state, returns.

4. **TDFlow is Non-Negotiable**: The coder_agent CANNOT skip test verification. The orchestrator enforces: tests written → tests fail → code written → tests pass → review. This sequence cannot be bypassed.

5. **Fail Fast, Escalate Clearly**: If an agent is stuck (3 failed attempts on same error), it must stop and report. Never loop forever. The system should tell the human exactly what it couldn't solve and why.

6. **Skills are Data, Not Code**: Skills are YAML files that any developer can write. Adding a new capability (e.g., React upgrade) means writing a new YAML file, not modifying Python code.

7. **Observability Built In**: Every LLM call, every tool execution, every state transition is logged with correlation IDs. A developer should be able to replay exactly what the agent did and why.

8. **Security by Default**: All file operations are sandboxed to the working directory. No force pushes. No deletions outside workspace. All subprocess calls have timeouts. No secrets in logs.

---

## IMPLEMENTATION INSTRUCTIONS

Generate ALL files listed in the project structure above with COMPLETE, PRODUCTION-READY code. Not stubs. Not placeholders. Full implementations.

For each file:
- Include comprehensive docstrings
- Include type hints on all functions
- Include input validation
- Include error handling with specific exceptions
- Include logging at appropriate levels
- Follow PEP 8 and Python best practices
- Use Python 3.11+ features where appropriate (dataclasses, type unions, match statements)

For `requirements.txt`, include:
- requests (HTTP client for Torri proxy and Jira)
- pyyaml (config and skill parsing)
- tree-sitter + language grammars (AST parsing)
- networkx (dependency graph and PageRank)
- gitpython (git operations)
- python-dotenv (env variable loading)
- rich (CLI output formatting)
- tenacity (retry logic)

Generate the code file by file, in dependency order (dependencies first). Start with `core/` then `tools/` then `perception/` then `agents/` then `skills/` then `main.py`.

---

## TESTING REQUIREMENTS

Generate test files that cover:
- `test_llm_client.py`: Mock Torri proxy responses, test retry logic, test timeout handling
- `test_tools.py`: Test each tool's core functionality with mocked external services
- `test_agents.py`: Test the base agent loop with mocked LLM responses and tools
- `test_orchestrator.py`: Test the full pipeline with all agents mocked
- Use pytest. Include fixtures. Include both success and failure scenarios.

---

## WHAT SUCCESS LOOKS LIKE

When complete, a developer should be able to:

```bash
# Install
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with Torri URL, Jira URL, Git credentials

# Run a Spring Boot upgrade
python main.py --jira PROJ-1234 --repo https://git.company.com/team/service.git --branch main --task spring_boot_upgrade

# Run a story implementation
python main.py --jira PROJ-5678 --repo https://git.company.com/team/service.git --branch main --task story_implementation

# Write tests for a story
python main.py --jira PROJ-9999 --repo https://git.company.com/team/service.git --branch main --task write_tests
```

And the system will autonomously:
1. Read the Jira story
2. Clone the repo
3. Understand the codebase
4. Plan the work
5. Write tests
6. Implement changes
7. Verify everything passes
8. Create a PR
9. Log every step for auditability

Generate the complete application now.
