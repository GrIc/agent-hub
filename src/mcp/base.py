"""Base classes and middleware for the Agent Hub MCP server.

Every tool implements:
  class MyTool(BaseTool):
      name = "my_tool"
      description = "..."
      input_schema = { ... JSON Schema ... }
      output_schema = { ... JSON Schema ... }
      examples = [ {"input": {...}, "output": {...}}, ... ]
      requires_citations = True | False
      auth_required = True | False
      rate_limit_per_minute = 60

      def handle(self, args: dict) -> dict:
          ...

The framework handles:
  - input validation (jsonschema)
  - output validation
  - citation enforcement (if requires_citations)
  - error envelope normalization
  - structured logging

Authentication and rate-limit enforcement are performed by the transport layer.
"""

from abc import ABC, abstractmethod
import jsonschema, time, json, logging, uuid

logger = logging.getLogger("mcp")


class ToolError(Exception):
    def __init__(self, code: str, message: str, hint: str = ""):
        self.code = code
        self.message = message
        self.hint = hint


class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    examples: list[dict] = []
    requires_citations: bool = False
    auth_required: bool = False
    rate_limit_per_minute: int = 60

    @abstractmethod
    def handle(self, args: dict) -> dict:
        ...

    def __call__(self, args: dict, *, context: dict) -> dict:
        call_id = str(uuid.uuid4())[:8]
        t0 = time.time()
        try:
            jsonschema.validate(args, self.input_schema)
        except jsonschema.ValidationError as e:
            return self._error("invalid_input", str(e), call_id, t0)

        try:
            result = self.handle(args)
        except ToolError as e:
            return self._error(e.code, e.message, call_id, t0, hint=e.hint)
        except Exception as e:
            logger.exception("tool=%s call=%s unhandled", self.name, call_id)
            return self._error("internal_error", str(e), call_id, t0)

        try:
            jsonschema.validate(result, self.output_schema)
        except jsonschema.ValidationError as e:
            logger.error("tool=%s call=%s invalid output: %s", self.name, call_id, e)
            return self._error("invalid_output", str(e), call_id, t0)

        if self.requires_citations:
            from src.mcp.middleware.citation import enforce_citations
            err = enforce_citations(result)
            if err:
                return self._error("citation_failure", err, call_id, t0)

        dur_ms = int((time.time() - t0) * 1000)
        logger.info(
            json.dumps({"tool": self.name, "call_id": call_id,
                        "duration_ms": dur_ms, "success": True})
        )
        return result

    def _error(self, code, message, call_id, t0, hint=""):
        dur_ms = int((time.time() - t0) * 1000)
        logger.warning(json.dumps({
            "tool": self.name, "call_id": call_id, "duration_ms": dur_ms,
            "success": False, "error_code": code,
        }))
        return {"error": {"code": code, "message": message, "hint": hint}}
