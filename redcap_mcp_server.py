#!/usr/bin/env python3
"""Ultra-compact, zero-dependency stdio MCP Server for REDCap Single-Line Conversion.

Designed for Google Antigravity IDE / CLI with Orchestrator (Neon) + Hydrogen worker.
Implements Model Context Protocol (JSON-RPC 2.0 over stdio) using Python 3 stdlib only.
No pip install, no PowerShell, no admin privileges required.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Ensure sibling redcap_flatten.py is importable regardless of working directory
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from redcap_flatten import VALID_MODES, convert_redcap, inspect_redcap  # noqa: E402

SERVER_NAME = "redcap-singleline-mcp"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "inspect_redcap_csv",
        "description": (
            "Inspect any REDCap CSV/TSV export (classic or longitudinal, raw or labeled headers). "
            "Returns record ID column, events, repeating instruments, max repeat instance, and all "
            "fields classified as static, repeating_instrument, repeating_event, or longitudinal."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "input_path": {"type": "string", "description": "Path to REDCap CSV/TSV file"},
                "id_col": {"type": "string", "description": "Optional record ID column override"},
            },
            "required": ["input_path"],
        },
    },
    {
        "name": "preview_singleline",
        "description": (
            "Dry-run conversion on the first N records using selected fields and collapse modes "
            "(auto, wide, join, unique, first, last, count, min, max, sum, mean) without writing a file."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "input_path": {"type": "string", "description": "Path to REDCap CSV/TSV file"},
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fields to include (supports * wildcards, omit for all fields)",
                },
                "default_mode": {
                    "type": "string",
                    "enum": sorted(VALID_MODES),
                    "default": "wide",
                    "description": "Default collapse mode for multi-line fields",
                },
                "field_modes": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Optional per-field collapse mode overrides",
                },
                "sep": {"type": "string", "default": "; ", "description": "Separator for join/unique modes"},
                "tag_instance": {"type": "boolean", "default": False, "description": "Prefix joined values with [slot]"},
                "filter_events": {"type": "array", "items": {"type": "string"}},
                "filter_instruments": {"type": "array", "items": {"type": "string"}},
                "preview_limit": {"type": "integer", "default": 5, "description": "Max records to preview"},
            },
            "required": ["input_path"],
        },
    },
    {
        "name": "convert_redcap_to_singleline",
        "description": (
            "Convert a multi-line REDCap repeating instruments/events CSV/TSV into a single-line-per-record "
            "CSV/TSV with user-selected fields and per-field collapse strategies."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "input_path": {"type": "string", "description": "Path to input REDCap CSV/TSV"},
                "output_path": {"type": "string", "description": "Path to output single-line CSV/TSV"},
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Selected fields (supports * wildcards)",
                },
                "default_mode": {
                    "type": "string",
                    "enum": sorted(VALID_MODES),
                    "default": "wide",
                },
                "field_modes": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "id_col": {"type": "string"},
                "sep": {"type": "string", "default": "; "},
                "tag_instance": {"type": "boolean", "default": False},
                "filter_events": {"type": "array", "items": {"type": "string"}},
                "filter_instruments": {"type": "array", "items": {"type": "string"}},
                "profile_path": {"type": "string", "description": "Optional JSON profile to load settings from"},
            },
            "required": ["input_path", "output_path"],
        },
    },
    {
        "name": "manage_conversion_profile",
        "description": "Save or load a reusable JSON field-selection profile for recurring REDCap exports.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["save", "load"]},
                "profile_path": {"type": "string", "description": "Path to JSON profile"},
                "profile": {
                    "type": "object",
                    "description": "Profile payload when action='save' (fields, default_mode, field_modes, sep, tag_instance)",
                },
            },
            "required": ["action", "profile_path"],
        },
    },
]


def _dispatch_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "inspect_redcap_csv":
        return inspect_redcap(args["input_path"], id_col=args.get("id_col"))

    if name == "preview_singleline":
        return convert_redcap(
            input_path=args["input_path"],
            output_path=None,
            fields=args.get("fields"),
            default_mode=args.get("default_mode", "wide"),
            field_modes=args.get("field_modes"),
            sep=args.get("sep", "; "),
            tag_instance=bool(args.get("tag_instance", False)),
            filter_events=args.get("filter_events"),
            filter_instruments=args.get("filter_instruments"),
            preview_limit=int(args.get("preview_limit", 5)),
        )

    if name == "convert_redcap_to_singleline":
        fields = args.get("fields")
        default_mode = args.get("default_mode", "wide")
        field_modes = dict(args.get("field_modes") or {})
        sep = args.get("sep", "; ")
        tag_instance = bool(args.get("tag_instance", False))
        if args.get("profile_path"):
            prof = json.loads(Path(args["profile_path"]).read_text(encoding="utf-8"))
            fields = fields or prof.get("fields")
            default_mode = args.get("default_mode", prof.get("default_mode", "wide"))
            merged = dict(prof.get("field_modes", {}))
            merged.update(field_modes)
            field_modes = merged
            sep = args.get("sep", prof.get("sep", "; "))
            tag_instance = bool(args.get("tag_instance", prof.get("tag_instance", False)))
        return convert_redcap(
            input_path=args["input_path"],
            output_path=args["output_path"],
            fields=fields,
            default_mode=default_mode,
            field_modes=field_modes,
            id_col=args.get("id_col"),
            sep=sep,
            tag_instance=tag_instance,
            filter_events=args.get("filter_events"),
            filter_instruments=args.get("filter_instruments"),
        )

    if name == "manage_conversion_profile":
        p = Path(args["profile_path"])
        if args["action"] == "save":
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(args.get("profile", {}), indent=2), encoding="utf-8")
            return {"status": "saved", "profile_path": str(p.resolve())}
        return {"status": "loaded", "profile": json.loads(p.read_text(encoding="utf-8"))}

    raise ValueError(f"Unknown tool: {name}")


def _send(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def handle_request(req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "notifications/initialized":
        return None
    if method == "initialize":
        client_ver = params.get("protocolVersion") or PROTOCOL_VERSION
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": client_ver,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        tname = params.get("name", "")
        targs = params.get("arguments") or {}
        try:
            data = _dispatch_tool(tname, targs)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(data, indent=2)}],
                    "isError": False,
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error: {exc}"}],
                    "isError": True,
                },
            }
    if req_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    return None


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            _send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}})
            continue
        resp = handle_request(req)
        if resp is not None:
            _send(resp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
