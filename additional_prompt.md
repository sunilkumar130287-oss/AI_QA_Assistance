# AgentForge v2: Dynamic Skill Resolution & Skill-Aware Review — Execution Prompt

> **Instructions:** Copy this entire prompt and paste it into Claude Opus 4.6 along with your full AgentForge codebase (all files from the v1 generation + Phase 1-7 remediation). Claude will refactor the skill system, planner agent, condition evaluator, reviewer agent, and all skill YAML files to support project-aware dynamic step resolution.

---

## PROMPT START

You are a senior Python architect evolving the AgentForge autonomous coding agent framework from static skill execution to **dynamic, project-aware skill resolution**. The current codebase has a working pipeline with 6 agents, tools, and YAML-based skills. You must refactor the architecture so that:

1. Skills define **conditional steps** — each step has a condition evaluated against the actual codebase
2. The planner agent **dynamically resolves** which steps apply to a specific project
3. The reviewer agent performs **skill-specific reviews** instead of generic code review
4. Skills support **inheritance** so Spring Boot upgrade extends Java upgrade
5. The entire system handles the spectrum from "2-step simple project" to "15-step complex monolith" using the same skill file

**Do not break existing functionality.** Every change must be backward-compatible — existing skills without conditions should still work (all steps execute, which is the current behavior).

---

## CRITICAL DESIGN PRINCIPLES

1. **Conditions are deterministic, not LLM-evaluated.** Step conditions like `imports_exist('javax.xml.bind')` are resolved by querying the repo context data structure — not by asking the LLM. This eliminates hallucination from the planning phase.
2. **Skills are data, not code.** All skill logic lives in YAML. The ConditionEvaluator interprets condition expressions against repo context. No Python code in skill files.
3. **The planner explains its decisions.** When the planner skips a step, it logs WHY (the condition and the repo evidence). This creates an auditable plan.
4. **The reviewer is told exactly what to check.** The reviewer's system prompt is dynamically assembled from the skill's review_criteria section — not hardcoded.
5. **Backward compatibility.** Steps without a `condition` field always execute. Skills without `review_criteria` get a generic review. Skills without `extends` are standalone.

---

## NEW AND MODIFIED FILES

### New Files to Create

```
src/
├── core/
│   └── condition_evaluator.py      # NEW — Evaluates step conditions against repo context
│
├── skills/
│   ├── base_skill_schema.yaml      # NEW — Defines the v2 skill YAML schema
│   ├── java_upgrade.yaml           # REWRITE — Full conditional skill
│   ├── spring_boot_upgrade.yaml    # REWRITE — Extends java_upgrade
│   ├── angular_upgrade.yaml        # REWRITE — Full conditional skill
│   ├── story_implementation.yaml   # REWRITE — Full conditional skill
│   └── test_generation.yaml        # REWRITE — Full conditional skill
│
└── tests/
    ├── test_condition_evaluator.py  # NEW — Thorough tests for condition evaluation
    └── test_dynamic_planning.py    # NEW — Tests for dynamic step resolution
```

### Existing Files to Modify

```
src/core/skill_loader.py            # MODIFY — Support v2 schema, inheritance, condition fields
src/core/orchestrator.py            # MODIFY — Pass repo context to planner, wire condition evaluator
src/agents/repo_agent.py            # MODIFY — Output enriched repo context for condition evaluation
src/agents/planner_agent.py         # MODIFY — Dynamic step resolution with condition evaluation
src/agents/reviewer_agent.py        # MODIFY — Skill-aware review with dynamic criteria
src/agents/coder_agent.py           # MODIFY — Receive filtered plan with only active steps
src/core/state_manager.py           # MODIFY — Add plan_resolution section for audit trail
```

---

## MODULE 1: `core/condition_evaluator.py` — NEW FILE

This is the heart of the dynamic system. It evaluates condition expressions from skill YAML against the actual repo context that the repo agent produced.

