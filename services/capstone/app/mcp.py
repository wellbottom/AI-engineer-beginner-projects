"""In-process MCP_Server: a minimal Model-Context-Protocol-style tool registry.

The Capstone_App must expose **one or more tools to the Agent via the Model Context
Protocol** (Requirement 9.2). A full MCP SDK (a JSON-RPC server over stdio/SSE plus
a separate client transport) is heavyweight for a single-process practice service
and adds 3.14-wheel risk, so this module implements a **minimal in-process MCP-style
tool registry** that exposes tools to the Agent through an MCP-shaped interface —
each tool has a ``name``, a ``description``, and an ``invoke(arguments)`` method, and
the :class:`MCPServer` mirrors the MCP server surface (``list_tools`` / ``invoke``).
This decision is documented in ``development/buglists.md`` (BUG-009).

Design constraints honored here:

- **≥1 tool** (Requirement 9.2): :func:`build_default_mcp_server` registers two real,
  deterministic tools (``word_count`` and ``calculator``) so the Agent always has at
  least one tool available.
- **Tool failures are recorded, not fatal** (Requirement 9.8): a tool that raises is
  surfaced as a structured :class:`MCPToolError` carrying the tool name + reason; the
  Agent records the failure and continues with the remaining steps.
- **Dependency isolation**: no MCP SDK is imported. If a real MCP SDK is adopted
  later, only this module changes — the Agent depends solely on the
  ``list_tools`` / ``invoke`` surface, not on any transport.
"""

from __future__ import annotations

import ast
import operator
from dataclasses import dataclass
from typing import Any, Callable

__all__ = [
    "MCPToolError",
    "MCPToolSpec",
    "MCPTool",
    "MCPServer",
    "build_default_mcp_server",
    "word_count_tool",
    "calculator_tool",
]


class MCPToolError(Exception):
    """A tool invocation failed (unknown tool, or the tool raised).

    Carries the ``tool`` name and a human-readable ``reason`` so the Agent can record
    the failure and surface the failed tool in its final response (Requirement 9.8).
    """

    def __init__(self, tool: str, reason: str) -> None:
        self.tool = tool
        self.reason = reason or "tool invocation failed"
        super().__init__(self.reason)


@dataclass(frozen=True)
class MCPToolSpec:
    """The MCP-shaped public description of a tool (``name`` + ``description``)."""

    name: str
    description: str

    def to_json(self) -> dict[str, str]:
        return {"name": self.name, "description": self.description}


class MCPTool:
    """One registered tool exposed to the Agent via the MCP-shaped interface.

    A tool wraps a callable ``func(arguments: dict) -> Any``. :meth:`invoke` maps any
    exception the callable raises onto a structured :class:`MCPToolError` (so the
    Agent records a failed tool and continues), while a callable that already raises
    :class:`MCPToolError` is propagated unchanged.
    """

    def __init__(
        self,
        name: str,
        description: str,
        func: Callable[[dict[str, Any]], Any],
    ) -> None:
        self.name = name
        self.description = description
        self._func = func

    @property
    def spec(self) -> MCPToolSpec:
        """The tool's MCP-shaped ``name`` + ``description``."""
        return MCPToolSpec(name=self.name, description=self.description)

    def invoke(self, arguments: dict[str, Any] | None = None) -> Any:
        """Invoke the tool with ``arguments``; raise :class:`MCPToolError` on failure."""
        try:
            return self._func(dict(arguments or {}))
        except MCPToolError:
            raise
        except Exception as exc:  # noqa: BLE001 - map ANY tool error onto MCPToolError
            raise MCPToolError(self.name, str(exc) or "tool invocation failed") from exc


