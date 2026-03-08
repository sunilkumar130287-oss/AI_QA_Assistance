"""Custom exception hierarchy for the agent framework.

All exceptions inherit from AgentFrameworkError, enabling callers to catch
broad categories or specific failure modes as needed.
"""


class AgentFrameworkError(Exception):
    """Base exception for all agent framework errors."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


class LLMCallError(AgentFrameworkError):
    """Any error communicating with the Torri LLM proxy."""

    def __init__(self, message: str, status_code: int | None = None, details: dict | None = None):
        super().__init__(message, details)
        self.status_code = status_code


class LLMRateLimitError(LLMCallError):
    """HTTP 429 — rate-limited by Torri proxy."""

    def __init__(self, message: str = "Rate limited by LLM proxy", retry_after: float | None = None):
        super().__init__(message, status_code=429)
        self.retry_after = retry_after


class LLMTimeoutError(LLMCallError):
    """LLM call exceeded the configured timeout."""

    def __init__(self, message: str = "LLM call timed out", timeout_seconds: float | None = None):
        super().__init__(message, status_code=None)
        self.timeout_seconds = timeout_seconds


class ToolExecutionError(AgentFrameworkError):
    """A tool failed during execution."""

    def __init__(self, tool_name: str, message: str, details: dict | None = None):
        super().__init__(f"Tool '{tool_name}' failed: {message}", details)
        self.tool_name = tool_name


class BuildFailedError(AgentFrameworkError):
    """Build could not be fixed after maximum retries."""

    def __init__(self, message: str = "Build failed after max retries", build_output: str = ""):
        super().__init__(message)
        self.build_output = build_output


class TestFailedError(AgentFrameworkError):
    """Tests could not be fixed after maximum retries."""

    def __init__(self, message: str = "Tests failed after max retries", test_output: str = ""):
        super().__init__(message)
        self.test_output = test_output


class MaxIterationsError(AgentFrameworkError):
    """Agent hit its iteration limit without completing."""

    def __init__(self, agent_name: str, iterations: int):
        super().__init__(
            f"Agent '{agent_name}' reached max iterations ({iterations})"
        )
        self.agent_name = agent_name
        self.iterations = iterations


class SkillNotFoundError(AgentFrameworkError):
    """Requested skill/task type does not exist."""

    def __init__(self, skill_name: str):
        super().__init__(f"Skill '{skill_name}' not found")
        self.skill_name = skill_name


class EscalationRequired(AgentFrameworkError):
    """Agent cannot proceed and needs human intervention."""

    def __init__(self, agent_name: str, reason: str, context: dict | None = None):
        super().__init__(
            f"Agent '{agent_name}' requires human escalation: {reason}"
        )
        self.agent_name = agent_name
        self.reason = reason
        self.context = context or {}