```python
"""
Condition Evaluator for AgentForge Dynamic Skill Resolution.

Evaluates condition expressions from skill YAML steps against the repo context
produced by RepoAgent. All evaluation is deterministic — no LLM calls.

Condition expressions are simple strings that support:
- Function calls: file_exists('pom.xml'), imports_exist('javax.xml.bind')
- Comparisons: build_system == 'maven', module_count > 5
- Boolean operators: and, or, not
- Arithmetic on versions: java_version_jump >= 6

Supported condition functions:
    file_exists(path)                 — True if file exists in repo
    file_contains(path, pattern)      — True if file contains regex pattern
    dependency_exists(name)           — True if dependency declared in build config
    dependency_version(name)          — Returns version string of a dependency
    dependency_version_lt(name, ver)  — True if dependency version < ver
    dependency_version_gte(name, ver) — True if dependency version >= ver
    imports_exist(pattern)            — True if any source file imports matching pattern
    import_count(pattern)             — Returns number of files with matching imports
    class_exists(name)                — True if class with exact name exists in AST
    method_calls_exist(pattern)       — True if any method call matches pattern
    annotation_exists(name)           — True if annotation is used anywhere
    property_exists(key)              — True if property/config key exists
    count_files(pattern)              — Count files matching glob pattern
    has_test_framework(name)          — True if test framework is detected
    spring_boot_version_jump_crosses(ver) — True if upgrade crosses a major version boundary

Built-in variables (resolved from repo context):
    build_system         — 'maven' | 'gradle' | 'npm' | 'ng' | 'unknown'
    java_version         — Current Java version as int (e.g., 11)
    target_java_version  — Target Java version from Jira context as int
    java_version_jump    — target_java_version - java_version
    module_count         — Number of build modules
    framework            — Detected framework: 'spring-boot' | 'jakarta-ee' | 'angular' | etc.
    language             — Primary language: 'java' | 'typescript' | 'python'
    test_framework       — Detected test framework: 'junit4' | 'junit5' | 'jest' | 'pytest'
    source_file_count    — Total number of source files
    has_tests            — True if test files exist

Requirements:
- Parse condition strings safely — NO eval() or exec(). Use a simple recursive descent
  parser or ast.literal_eval for comparisons, and regex-based function call extraction.
- Every condition evaluation is logged: condition string, resolved value, and the
  repo evidence used to determine the result.
- If a condition references a function or variable that doesn't exist, log a warning
  and return False (safe default — step is skipped, not erroneously run).
- Thread-safe and stateless — the evaluator receives repo_context as a parameter,
  does not mutate it.
- Return a ConditionResult dataclass, not just a bool:

    @dataclass(frozen=True)
    class ConditionResult:
        condition: str          # Original condition string
        result: bool            # Evaluated result
        evidence: str           # Human-readable explanation of why
        variables_used: dict    # Variables/functions and their resolved values

Interface:
    class ConditionEvaluator:
        def __init__(self, repo_context: dict, jira_context: dict, logger)
        def evaluate(self, condition: str) -> ConditionResult
        def evaluate_all(self, conditions: list[str]) -> list[ConditionResult]
        def get_available_variables(self) -> dict[str, Any]
        def get_available_functions(self) -> list[str]

Implementation approach:
- Register each condition function as a method: _fn_file_exists, _fn_imports_exist, etc.
- Use a dispatch dict: {"file_exists": self._fn_file_exists, "imports_exist": self._fn_imports_exist, ...}
- Parse the condition string to extract function calls with regex:
    pattern: r"(\w+)\(([^)]*)\)"  matches  function_name(args)
- Parse comparisons with regex:
    pattern: r"(\w+)\s*(==|!=|>=|<=|>|<)\s*(.+)"  matches  variable op value
- Parse boolean combinators: split on ' and ', ' or ', handle 'not ' prefix
- For compound conditions like "build_system == 'maven' and dependency_exists('lombok')",
  split on ' and ' / ' or ', evaluate each part, combine with Python and/or.

IMPORTANT: The condition evaluator queries the repo_context dict that RepoAgent produces.
Here is the expected structure of repo_context (define this as a TypedDict or document it):

    repo_context = {
        "build_system": "maven",
        "language": "java",
        "framework": "spring-boot",
        "java_version": 11,
        "module_count": 3,
        "source_file_count": 247,
        "has_tests": True,
        "test_framework": "junit5",
        "dependencies": {
            "spring-boot-starter": {"version": "2.7.14", "scope": "compile"},
            "lombok": {"version": "1.18.28", "scope": "compile"},
            "junit-jupiter": {"version": "5.9.3", "scope": "test"},
        },
        "imports": {
            "javax.xml.bind": ["src/main/java/com/app/model/User.java", ...],
            "javax.servlet": ["src/main/java/com/app/filter/AuthFilter.java", ...],
            "sun.misc.Unsafe": [],
        },
        "classes": {
            "UserService": {"file": "src/main/.../UserService.java", "line": 15},
            "SecurityManager": None,
        },
        "annotations": ["Entity", "RestController", "Service", "Autowired", ...],
        "properties": {
            "server.port": "8080",
            "spring.datasource.url": "jdbc:postgresql://...",
        },
        "files": ["pom.xml", "src/main/java/...", ...],
        "method_calls": {
            "Pattern.compile": ["src/main/.../Validator.java:42", ...],
        },
    }
"""
```

Generate the **complete, working implementation** of `ConditionEvaluator` with all functions listed above implemented. Every function must query the `repo_context` dict — no stubs.

---

## MODULE 2: `core/skill_loader.py` — MODIFY

The skill loader must be updated to support the v2 skill schema while remaining backward-compatible with v1 skills.

**Changes required:**

### 2.1 — Support the v2 YAML schema

The v2 schema introduces these new fields:

```yaml
# Top-level new fields
extends: parent_skill_name           # Optional — inherit from another skill
project_analysis:                    # Optional — detection rules for repo scanning
  detect:
    field_name:
      - check: "condition_expression"
        value: result_value

# Phase-level new fields
phases:                              # Replaces flat 'steps' list
  - name: Phase Name
    always_run: true/false           # Optional, default false
    steps:
      - name: Step Name
        agent: agent_name
        condition: "condition_expr"  # Optional — if absent, step always runs
        instruction: "..."
        tools_needed: [tool1, tool2]
        verify: "condition_expr"     # Optional — post-step verification
        outputs: [var1, var2]        # Optional — state keys this step produces
        loop: true/false
        exit_condition: "..."
        max_iterations: 10
        context: |
          Additional knowledge...

# Review criteria
review_criteria:
  extends: parent_skill_name         # Optional — inherit parent review checks
  mandatory:
    - "Check description"
  conditional:
    - condition: "condition_expr"
      check: "Check description"
  forbidden:
    - "Anti-pattern description"
```

### 2.2 — Implement skill inheritance

When a skill has `extends: parent_skill_name`:

