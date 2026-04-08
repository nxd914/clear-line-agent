"""
Vequil MCP Server — connects Claude Code to the Vequil reliability layer.

Claude Code can query agent activity, list anomalies, resolve issues, and
ingest events directly from your editor via the Model Context Protocol.

Usage (added automatically via .claude/settings.json):
  python src/vequil/mcp_server.py

Environment variables:
  VEQUIL_URL         Base URL of your Vequil deployment (default: http://localhost:8000)
  VEQUIL_API_KEY     Your DASHBOARD_API_KEY from the Vequil server
  VEQUIL_WORKSPACE   Default workspace slug to scope queries (optional)
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VEQUIL_URL = os.environ.get("VEQUIL_URL", "http://localhost:8000").rstrip("/")
VEQUIL_API_KEY = os.environ.get("VEQUIL_API_KEY", "")
DEFAULT_WORKSPACE = os.environ.get("VEQUIL_WORKSPACE", "")

mcp = FastMCP("vequil")


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if VEQUIL_API_KEY:
        h["X-API-Key"] = VEQUIL_API_KEY
    return h


def _get(path: str, params: dict | None = None) -> Any:
    with httpx.Client(timeout=10) as client:
        resp = client.get(f"{VEQUIL_URL}{path}", headers=_headers(), params=params or {})
        resp.raise_for_status()
        return resp.json()


def _post(path: str, body: dict) -> Any:
    with httpx.Client(timeout=10) as client:
        resp = client.post(f"{VEQUIL_URL}{path}", headers=_headers(), json=body)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def vequil_get_overview(workspace_id: int | None = None) -> str:
    """
    Get the current Vequil overview: total events, anomaly count, success rate,
    total cost, active agents, and recent anomalies.

    Pass workspace_id to scope to a specific team/project. Omit for all workspaces.
    """
    params = {}
    if workspace_id is not None:
        params["workspace_id"] = workspace_id
    data = _get("/api/overview", params=params)
    m = data.get("metrics", {})
    lines = [
        f"Total events: {m.get('total_events', 0):,}",
        f"Anomalies:    {m.get('anomaly_events', 0):,}",
        f"Resolved:     {m.get('resolved_events', 0):,}",
        f"Success rate: {m.get('success_rate', 0):.1f}%",
        f"Total cost:   ${m.get('total_cost_usd', 0):.4f}",
        f"Active agents: {m.get('active_agents', 0)}",
        f"Active sources: {m.get('active_sources', 0)}",
        f"Last event:   {m.get('last_event_at', 'never')}",
        "",
    ]
    anomalies = data.get("recent_anomalies", [])
    if anomalies:
        lines.append(f"Recent anomalies ({len(anomalies)}):")
        for a in anomalies[:5]:
            status = "(resolved)" if a.get("resolved_note") else "(open)"
            lines.append(
                f"  [{a['event_id']}] {a['anomaly_label']} — {a['source']} / {a['agent_id']} {status}"
            )
    else:
        lines.append("No anomalies detected in recent window.")
    return "\n".join(lines)


@mcp.tool()
def vequil_list_anomalies(workspace_id: int | None = None, limit: int = 20) -> str:
    """
    List flagged agent events that need operator review.

    Returns unresolved anomalies first, sorted by recency. Use resolve_anomaly
    to mark items as reviewed after investigation.
    """
    params: dict[str, Any] = {}
    if workspace_id is not None:
        params["workspace_id"] = workspace_id
    data = _get("/api/overview", params=params)
    anomalies = data.get("recent_anomalies", [])[:limit]

    if not anomalies:
        return "No anomalies detected."

    lines = [f"Flagged events ({len(anomalies)}):"]
    for a in anomalies:
        resolved = f"  RESOLVED: {a['resolved_note']}" if a.get("resolved_note") else "  OPEN"
        lines.append(
            f"\n[event_id={a['event_id']}]"
            f"\n  Label:    {a['anomaly_label']}"
            f"\n  Source:   {a['source']}"
            f"\n  Agent:    {a['agent_id']}"
            f"\n  Session:  {a.get('session_id', '')}"
            f"\n  Cost:     ${a.get('cost_usd', 0):.4f}"
            f"\n  At:       {a['event_at']}"
            f"\n  Status:{resolved}"
        )
    return "\n".join(lines)


@mcp.tool()
def vequil_resolve_anomaly(event_id: int, resolution: str) -> str:
    """
    Mark a flagged agent event as resolved with an explanation.

    event_id:   The integer event ID from vequil_list_anomalies.
    resolution: Plain-English explanation of what happened and how it was fixed.
                Example: "Rotated API key — agent was using a revoked key from .env"
    """
    result = _post("/api/resolve", {"event_id": event_id, "resolution": resolution})
    if result.get("status") == "ok":
        return f"Event {event_id} marked as resolved."
    return f"Failed to resolve event {event_id}: {result}"


@mcp.tool()
def vequil_get_report(workspace_slug: str = "all", days: int = 7) -> str:
    """
    Get the public reliability report card for a workspace.

    workspace_slug: slug of the workspace, or "all" for aggregate.
    days:           rolling window in days (default 7).

    This is the report you'd share with your team or investors.
    """
    data = _get("/api/public/report", params={"workspace_slug": workspace_slug, "days": days})
    if "error" in data:
        return f"Error: {data['error']}"
    m = data.get("metrics", {})
    lines = [
        f"Reliability Report — {data.get('workspace', {}).get('name', workspace_slug)}",
        f"Period: last {data.get('period_days', days)} days",
        f"",
        f"Total events:   {m.get('total_events', 0):,}",
        f"Anomalies:      {m.get('anomaly_events', 0):,}",
        f"Success rate:   {m.get('success_rate', 0):.1f}%",
        f"Total cost:     ${m.get('total_cost_usd', 0):.4f}",
        f"Active agents:  {m.get('active_agents', 0)}",
        f"",
        f"Top runtime:  {data.get('top_runtime', '—')}",
        f"Top agent:    {data.get('top_agent', '—')}",
        f"Top anomaly:  {data.get('top_anomaly', '—')}",
    ]
    recent = data.get("recent_anomalies", [])
    if recent:
        lines.append(f"\nRecent anomalies:")
        for a in recent[:3]:
            lines.append(f"  {a['anomaly_label']} — {a['agent_id']} @ {a['event_at']}")
    return "\n".join(lines)


@mcp.tool()
def vequil_list_workspaces() -> str:
    """
    List all Vequil workspaces (teams/projects) and their event counts.
    Use workspace IDs returned here with other tools to scope queries.
    """
    data = _get("/api/workspaces")
    workspaces = data.get("workspaces", [])
    if not workspaces:
        return "No workspaces found. Create one at POST /api/workspaces."
    lines = ["Workspaces:"]
    for w in workspaces:
        lines.append(f"  [{w['id']}] {w['name']} (slug: {w['slug']}) — created {w['created_at']}")
    return "\n".join(lines)


@mcp.tool()
def vequil_ingest_event(
    workspace_key: str,
    source: str,
    event_type: str,
    event_status: str,
    agent_id: str,
    event_at: str,
    session_id: str = "",
    tool_name: str = "",
    cost_usd: float = 0.0,
) -> str:
    """
    Log an agent action event directly to Vequil from Claude Code.

    workspace_key: Your ingest API key (vk_ws_...) for the workspace.
    source:        Platform name (openclaw, claude, openai, langchain, custom).
    event_type:    Type of action (tool_call, agent_response, chain_step, etc.).
    event_status:  Outcome (success, failed, completed, error, etc.).
    agent_id:      Identifier for the agent (e.g. "ops-agent-1").
    event_at:      ISO 8601 timestamp (e.g. "2026-04-08T12:00:00Z").
    session_id:    Session or conversation ID (optional).
    tool_name:     Tool used, if applicable (optional).
    cost_usd:      Cost in USD for this call (optional).
    """
    with httpx.Client(timeout=10) as client:
        resp = client.post(
            f"{VEQUIL_URL}/api/ingest",
            headers={"Content-Type": "application/json", "X-Workspace-Key": workspace_key},
            json={
                "source": source,
                "event_type": event_type,
                "event_status": event_status,
                "agent_id": agent_id,
                "event_at": event_at,
                "session_id": session_id or None,
                "tool_name": tool_name or None,
                "cost_usd": cost_usd if cost_usd else None,
                "metadata": {},
            },
        )
        resp.raise_for_status()
        result = resp.json()
    return f"Event logged. event_id={result.get('event_id')} workspace={result.get('workspace', {}).get('slug')}"


@mcp.tool()
def vequil_health() -> str:
    """Check if the Vequil server is reachable and responding."""
    try:
        data = _get("/health")
        return f"Vequil is up. URL: {VEQUIL_URL} — {data}"
    except Exception as exc:
        return f"Vequil unreachable at {VEQUIL_URL}: {exc}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