class MCPServer:
    """A minimal in-process MCP-style tool registry exposed to the Agent.

    Mirrors the MCP server surface the Agent needs: :meth:`list_tools` (tool
    discovery) and :meth:`invoke` (tool invocation). Tools are registered by name;
    registering a duplicate name replaces the earlier tool.
    """

    def __init__(self) -> None:
        self._tools: dict[str, MCPTool] = {}

    def register(self, tool: MCPTool) -> None:
        """Register (or replace) a tool by its name."""
        self._tools[tool.name] = tool

    def register_function(
        self,
        name: str,
        description: str,
        func: Callable[[dict[str, Any]], Any],
    ) -> MCPTool:
        """Convenience: build an :class:`MCPTool` from a callable and register it."""
        tool = MCPTool(name=name, description=description, func=func)
        self.register(tool)
        return tool

    def list_tools(self) -> list[MCPToolSpec]:
        """Return the MCP-shaped specs of every registered tool (discovery)."""
        return [tool.spec for tool in self._tools.values()]

    def tool_names(self) -> list[str]:
        """Return the registered tool names in registration order."""
        return list(self._tools.keys())

    def get_tool(self, name: str) -> MCPTool | None:
        """Return the registered tool named ``name``, or ``None``."""
        return self._tools.get(name)

    def invoke(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Invoke the named tool; raise :class:`MCPToolError` for unknown/failed tools.

        An unknown tool name raises :class:`MCPToolError` (so the Agent records it as a
        failed invocation and continues — Requirement 9.8), as does any error the tool
        itself raises.
        """
        tool = self._tools.get(name)
        if tool is None:
            raise MCPToolError(name, f"unknown tool: {name!r}")
        return tool.invoke(arguments)


# --------------------------------------------------------------------------- #
# Built-in tools (deterministic, no I/O, no network).
# --------------------------------------------------------------------------- #
def _pick_text(arguments: dict[str, Any]) -> str:
    """Pull the operand text from common argument keys (``text``/``task``/``input``)."""
    for key in ("text", "task", "input", "query"):
        value = arguments.get(key)
        if isinstance(value, str):
            return value
    return ""


def word_count_tool(arguments: dict[str, Any]) -> dict[str, int]:
    """Count words, characters, and lines in the supplied text.

    A deterministic, always-succeeding tool (given any string input). Reads the text
    from the ``text`` / ``task`` / ``input`` / ``query`` argument keys.
    """
    text = _pick_text(arguments)
    return {
        "words": len(text.split()),
        "characters": len(text),
        "lines": len(text.splitlines()) if text else 0,
    }


# Safe arithmetic operators for the calculator tool (no names/calls/attributes).
_ARITH_OPS: dict[type, Callable[..., Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_arith(node: ast.AST) -> float:
    """Safely evaluate an arithmetic AST node (numbers + + - * / // % ** only)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ARITH_OPS:
        return _ARITH_OPS[type(node.op)](_eval_arith(node.left), _eval_arith(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ARITH_OPS:
        return _ARITH_OPS[type(node.op)](_eval_arith(node.operand))
    raise ValueError("unsupported expression")


def calculator_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a safe arithmetic expression (``+ - * / // % **`` and parentheses).

    Reads the expression from the ``expression`` argument key, falling back to
    ``text`` / ``task`` / ``input`` / ``query``. Raises ``ValueError`` (mapped to a
    structured :class:`MCPToolError` by :meth:`MCPTool.invoke`) for any non-arithmetic
    input — this is the realistic "tool failure" the Agent records and continues past
    (Requirement 9.8).
    """
    expression = arguments.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        expression = _pick_text(arguments)
    expression = (expression or "").strip()
    if not expression:
        raise ValueError("no expression provided")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression: {expression!r}") from exc
    value = _eval_arith(tree.body)
    return {"expression": expression, "result": value}


def build_default_mcp_server() -> MCPServer:
    """Build the default MCP_Server with the built-in tools (Requirement 9.2).

    Registers at least one (here two) deterministic tool so the Agent always has a
    tool to invoke: ``word_count`` (always succeeds) and ``calculator`` (succeeds on
    arithmetic, fails cleanly otherwise — exercising the record-and-continue path).
    """
    server = MCPServer()
    server.register_function(
        "word_count",
        "Count the words, characters, and lines in the provided text.",
        word_count_tool,
    )
    server.register_function(
        "calculator",
        "Evaluate a basic arithmetic expression (+, -, *, /, //, %, ** and parentheses).",
        calculator_tool,
    )
    return server