1. Load the parent skill first
2. Deep-merge the child into the parent:
   - `phases`: parent phases come first, child `additional_phases` are appended
   - `review_criteria`: parent criteria are inherited, child criteria are added
     - If child has `extends` in review_criteria, merge parent mandatory/conditional/forbidden
   - `project_analysis`: child overrides parent if present
3. Inheritance is single-level only (no grandparent chains) for simplicity in v2

```python
def _resolve_inheritance(self, skill: dict) -> dict:
    """Resolve skill inheritance by merging parent skill into child.

    Args:
        skill: Child skill dict with optional 'extends' field.

    Returns:
        Fully resolved skill with parent fields merged in.

    Raises:
        SkillError: If parent skill not found or circular inheritance detected.
    """
```

### 2.3 — Backward compatibility

If a skill uses the v1 format (flat `steps` list, no `phases`, no `conditions`):
- Wrap the steps in a single phase named "Execution" with `always_run: true`
- No conditions to evaluate — all steps run
- No review_criteria — reviewer uses generic review
- Log a deprecation warning suggesting migration to v2 format

### 2.4 — Validation

Add schema validation for v2 skills:
- Every step must have `name`, `agent`, and `instruction`
- `condition` must be a string (not a list or dict)
- `verify` must be a string
- `agent` must be one of: context_agent, repo_agent, planner_agent, coder_agent, test_agent, reviewer_agent
- `tools_needed` must be a list of known tool names
- `extends` must reference an existing skill file

Generate the **complete updated `skill_loader.py`** with all changes above.

---

## MODULE 3: `agents/repo_agent.py` — MODIFY

The repo agent must produce a **much richer** repo context that the ConditionEvaluator can query. The current repo agent likely produces a summary — it needs to produce structured, queryable data.

**Changes required:**

### 3.1 — Enrich the repo context output

After the repo agent finishes its analysis, it must populate the state manager with a `repo_context` dict matching this structure:

```python
repo_context = {
    # Build system detection
    "build_system": str,          # "maven" | "gradle" | "npm" | "ng" | "unknown"
    "build_files": list[str],     # Paths to all build config files

    # Language and framework
    "language": str,              # Primary language
    "framework": str | None,      # Detected framework or None
    "framework_version": str | None,

    # Java-specific (populated only if language == "java")
    "java_version": int | None,
    "module_count": int,
    "modules": list[dict],        # [{name, path, dependencies}]

    # Angular/TS-specific (populated only if framework == "angular")
    "angular_version": int | None,
    "node_version": str | None,

    # Source analysis
    "source_file_count": int,
    "has_tests": bool,
    "test_framework": str | None,  # "junit4" | "junit5" | "testng" | "jest" | "karma" | "pytest"
    "test_file_count": int,

    # Dependencies (parsed from build files)
    "dependencies": dict[str, dict],  # name -> {version, scope, group_id}

    # Import analysis (from AST parsing)
    "imports": dict[str, list[str]],  # import_pattern -> [file_paths]

    # Class/symbol analysis (from AST)
    "classes": dict[str, dict | None],    # class_name -> {file, line} or None if not found
    "annotations": list[str],              # All annotations used in codebase

    # Property/config analysis
    "properties": dict[str, str],          # key -> value from config files

    # File inventory
    "files": list[str],                    # All source files
    "file_tree": dict,                     # Nested dict representing directory structure

    # Method call analysis (for migration detection)
    "method_calls": dict[str, list[str]],  # pattern -> [file:line references]
}
```

### 3.2 — Add targeted analysis methods

The repo agent needs new tool calls to populate the enriched context. Add these analysis steps to its workflow:

```python
def _analyze_dependencies(self) -> dict:
    """Parse build files to extract all dependencies with versions."""
    # For Maven: parse pom.xml using xml/regex
    # For Gradle: parse build.gradle
    # For npm: parse package.json
    # Return: {name: {version, scope, group_id}}

def _analyze_imports(self, patterns: list[str] | None = None) -> dict:
    """Scan source files for import statements.

    If patterns provided, only track imports matching those patterns.
    Otherwise, track all unique import prefixes.
    """
    # Use AST parser for Java/Python
    # Use regex for TypeScript/JavaScript
    # Return: {import_pattern: [file_paths]}

def _analyze_properties(self) -> dict:
    """Parse configuration files for property key-value pairs."""
    # application.properties, application.yml, .env, angular.json
    # Return: {key: value}

def _detect_test_framework(self) -> str | None:
    """Detect which test framework is in use."""
    # Check dependencies for junit, testng, jest, karma, pytest
    # Check for test file patterns

def _analyze_annotations(self) -> list[str]:
    """Extract all Java annotations used in the codebase."""
    # Parse AST for decorator/annotation nodes
    # Return unique list

def _analyze_method_calls(self, patterns: list[str] | None = None) -> dict:
    """Find method call sites matching patterns."""
    # Use AST to find Call nodes matching patterns
    # Return: {pattern: [file:line]}
```

### 3.3 — Integrate project_analysis from skill

If the loaded skill has a `project_analysis.detect` section, the repo agent should use it as **guidance** for what to look for. This makes the analysis targeted instead of exhaustive:

```python
def _apply_skill_detection_hints(self, skill: dict) -> None:
    """Use skill's project_analysis section to guide repo analysis.

    Instead of analyzing everything, focus on what the skill cares about.
    This makes analysis faster for large repos.
    """
    detection = skill.get("project_analysis", {}).get("detect", {})
    # For each detection rule, run the corresponding check
    # This pre-populates repo_context with skill-relevant data
```

