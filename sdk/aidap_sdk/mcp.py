"""AIDAP as an MCP server (stdio), so an agent can check content before it reads or stores it.

  AIDAP_URL=... AIDAP_API_KEY=... AIDAP_PROJECT=prj_... AIDAP_PROFILE=agent_tool_output python -m aidap_sdk.mcp

Tools: ``aidap_check`` (submit text, return the decision), ``aidap_result`` (re-read a decision), ``aidap_findings``.
The server never returns the checked content or finding excerpts, and it never releases anything: a decision of
anything other than ``pass`` means the agent must not use the content. Standard library only.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from .client import AidapError, Client

PROTOCOL = "2024-11-05"
TOOLS = [
    {"name": "aidap_check", "description": "Check text against an AIDAP intended-use profile before using it. Returns pass, review, "
     "quarantine or block with reason codes. Only 'pass' means the content may be used.",
     "inputSchema": {"type": "object", "required": ["text"], "properties": {
         "text": {"type": "string", "description": "The content to check"},
         "filename": {"type": "string", "description": "A name for the content, e.g. search_result.txt"},
         "profile": {"type": "string", "description": "Profile id; defaults to AIDAP_PROFILE"},
         "destination": {"type": "string"}, "source_class": {"type": "string"},
         "metadata": {"type": "object", "description": "owner, source_revision, effective_date, upstream_checks, ..."}}}},
    {"name": "aidap_result", "description": "Re-read the decision of an earlier check.",
     "inputSchema": {"type": "object", "required": ["run_id"], "properties": {"run_id": {"type": "string"}}}},
    {"name": "aidap_findings", "description": "List the findings behind a decision (no excerpts of the content).",
     "inputSchema": {"type": "object", "required": ["run_id"], "properties": {"run_id": {"type": "string"}, "severity": {"type": "string"}}}},
]


def _reply(id_: Any, result: Any = None, error: dict | None = None) -> None:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "id": id_}
    msg.update({"error": error} if error else {"result": result})
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _text(payload: Any, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": payload if isinstance(payload, str) else json.dumps(payload, indent=2)}], "isError": is_error}


def call_tool(client: Client, name: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "aidap_check":
            project = os.environ.get("AIDAP_PROJECT", "")
            profile = args.get("profile") or os.environ.get("AIDAP_PROFILE", "agent_tool_output")
            if not project:
                return _text("AIDAP_PROJECT is not set on the server", True)
            r = client.assure(str(args.get("text", "")), project=project, profile=profile, filename=args.get("filename") or "agent_input.txt",
                              destination=args.get("destination", ""), source_class=args.get("source_class", "unknown"),
                              metadata=args.get("metadata") or None, wait_timeout=120)
            return _text({"run_id": r.run_id, "decision": r.decision, "usable": r.decision == "pass" and r.release_authorized,
                          "reasons": r.reason_codes, "summary": r.summary})
        if name == "aidap_result":
            r = client.wait(str(args["run_id"]), timeout=30)
            return _text({"run_id": r.run_id, "decision": r.decision, "usable": r.decision == "pass" and r.release_authorized,
                          "reasons": r.reason_codes, "summary": r.summary})
        if name == "aidap_findings":
            f = client.findings(str(args["run_id"]), severity=args.get("severity", "")).get("findings", [])
            return _text([{k: x[k] for k in ("code", "severity", "title", "observed", "recommended_action")} for x in f[:50]])
    except (AidapError, ValueError, TimeoutError, KeyError) as exc:
        return _text(f"{type(exc).__name__}: {exc}", True)
    return _text(f"unknown tool {name}", True)


def serve(client: Client | None = None) -> None:
    cl = client or Client()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            _reply(None, error={"code": -32700, "message": "parse error"})
            continue
        method, id_ = msg.get("method"), msg.get("id")
        if id_ is None:                                         # notifications need no reply
            continue
        if method == "initialize":
            _reply(id_, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                         "serverInfo": {"name": "aidap", "version": "1.0.0"}})
        elif method == "tools/list":
            _reply(id_, {"tools": TOOLS})
        elif method == "tools/call":
            p = msg.get("params") or {}
            _reply(id_, call_tool(cl, p.get("name", ""), p.get("arguments") or {}))
        elif method == "ping":
            _reply(id_, {})
        else:
            _reply(id_, error={"code": -32601, "message": f"method not found: {method}"})


if __name__ == "__main__":
    serve()
