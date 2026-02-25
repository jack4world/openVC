"""openVC agent utilities — helper commands for LLM agent and developer integration.

Subcommands:
    openvc agent exit-codes   Print stable exit codes (JSON or table)
    openvc agent schema       Print CLI structure as JSON for agent discovery
"""

from __future__ import annotations

import json
import sys
from typing import Any


# ── exit-codes ────────────────────────────────────────────────────────────────

def handle_exit_codes(json_mode: bool = False) -> int:
    from app.cli.exit_codes import EXIT_CODE_TABLE

    if json_mode:
        data = [
            {"code": code, "type": slug, "description": desc}
            for code, slug, desc in EXIT_CODE_TABLE
        ]
        print(json.dumps(data, indent=2))
        return 0

    width = 60
    print(f"\n{'─' * width}")
    print("  openVC — Stable Exit Codes")
    print(f"{'─' * width}")
    print(f"  {'Code':<6}  {'Type':<16}  Description")
    print(f"  {'─'*4}  {'─'*16}  {'─'*30}")
    for code, slug, desc in EXIT_CODE_TABLE:
        print(f"  {code:<6}  {slug:<16}  {desc}")
    print(f"{'─' * width}\n")
    return 0


# ── schema ────────────────────────────────────────────────────────────────────

def _action_to_dict(action: Any) -> dict:
    """Serialize a single argparse action to a dict."""
    import argparse

    d: dict = {
        "dest": action.dest,
        "help": action.help or "",
    }

    if isinstance(action, argparse._SubParsersAction):
        return {}  # handled separately

    option_strings = getattr(action, "option_strings", [])
    if option_strings:
        d["flags"] = option_strings
    else:
        d["positional"] = True

    # Type name
    if action.type is not None:
        d["type"] = getattr(action.type, "__name__", str(action.type))
    elif isinstance(action, argparse._StoreTrueAction):
        d["type"] = "bool"
        d["default"] = False
    elif isinstance(action, argparse._StoreFalseAction):
        d["type"] = "bool"
        d["default"] = True
    else:
        d["type"] = "string"

    if action.choices:
        d["choices"] = [str(c) for c in action.choices]
    if action.default is not None and not isinstance(action, (
        argparse._StoreTrueAction, argparse._StoreFalseAction
    )):
        # Ensure default is JSON-serializable (Path → str, etc.)
        dv = action.default
        d["default"] = str(dv) if not isinstance(dv, (str, int, float, bool)) else dv
    if action.required:
        d["required"] = True

    return d


def _parser_to_dict(parser: Any, name: str = "openvc") -> dict:
    """Recursively serialize an argparse parser to a nested dict."""
    import argparse

    result: dict = {
        "name": name,
        "description": parser.description or "",
        "flags": [],
        "subcommands": [],
    }

    subparser_map: dict = {}

    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        if isinstance(action, argparse._SubParsersAction):
            subparser_map = action.choices or {}
            continue
        d = _action_to_dict(action)
        if d:
            result["flags"].append(d)

    for sub_name, sub_parser in subparser_map.items():
        result["subcommands"].append(_parser_to_dict(sub_parser, name=sub_name))

    return result


def handle_schema(parser: Any, command_path: str | None, json_mode: bool = False) -> int:
    """Print CLI schema as JSON.

    Args:
        parser:       The root argparse.ArgumentParser.
        command_path: Optional dot/space path to a specific subcommand, e.g. "process".
        json_mode:    If True, pretty-print JSON; otherwise, also JSON (schema is always JSON).
    """
    schema = _parser_to_dict(parser)

    if command_path:
        # Navigate to requested subcommand
        parts = command_path.strip().split()
        node = schema
        for part in parts:
            found = next((s for s in node.get("subcommands", []) if s["name"] == part), None)
            if not found:
                print(f"Error: command '{part}' not found in schema", file=sys.stderr)
                return 1
            node = found
        schema = node

    print(json.dumps(schema, indent=2, ensure_ascii=False))
    return 0


# ── dispatcher ────────────────────────────────────────────────────────────────

def handle_agent_command(args: Any, parser: Any) -> int:
    """Dispatch `openvc agent <subcommand>`."""
    json_mode: bool = getattr(args, "json_output", False)
    subcommand: str = getattr(args, "agent_subcommand", "")

    if subcommand in ("exit-codes", "exitcodes", "exit-code"):
        return handle_exit_codes(json_mode=json_mode)

    if subcommand == "schema":
        command_path: str | None = getattr(args, "schema_command", None)
        return handle_schema(parser, command_path=command_path, json_mode=json_mode)

    print(f"Unknown agent subcommand: {subcommand}", file=sys.stderr)
    return 1