Generate the **complete updated `repo_agent.py`** with all enrichments.

---

## MODULE 4: `agents/planner_agent.py` — MODIFY

The planner agent is the most significant change. It transforms from "read skill steps and output them as a plan" to "evaluate each step's condition against the repo, build a dynamic execution plan, and explain every inclusion/exclusion decision."

**Changes required:**

### 4.1 — Add ConditionEvaluator integration

```python
class PlannerAgent(BaseAgent):
    def __init__(self, llm_client, tool_registry, condition_evaluator: ConditionEvaluator):
        super().__init__(...)
        self._evaluator = condition_evaluator
```

### 4.2 — Dynamic step resolution

The planner's main workflow becomes:

```python
def _resolve_plan(self, skill: dict, repo_context: dict, jira_context: dict) -> ResolvedPlan:
    """Resolve a skill into a concrete execution plan for this specific project.

    For each phase in the skill:
      1. If phase has always_run=True, include all steps
      2. For each step with a condition, evaluate it against repo_context
      3. Steps with True conditions are ACTIVE
      4. Steps with False conditions are SKIPPED (with reason logged)
      5. Steps without conditions are ACTIVE (backward compat)

    After resolution, the LLM is used ONLY to:
      - Adapt generic instructions to the specific project context
      - Order steps that have dependencies on each other
      - Estimate iteration budgets based on project complexity

    Returns:
        ResolvedPlan with active steps, skipped steps with reasons, and audit trail.
    """
```

### 4.3 — ResolvedPlan data structure

```python
@dataclass(frozen=True)
class ResolvedStep:
    name: str
    agent: str
    instruction: str              # May be adapted by LLM for this specific project
    tools_needed: list[str]
    verify: str | None
    loop: bool
    max_iterations: int
    context: str
    condition: str | None         # Original condition string
    condition_result: ConditionResult | None  # How the condition was evaluated
    status: str                   # "active" | "skipped"
    skip_reason: str | None       # Why it was skipped, if skipped

@dataclass(frozen=True)
class ResolvedPhase:
    name: str
    always_run: bool
    steps: list[ResolvedStep]     # Both active and skipped steps for audit
    active_step_count: int
    skipped_step_count: int

@dataclass(frozen=True)
class ResolvedPlan:
    skill_name: str
    project_summary: str          # One-line summary of what was detected
    phases: list[ResolvedPhase]
    total_active_steps: int
    total_skipped_steps: int
    estimated_iterations: int     # Budget based on complexity
    resolution_audit: list[dict]  # Full audit trail of every condition evaluation
```

### 4.4 — LLM usage in the planner

The LLM is used for exactly two things in the planner (everything else is deterministic):

1. **Instruction adaptation**: Take the generic skill instruction "Replace all javax.persistence imports with jakarta.persistence" and adapt it to the specific project: "Replace javax.persistence imports in these 7 files: User.java, Order.java, Product.java, ..."

2. **Complexity estimation**: Given the number of active steps, the module count, and the source file count, estimate how many coder iterations will be needed. This sets the `max_iterations` budget for the coder agent.

The LLM is **NOT** used to decide which steps to include — that's the ConditionEvaluator's job.

### 4.5 — Plan output to state manager

The planner saves the full `ResolvedPlan` to the state manager, including skipped steps and their reasons. This becomes part of the execution report.

Generate the **complete updated `planner_agent.py`** with all changes.

---

## MODULE 5: `agents/reviewer_agent.py` — MODIFY

The reviewer agent must become **skill-aware**. Its review criteria come from the skill YAML, not from a hardcoded system prompt.

**Changes required:**

### 5.1 — Dynamic review prompt assembly

```python
class ReviewerAgent(BaseAgent):

    def _build_review_prompt(
        self,
        skill: dict,
        resolved_plan: ResolvedPlan,
        repo_context: dict,
        jira_context: dict,
        condition_evaluator: ConditionEvaluator
    ) -> str:
        """Assemble a skill-specific review prompt.

        The prompt includes:
        1. What the task was (from Jira context)
        2. What steps were executed (from resolved plan)
        3. What steps were skipped and why (from resolved plan)
        4. Mandatory review checks (from skill review_criteria)
        5. Conditional review checks (evaluated against repo context)
        6. Forbidden patterns to scan for (from skill review_criteria)
        7. Acceptance criteria verification (from Jira context)

        Returns:
            Complete system prompt for the reviewer LLM call.
        """
        criteria = skill.get("review_criteria", {})

        sections = []

        # Section 1: Task Summary
        sections.append(
            f"## Task Summary\n"
            f"Jira: {jira_context.get('jira_id')}\n"
            f"Task Type: {skill.get('name')}\n"
            f"Steps Executed: {resolved_plan.total_active_steps}\n"
            f"Steps Skipped: {resolved_plan.total_skipped_steps}\n"
        )

        # Section 2: Mandatory Checks
        mandatory = criteria.get("mandatory", [])
        if mandatory:
            sections.append("## Mandatory Checks — ALL must pass\n")
            for i, check in enumerate(mandatory, 1):
                sections.append(f"{i}. {check}")

        # Section 3: Conditional Checks — only include if condition is true for THIS project
        conditional = criteria.get("conditional", [])
        active_conditional = []
        for item in conditional:
            condition_str = item.get("condition", "true")
            result = condition_evaluator.evaluate(condition_str)
            if result.result:
                active_conditional.append(item["check"])

        if active_conditional:
            sections.append("\n## Project-Specific Checks\n")
            for i, check in enumerate(active_conditional, 1):
                sections.append(f"{i}. {check}")

        # Section 4: Forbidden Patterns
        forbidden = criteria.get("forbidden", [])
        if forbidden:
            sections.append("\n## Forbidden Patterns — FAIL if any found\n")
            for i, check in enumerate(forbidden, 1):
                sections.append(f"{i}. {check}")

        # Section 5: Acceptance Criteria from Jira
        acs = jira_context.get("acceptance_criteria", [])
        if acs:
            sections.append("\n## Acceptance Criteria Verification\n")
            for i, ac in enumerate(acs, 1):
                sections.append(f"{i}. {ac}")

        # Section 6: Executed Steps Summary (so reviewer knows what was done)
        sections.append("\n## Steps That Were Executed\n")
        for phase in resolved_plan.phases:
            for step in phase.steps:
                if step.status == "active":
                    sections.append(f"- {step.name}: {step.instruction[:100]}...")

        # Section 7: Skipped Steps (so reviewer knows what was NOT done and why)
        skipped = [s for p in resolved_plan.phases for s in p.steps if s.status == "skipped"]
        if skipped:
            sections.append("\n## Steps That Were Skipped (verify these are correctly skipped)\n")
            for step in skipped:
                sections.append(f"- {step.name}: SKIPPED because {step.skip_reason}")

        # Section 8: Review output format
        sections.append("""
## Your Review Output Format

For each check, respond with this exact JSON structure:
```json
{
    "checks": [
        {
            "category": "mandatory|conditional|forbidden|acceptance_criteria",
            "description": "What was checked",
            "result": "PASS|FAIL",
            "evidence": "Specific file/line/diff evidence",
            "severity": "critical|high|medium|low"
        }
    ],
    "overall_verdict": "APPROVED|REJECTED|NEEDS_CHANGES",
    "summary": "One paragraph summary",
    "blocking_issues": ["List of issues that must be fixed before merge"],
    "suggestions": ["Non-blocking improvement suggestions"],
    "skipped_steps_review": "Confirm whether skipped steps were correctly skipped"
}
```
""")

        return "\n".join(sections)
```

### 5.2 — Fallback for skills without review_criteria

If the skill has no `review_criteria` section (v1 skills or simple skills), the reviewer falls back to a **generic but still structured** review:

```python
_GENERIC_REVIEW_CRITERIA = {
    "mandatory": [
        "All modified files compile/parse without errors",
        "No debug prints, console.logs, or commented-out code in changes",
        "All existing tests still pass",
        "New code follows existing code style and conventions",
        "Git diff is clean — no unrelated changes",
    ],
    "forbidden": [
        "Hardcoded credentials, API keys, or secrets",
        "TODO or FIXME comments in new code without linked tickets",
        "Disabled or skipped tests",
    ]
}
```

### 5.3 — Review result parsing and retry logic

When the reviewer outputs its JSON result:
1. Parse the JSON using `_extract_json()` from BaseAgent
2. If `overall_verdict` is `REJECTED` or `NEEDS_CHANGES`:
   - Extract `blocking_issues`
   - Send them back to the coder agent as a new task
   - Re-run the reviewer after coder makes fixes
   - Maximum 2 review-fix cycles (configurable)
3. If `overall_verdict` is `APPROVED`:
   - Proceed to git commit and PR
4. Save the full review result to state manager

### 5.4 — Verify skipped steps are correct

The reviewer has a unique responsibility: it checks whether the planner **correctly skipped** steps. If the reviewer sees evidence that a skipped step should have been active (e.g., the planner skipped "Replace javax.xml.bind" but the reviewer sees javax.xml.bind in the diff), it flags this as a critical issue.

Generate the **complete updated `reviewer_agent.py`** with all changes.

---

## MODULE 6: `core/orchestrator.py` — MODIFY

The orchestrator must wire the new components together.

**Changes required:**

### 6.1 — Create ConditionEvaluator after repo analysis

```python
def _execute_pipeline(self, skill: dict, user_input: dict) -> PipelineResult:
    # Stage 1: Context (unchanged)
    jira_context = self._run_agent("context", ...)

    # Stage 2: Perception — repo agent now produces enriched context
    repo_context = self._run_agent("repo", ...)

    # NEW: Create condition evaluator with live repo data
    condition_evaluator = ConditionEvaluator(
        repo_context=self._state.get("repo_agent", "repo_context"),
        jira_context=self._state.get("context_agent", "jira_context"),
        logger=self._log
    )

    # Inject target version from Jira into evaluator context
    # (e.g., target_java_version parsed from Jira story)
    condition_evaluator.set_variable(
        "target_java_version",
        jira_context.get("target_version")
    )

    # Stage 3: Planning — planner now uses condition evaluator
    self._planner_agent.set_condition_evaluator(condition_evaluator)
    resolved_plan = self._run_agent("planner", skill=skill)

    # Log plan resolution summary
    self._log.info(
        "Plan resolved",
        extra={
            "active_steps": resolved_plan.total_active_steps,
            "skipped_steps": resolved_plan.total_skipped_steps,
            "phases": len(resolved_plan.phases),
        }
    )

    # Stage 4 & 5: Execute only ACTIVE steps
    for phase in resolved_plan.phases:
        active_steps = [s for s in phase.steps if s.status == "active"]
        if not active_steps:
            self._log.info(f"Skipping phase '{phase.name}' — no active steps")
            continue

        for step in active_steps:
            agent = self._get_agent(step.agent)
            step_result = agent.run(task_context={
                "instruction": step.instruction,
                "tools_needed": step.tools_needed,
                "context": step.context,
                "verify": step.verify,
                "loop": step.loop,
                "max_iterations": step.max_iterations,
            })

            # If step has a verify condition, check it
            if step.verify:
                verify_result = condition_evaluator.evaluate(step.verify)
                if not verify_result.result:
                    self._log.warning(
                        f"Step verification failed: {step.name}",
                        extra={"verify": step.verify, "evidence": verify_result.evidence}
                    )
                    # Optionally retry the step or fail the pipeline

    # Stage 6: Review — reviewer gets skill-specific criteria
    self._reviewer_agent.set_skill(skill)
    self._reviewer_agent.set_resolved_plan(resolved_plan)
    self._reviewer_agent.set_condition_evaluator(condition_evaluator)
    review_result = self._run_agent("reviewer", ...)

    # Stage 7: Deliver (unchanged, but only if review passes)
    ...
```

### 6.2 — Add plan resolution to execution report

The final `PipelineResult` should include:
- The full `ResolvedPlan` with active and skipped steps
- The condition evaluation audit trail
- The skill-specific review results
- Which review criteria passed and which failed

Generate the **complete updated `orchestrator.py`**.

---

## MODULE 7: `core/state_manager.py` — MODIFY

Add a new `plan_resolution` section that captures the full audit trail:

```python
# New state sections
"plan_resolution": {
    "skill_name": str,
    "skill_version": str,
    "parent_skill": str | None,
    "total_steps_in_skill": int,
    "active_steps": int,
    "skipped_steps": int,
    "condition_evaluations": [
        {
            "step_name": str,
            "condition": str,
            "result": bool,
            "evidence": str,
            "variables_used": dict,
            "timestamp": str,
        }
    ],
    "plan_adaptation_notes": str,  # LLM's notes on how it adapted instructions
}

"review_resolution": {
    "criteria_source": "skill-specific" | "generic",
    "mandatory_checks_count": int,
    "conditional_checks_count": int,
    "conditional_checks_activated": int,
    "forbidden_checks_count": int,
    "results": [...],  # Full review check results
    "verdict": str,
    "review_cycles": int,  # How many review-fix cycles occurred
}
```

Generate the **complete updated `state_manager.py`**.

---

## MODULE 8: SKILL YAML FILES — REWRITE ALL

Rewrite every skill file to use the v2 schema with conditions, phases, and review criteria. Each skill must be **deeply detailed** with real-world migration knowledge.

### 8.1 — `skills/java_upgrade.yaml`

Requirements:
- Phases: Pre-flight Analysis, Build Configuration, API Migration, Dependency Compatibility, Language Features, Verification
- At least 15 conditional steps covering: compiler settings, javax.xml.bind removal (Java 11+), Nashorn removal (Java 15+), SecurityManager deprecation (Java 17+), sun.misc.Unsafe (all versions), Lombok compatibility (Java 16+), JUnit 4→5, reflection access (Java 16+ strong encapsulation), text blocks opportunity (Java 15+), records opportunity (Java 16+), sealed classes opportunity (Java 17+), pattern matching opportunity (Java 21+), virtual threads opportunity (Java 21+)
- Review criteria: mandatory checks for version correctness, no banned imports, build success, test pass. Conditional checks for multi-module projects. Forbidden patterns for --add-opens workarounds, @SuppressWarnings('removal')
- Full `project_analysis.detect` section

### 8.2 — `skills/spring_boot_upgrade.yaml`

Requirements:
- `extends: java_upgrade` — inherits all Java upgrade phases
- Additional phases: Spring Namespace Migration (javax→jakarta for SB3), Property Renames, Security Configuration (WebSecurityConfigurerAdapter removal), Actuator Changes, Spring Data Changes
- At least 12 additional conditional steps specific to Spring Boot
- Conditions that detect which Spring Boot version boundary is being crossed (2.x→3.x is the big one)
- Review criteria extending java_upgrade plus Spring-specific checks
- Detection of Spring-specific patterns: @Configuration classes, WebSecurityConfigurerAdapter, spring.config.* properties

### 8.3 — `skills/angular_upgrade.yaml`

Requirements:
- Phases: Pre-flight, Package Updates, Module Migration, Template Syntax, RxJS Migration, Test Migration, Verification
- Conditional steps for: NgModule→standalone (Angular 15+), RxJS operator changes, deprecated decorators, Ivy renderer (Angular 12+), ESBuild migration (Angular 16+), signals (Angular 16+), control flow syntax (Angular 17+), zoneless (Angular 18+)
- Review criteria specific to Angular: no deprecated imports from @angular/core, no legacy module patterns if targeting 15+, updated angular.json
- Conditions based on angular_version and target_angular_version

### 8.4 — `skills/story_implementation.yaml`

Requirements:
- Phases: Analysis, Design, Test Writing (TDFlow), Implementation, Integration, Verification
- Conditional steps for: API endpoint (if story involves REST), database changes (if story mentions schema/model), UI changes (if story mentions frontend), configuration changes
- Review criteria from acceptance criteria (dynamically pulled from Jira)
- This is the default/generic skill — conditions are broader and more heuristic

### 8.5 — `skills/test_generation.yaml`

Requirements:
- Phases: Coverage Analysis, Unit Test Generation, Integration Test Generation, Edge Case Generation, Verification
- Conditional steps for: uncovered classes, uncovered branches, missing null checks, missing boundary tests, missing error path tests
- Conditions based on test_framework detection and existing coverage
- Review criteria: minimum coverage threshold, no trivial assertions, no test interdependencies

Generate **all 5 complete skill YAML files** with full conditional steps and review criteria.

---

## MODULE 9: `agents/coder_agent.py` — MODIFY

The coder agent needs minor changes to work with the resolved plan:

### 9.1 — Accept step-level instructions

The coder now receives individual steps from the orchestrator rather than a monolithic plan. Its `run()` method should accept:

```python
def run(self, task_context: dict) -> AgentResult:
    """Execute a single step from the resolved plan.

    task_context keys:
        instruction: str — What to do (adapted for this project)
        tools_needed: list[str] — Which tools to use
        context: str — Additional knowledge from the skill
        verify: str | None — Post-step verification condition
        loop: bool — Whether to iterate until exit_condition
        max_iterations: int — Iteration budget for this step
    """
```

### 9.2 — Verification integration

After the coder completes a step, if `verify` is provided, the orchestrator evaluates it via ConditionEvaluator. But the coder itself should also have awareness — add the verify condition to the coder's system prompt so it knows what "done" looks like:

```python
if task_context.get("verify"):
    system_prompt += f"\n\nVERIFICATION CRITERIA: Your changes are complete when: {task_context['verify']}"
```

Generate the **complete updated `coder_agent.py`**.

---

## MODULE 10: TEST FILES — NEW

### 10.1 — `tests/test_condition_evaluator.py`

Comprehensive tests for the ConditionEvaluator:

```python
class TestConditionEvaluator:
    """Tests for deterministic condition evaluation against repo context."""

    # Test each condition function
    def test_file_exists_true(self, evaluator_with_java_repo): ...
    def test_file_exists_false(self, evaluator_with_java_repo): ...
    def test_dependency_exists_found(self, evaluator_with_java_repo): ...
    def test_dependency_exists_not_found(self, evaluator_with_java_repo): ...
    def test_dependency_version_lt(self, evaluator_with_java_repo): ...
    def test_imports_exist_with_matches(self, evaluator_with_java_repo): ...
    def test_imports_exist_no_matches(self, evaluator_with_java_repo): ...
    def test_class_exists(self, evaluator_with_java_repo): ...
    def test_annotation_exists(self, evaluator_with_java_repo): ...

    # Test comparisons
    def test_equality_comparison(self, evaluator_with_java_repo): ...
    def test_numeric_comparison(self, evaluator_with_java_repo): ...

    # Test boolean operators
    def test_and_both_true(self, evaluator_with_java_repo): ...
    def test_and_one_false(self, evaluator_with_java_repo): ...
    def test_or_one_true(self, evaluator_with_java_repo): ...
    def test_not_operator(self, evaluator_with_java_repo): ...

    # Test compound conditions
    def test_complex_condition(self, evaluator_with_java_repo):
        """build_system == 'maven' and dependency_exists('lombok') and java_version_jump >= 5"""
        ...

    # Test edge cases
    def test_unknown_function_returns_false(self, evaluator_with_java_repo): ...
    def test_unknown_variable_returns_false(self, evaluator_with_java_repo): ...
    def test_empty_condition_returns_true(self, evaluator_with_java_repo): ...
    def test_malformed_condition_returns_false(self, evaluator_with_java_repo): ...

    # Test evidence trail
    def test_condition_result_includes_evidence(self, evaluator_with_java_repo): ...
    def test_condition_result_includes_variables_used(self, evaluator_with_java_repo): ...

    # Test with different project types
    def test_angular_project_conditions(self, evaluator_with_angular_repo): ...
    def test_minimal_project_skips_most_steps(self, evaluator_with_minimal_repo): ...
```

### 10.2 — `tests/test_dynamic_planning.py`

Tests for the full planning pipeline:

```python
class TestDynamicPlanning:
    """Tests for dynamic step resolution in the planner agent."""

    def test_simple_project_gets_minimal_steps(self, planner, simple_java_repo):
        """A simple microservice with no deprecated APIs should get only build config + verify steps."""
        plan = planner._resolve_plan(java_upgrade_skill, simple_java_repo, jira_context)
        assert plan.total_active_steps <= 3
        assert plan.total_skipped_steps >= 10
        active_names = [s.name for p in plan.phases for s in p.steps if s.status == "active"]
        assert "Update Maven compiler plugin" in active_names
        assert "Full build and test" in active_names

    def test_complex_monolith_gets_all_steps(self, planner, complex_java_repo):
        """A monolith with javax imports, Lombok, old JUnit should get most steps."""
        plan = planner._resolve_plan(java_upgrade_skill, complex_java_repo, jira_context)
        assert plan.total_active_steps >= 10
        active_names = [s.name for p in plan.phases for s in p.steps if s.status == "active"]
        assert "Replace removed javax.xml APIs" in active_names
        assert "Update Lombok version" in active_names

    def test_spring_boot_inherits_java_steps(self, planner, spring_boot_repo):
        """Spring Boot skill should include parent Java upgrade steps plus Spring-specific steps."""
        plan = planner._resolve_plan(spring_boot_skill, spring_boot_repo, jira_context)
        step_names = [s.name for p in plan.phases for s in p.steps]
        # Should have Java steps
        assert any("compiler" in n.lower() for n in step_names)
        # Should also have Spring steps
        assert any("jakarta" in n.lower() or "namespace" in n.lower() for n in step_names)

    def test_skipped_steps_have_reasons(self, planner, simple_java_repo):
        """Every skipped step must have a human-readable reason."""
        plan = planner._resolve_plan(java_upgrade_skill, simple_java_repo, jira_context)
        skipped = [s for p in plan.phases for s in p.steps if s.status == "skipped"]
        for step in skipped:
            assert step.skip_reason is not None
            assert len(step.skip_reason) > 10  # Not just "false"

    def test_always_run_phases_never_skipped(self, planner, simple_java_repo):
        """Phases with always_run=True execute regardless of conditions."""
        plan = planner._resolve_plan(java_upgrade_skill, simple_java_repo, jira_context)
        for phase in plan.phases:
            if phase.always_run:
                active = [s for s in phase.steps if s.status == "active"]
                assert len(active) > 0

    def test_v1_skill_backward_compatibility(self, planner, simple_java_repo):
        """V1 skills without conditions should still work — all steps execute."""
        plan = planner._resolve_plan(v1_legacy_skill, simple_java_repo, jira_context)
        skipped = [s for p in plan.phases for s in p.steps if s.status == "skipped"]
        assert len(skipped) == 0  # No steps skipped in v1 mode

    def test_condition_audit_trail_complete(self, planner, complex_java_repo):
        """Resolution audit must contain every condition evaluation."""
        plan = planner._resolve_plan(java_upgrade_skill, complex_java_repo, jira_context)
        conditional_steps = [
            s for p in plan.phases for s in p.steps if s.condition is not None
        ]
        assert len(plan.resolution_audit) >= len(conditional_steps)


class TestSkillAwareReviewer:
    """Tests for skill-specific review criteria in the reviewer agent."""

    def test_java_upgrade_review_checks_imports(self, reviewer, java_skill, java_context):
        """Java upgrade reviewer must check for banned javax imports."""
        prompt = reviewer._build_review_prompt(java_skill, ...)
        assert "javax.xml.bind" in prompt
        assert "sun." in prompt

    def test_spring_boot_review_inherits_java_checks(self, reviewer, spring_skill, spring_context):
        """Spring Boot reviewer must include both Java and Spring checks."""
        prompt = reviewer._build_review_prompt(spring_skill, ...)
        # Java checks inherited
        assert "javax.xml.bind" in prompt or "sun." in prompt
        # Spring-specific checks added
        assert "javax.persistence" in prompt or "jakarta" in prompt

    def test_conditional_review_criteria_evaluated(self, reviewer, java_skill):
        """Conditional review criteria are only included when condition is true."""
        # With multi-module project
        prompt_multi = reviewer._build_review_prompt(java_skill, multi_module_context, ...)
        assert "All modules compile independently" in prompt_multi

        # With single-module project
        prompt_single = reviewer._build_review_prompt(java_skill, single_module_context, ...)
        assert "All modules compile independently" not in prompt_single

    def test_generic_fallback_for_v1_skills(self, reviewer, v1_skill, context):
        """Skills without review_criteria get generic review checks."""
        prompt = reviewer._build_review_prompt(v1_skill, ...)
        assert "compile" in prompt.lower()
        assert "debug prints" in prompt.lower() or "console.log" in prompt.lower()

    def test_skipped_steps_included_in_review(self, reviewer, skill, plan_with_skips):
        """Reviewer sees skipped steps and verifies they were correctly skipped."""
        prompt = reviewer._build_review_prompt(skill, plan_with_skips, ...)
        assert "SKIPPED" in prompt
        assert "skipped_steps_review" in prompt.lower() or "correctly skipped" in prompt.lower()
```

Generate **complete test files** with all tests implemented, including fixtures.

---

## FINAL REQUIREMENTS

1. **Generate every file listed above — complete implementation, no stubs.**
2. **Maintain backward compatibility.** V1 skills must still work without modification.
3. **All condition evaluation is deterministic.** No LLM calls in the ConditionEvaluator.
4. **The audit trail is complete.** Every condition evaluation, every skip decision, every review check is logged and saved to state.
5. **Type hints on everything.** Use dataclasses with `frozen=True` for all data transfer objects.
6. **Tests must be meaningful.** Each test verifies a specific behavior — no `assert True` placeholders.

After generating all files, output a summary:

```
✅ AgentForge v2 — Dynamic Skill Resolution Complete

New files:
  - core/condition_evaluator.py (N lines)
  - tests/test_condition_evaluator.py (N lines)
  - tests/test_dynamic_planning.py (N lines)

Modified files:
  - core/skill_loader.py — v2 schema, inheritance, backward compat
  - core/orchestrator.py — ConditionEvaluator wiring, step-level execution
  - core/state_manager.py — plan_resolution and review_resolution sections
  - agents/repo_agent.py — enriched repo context output
  - agents/planner_agent.py — dynamic step resolution with conditions
  - agents/reviewer_agent.py — skill-aware review criteria
  - agents/coder_agent.py — step-level execution, verification awareness

Rewritten skills:
  - skills/java_upgrade.yaml (N conditional steps)
  - skills/spring_boot_upgrade.yaml (extends java_upgrade + N additional steps)
  - skills/angular_upgrade.yaml (N conditional steps)
  - skills/story_implementation.yaml (N conditional steps)
  - skills/test_generation.yaml (N conditional steps)
```

## PROMPT END
