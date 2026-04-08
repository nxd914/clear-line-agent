from __future__ import annotations

import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import DATA_DIR

SUCCESS_STATUSES = {"success", "completed", "ok", "resolved"}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    try:
        return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None


class VequilStorage:
    """Durable storage for workspaces, API keys, and ingested agent events."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (DATA_DIR / "vequil.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspaces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    slug TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workspace_api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id INTEGER NOT NULL,
                    key_value TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
                );

                CREATE TABLE IF NOT EXISTS ingest_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    event_status TEXT NOT NULL,
                    event_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    session_id TEXT,
                    tool_name TEXT,
                    cost_usd REAL,
                    payload_json TEXT NOT NULL,
                    anomaly_label TEXT,
                    resolved_note TEXT,
                    resolved_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
                );

                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                """
            )

    def capture_lead(self, email: str) -> None:
        """Save a waitlist lead to SQLite and attempt Supabase sync."""
        now = _utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO leads (email, created_at) VALUES (?, ?)",
                (email, now),
            )
        self._capture_lead_supabase(email)

    def _capture_lead_supabase(self, email: str) -> bool:
        """Fire-and-forget lead capture to Supabase. Returns True on success."""
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY")
        if not url or not key:
            return False
        try:
            import requests as _requests
            resp = _requests.post(
                f"{url}/rest/v1/leads",
                json={"email": email},
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                timeout=3,
            )
            return resp.status_code in (200, 201)
        except Exception:
            return False

    def create_workspace(self, name: str, slug: str) -> dict[str, Any]:
        key_value = f"vk_ws_{secrets.token_urlsafe(24)}"
        now = _utcnow_iso()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO workspaces (name, slug, created_at) VALUES (?, ?, ?)",
                (name, slug, now),
            )
            workspace_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO workspace_api_keys (workspace_id, key_value, created_at, revoked_at)
                VALUES (?, ?, ?, NULL)
                """,
                (workspace_id, key_value, now),
            )
        return {
            "id": workspace_id,
            "name": name,
            "slug": slug,
            "ingest_api_key": key_value,
        }

    def get_workspace_by_slug(self, slug: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, slug, created_at FROM workspaces WHERE slug = ?",
                (slug,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": int(row["id"]),
            "name": row["name"],
            "slug": row["slug"],
            "created_at": row["created_at"],
        }

    def ensure_workspace(self, name: str, slug: str) -> dict[str, Any]:
        existing = self.get_workspace_by_slug(slug)
        if existing:
            return existing
        created = self.create_workspace(name=name, slug=slug)
        return {
            "id": created["id"],
            "name": created["name"],
            "slug": created["slug"],
            "created_at": _utcnow_iso(),
        }

    def workspace_exists(self, workspace_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM workspaces WHERE id = ?",
                (workspace_id,),
            ).fetchone()
        return bool(row)

    def list_workspaces(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, slug, created_at FROM workspaces ORDER BY name ASC"
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "name": row["name"],
                "slug": row["slug"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def resolve_workspace_by_key(self, key_value: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT w.id, w.name, w.slug
                FROM workspace_api_keys k
                JOIN workspaces w ON w.id = k.workspace_id
                WHERE k.key_value = ? AND k.revoked_at IS NULL
                """,
                (key_value,),
            ).fetchone()
        if not row:
            return None
        return {"id": int(row["id"]), "name": row["name"], "slug": row["slug"]}

    def create_workspace_api_key(self, workspace_id: int) -> dict[str, Any]:
        key_value = f"vk_ws_{secrets.token_urlsafe(24)}"
        now = _utcnow_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO workspace_api_keys (workspace_id, key_value, created_at, revoked_at)
                VALUES (?, ?, ?, NULL)
                """,
                (workspace_id, key_value, now),
            )
            key_id = int(cur.lastrowid)
        return {
            "id": key_id,
            "workspace_id": workspace_id,
            "key_value": key_value,
            "created_at": now,
            "revoked_at": None,
        }

    def list_workspace_api_keys(self, workspace_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, workspace_id, key_value, created_at, revoked_at
                FROM workspace_api_keys
                WHERE workspace_id = ?
                ORDER BY id ASC
                """,
                (workspace_id,),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "workspace_id": int(row["workspace_id"]),
                "key_value": row["key_value"],
                "created_at": row["created_at"],
                "revoked_at": row["revoked_at"],
            }
            for row in rows
        ]

    def revoke_workspace_api_key(self, workspace_id: int, key_id: int) -> bool:
        now = _utcnow_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE workspace_api_keys
                SET revoked_at = ?
                WHERE id = ? AND workspace_id = ? AND revoked_at IS NULL
                """,
                (now, key_id, workspace_id),
            )
        return cur.rowcount > 0

    def insert_ingest_event(
        self,
        workspace_id: int,
        event_type: str,
        event_status: str,
        event_at: str,
        source: str,
        agent_id: str,
        session_id: str | None,
        tool_name: str | None,
        cost_usd: float | None,
        payload: dict[str, Any],
        anomaly_label: str | None = None,
    ) -> int:
        now = _utcnow_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO ingest_events (
                    workspace_id, event_type, event_status, event_at, source,
                    agent_id, session_id, tool_name, cost_usd, payload_json,
                    anomaly_label, resolved_note, resolved_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
                """,
                (
                    workspace_id,
                    event_type,
                    event_status,
                    event_at,
                    source,
                    agent_id,
                    session_id,
                    tool_name,
                    cost_usd,
                    json.dumps(payload),
                    anomaly_label,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def resolve_ingest_event(self, event_id: int, note: str) -> bool:
        now = _utcnow_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE ingest_events
                SET resolved_note = ?, resolved_at = ?
                WHERE id = ?
                """,
                (note, now, event_id),
            )
        return cur.rowcount > 0

    def _fetch_event_rows(
        self,
        workspace_id: int | None = None,
        limit: int | None = None,
        anomalies_only: bool = False,
    ) -> list[sqlite3.Row]:
        where_clauses: list[str] = []
        params: list[Any] = []
        if workspace_id is not None:
            where_clauses.append("e.workspace_id = ?")
            params.append(workspace_id)
        if anomalies_only:
            where_clauses.append("COALESCE(e.anomaly_label, '') <> ''")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        limit_sql = ""
        if limit is not None:
            limit_sql = " LIMIT ?"
            params.append(limit)

        query = f"""
            SELECT
                e.id,
                e.workspace_id,
                w.name AS workspace_name,
                w.slug AS workspace_slug,
                e.event_type,
                e.event_status,
                e.event_at,
                e.source,
                e.agent_id,
                e.session_id,
                e.tool_name,
                e.cost_usd,
                e.payload_json,
                e.anomaly_label,
                e.resolved_note,
                e.resolved_at,
                e.created_at
            FROM ingest_events e
            JOIN workspaces w ON w.id = e.workspace_id
            {where_sql}
            ORDER BY e.event_at DESC, e.id DESC
            {limit_sql}
        """
        with self._connect() as conn:
            return conn.execute(query, params).fetchall()

    def _event_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        return {
            "event_id": int(row["id"]),
            "workspace_id": int(row["workspace_id"]),
            "workspace_name": row["workspace_name"],
            "workspace_slug": row["workspace_slug"],
            "event_type": row["event_type"],
            "event_status": row["event_status"],
            "event_at": row["event_at"],
            "source": row["source"],
            "agent_id": row["agent_id"],
            "session_id": row["session_id"] or "",
            "tool_name": row["tool_name"] or "",
            "cost_usd": float(row["cost_usd"] or 0.0),
            "anomaly_label": row["anomaly_label"] or "",
            "resolved_note": row["resolved_note"] or "",
            "resolved_at": row["resolved_at"] or "",
            "metadata": metadata,
        }

    def list_recent_events(self, workspace_id: int | None = None, limit: int = 120) -> list[dict[str, Any]]:
        return [self._event_from_row(row) for row in self._fetch_event_rows(workspace_id=workspace_id, limit=limit)]

    def list_recent_anomalies(self, workspace_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
        events = [
            self._event_from_row(row)
            for row in self._fetch_event_rows(workspace_id=workspace_id, limit=limit, anomalies_only=True)
        ]
        return sorted(
            events,
            key=lambda item: (bool(item["resolved_note"]), item["event_at"]),
        )

    def list_workspace_rollups(self) -> list[dict[str, Any]]:
        query = """
            SELECT
                w.id,
                w.name,
                w.slug,
                w.created_at,
                COUNT(e.id) AS event_count,
                SUM(CASE WHEN COALESCE(e.anomaly_label, '') <> '' THEN 1 ELSE 0 END) AS anomaly_count,
                SUM(COALESCE(e.cost_usd, 0)) AS total_cost_usd,
                MAX(e.event_at) AS last_event_at
            FROM workspaces w
            LEFT JOIN ingest_events e ON e.workspace_id = w.id
            GROUP BY w.id
            ORDER BY event_count DESC, w.name ASC
        """
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
        return [
            {
                "id": int(row["id"]),
                "name": row["name"],
                "slug": row["slug"],
                "created_at": row["created_at"],
                "event_count": int(row["event_count"] or 0),
                "anomaly_count": int(row["anomaly_count"] or 0),
                "total_cost_usd": float(row["total_cost_usd"] or 0.0),
                "last_event_at": row["last_event_at"] or "",
            }
            for row in rows
        ]

    def list_runtime_rollups(self, workspace_id: int | None = None) -> list[dict[str, Any]]:
        where_sql = ""
        params: list[Any] = []
        if workspace_id is not None:
            where_sql = "WHERE workspace_id = ?"
            params.append(workspace_id)
        query = f"""
            SELECT
                source,
                COUNT(*) AS event_count,
                SUM(CASE WHEN COALESCE(anomaly_label, '') <> '' THEN 1 ELSE 0 END) AS anomaly_count,
                COUNT(DISTINCT agent_id) AS agent_count,
                SUM(COALESCE(cost_usd, 0)) AS total_cost_usd
            FROM ingest_events
            {where_sql}
            GROUP BY source
            ORDER BY event_count DESC, source ASC
        """
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "source": row["source"],
                "event_count": int(row["event_count"] or 0),
                "anomaly_count": int(row["anomaly_count"] or 0),
                "agent_count": int(row["agent_count"] or 0),
                "total_cost_usd": float(row["total_cost_usd"] or 0.0),
            }
            for row in rows
        ]

    def list_agent_rollups(self, workspace_id: int | None = None) -> list[dict[str, Any]]:
        where_sql = ""
        params: list[Any] = []
        if workspace_id is not None:
            where_sql = "WHERE workspace_id = ?"
            params.append(workspace_id)
        query = f"""
            SELECT
                agent_id,
                source,
                COUNT(*) AS event_count,
                SUM(CASE WHEN COALESCE(anomaly_label, '') <> '' THEN 1 ELSE 0 END) AS anomaly_count,
                SUM(COALESCE(cost_usd, 0)) AS total_cost_usd,
                MAX(event_at) AS last_event_at
            FROM ingest_events
            {where_sql}
            GROUP BY agent_id, source
            ORDER BY event_count DESC, agent_id ASC
            LIMIT 12
        """
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "agent_id": row["agent_id"],
                "source": row["source"],
                "event_count": int(row["event_count"] or 0),
                "anomaly_count": int(row["anomaly_count"] or 0),
                "total_cost_usd": float(row["total_cost_usd"] or 0.0),
                "last_event_at": row["last_event_at"] or "",
            }
            for row in rows
        ]

    def get_overview(self, workspace_id: int | None = None) -> dict[str, Any]:
        where_sql = ""
        params: list[Any] = []
        if workspace_id is not None:
            where_sql = "WHERE workspace_id = ?"
            params.append(workspace_id)

        metrics_query = f"""
            SELECT
                COUNT(*) AS total_events,
                SUM(CASE WHEN COALESCE(anomaly_label, '') <> '' THEN 1 ELSE 0 END) AS anomaly_events,
                SUM(CASE WHEN COALESCE(resolved_note, '') <> '' THEN 1 ELSE 0 END) AS resolved_events,
                SUM(CASE WHEN LOWER(event_status) IN ('success', 'completed', 'ok', 'resolved') THEN 1 ELSE 0 END) AS success_events,
                SUM(COALESCE(cost_usd, 0)) AS total_cost_usd,
                COUNT(DISTINCT agent_id) AS active_agents,
                COUNT(DISTINCT source) AS active_sources,
                COUNT(DISTINCT workspace_id) AS active_workspaces,
                MAX(event_at) AS last_event_at
            FROM ingest_events
            {where_sql}
        """
        with self._connect() as conn:
            row = conn.execute(metrics_query, params).fetchone()

        total_events = int(row["total_events"] or 0)
        success_events = int(row["success_events"] or 0)
        anomaly_events = int(row["anomaly_events"] or 0)
        resolved_events = int(row["resolved_events"] or 0)
        success_rate = (success_events / total_events * 100.0) if total_events else 0.0
        anomaly_rate = (anomaly_events / total_events * 100.0) if total_events else 0.0

        selected_workspace = None
        if workspace_id is not None:
            for workspace in self.list_workspaces():
                if workspace["id"] == workspace_id:
                    selected_workspace = workspace
                    break

        return {
            "generated_at": _utcnow_iso(),
            "selected_workspace": selected_workspace,
            "metrics": {
                "total_events": total_events,
                "anomaly_events": anomaly_events,
                "resolved_events": resolved_events,
                "success_rate": round(success_rate, 1),
                "anomaly_rate": round(anomaly_rate, 1),
                "total_cost_usd": round(float(row["total_cost_usd"] or 0.0), 4),
                "active_agents": int(row["active_agents"] or 0),
                "active_sources": int(row["active_sources"] or 0),
                "active_workspaces": int(row["active_workspaces"] or 0),
                "last_event_at": row["last_event_at"] or "",
            },
            "workspaces": self.list_workspace_rollups(),
            "runtimes": self.list_runtime_rollups(workspace_id=workspace_id),
            "top_agents": self.list_agent_rollups(workspace_id=workspace_id),
            "recent_events": self.list_recent_events(workspace_id=workspace_id, limit=120),
            "recent_anomalies": self.list_recent_anomalies(workspace_id=workspace_id, limit=50),
        }

    def get_public_report(self, workspace_slug: str | None = None, days: int = 7) -> dict[str, Any] | None:
        workspace_id: int | None = None
        workspace: dict[str, Any] | None = None
        normalized_slug = (workspace_slug or "").strip().lower()
        if normalized_slug and normalized_slug not in {"all", "latest"}:
            workspace = self.get_workspace_by_slug(normalized_slug)
            if not workspace:
                return None
            workspace_id = int(workspace["id"])

        overview = self.get_overview(workspace_id=workspace_id)
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
        recent_events = []
        for event in overview["recent_events"]:
            parsed = _parse_dt(event["event_at"])
            if parsed is None or parsed >= cutoff:
                recent_events.append(event)

        recent_anomalies = [event for event in recent_events if event["anomaly_label"]]
        runtime_counts: dict[str, int] = {}
        anomaly_counts: dict[str, int] = {}
        agent_counts: dict[str, int] = {}
        for event in recent_events:
            runtime_counts[event["source"]] = runtime_counts.get(event["source"], 0) + 1
            agent_counts[event["agent_id"]] = agent_counts.get(event["agent_id"], 0) + 1
            if event["anomaly_label"]:
                anomaly_counts[event["anomaly_label"]] = anomaly_counts.get(event["anomaly_label"], 0) + 1

        top_runtime = max(runtime_counts, key=runtime_counts.get) if runtime_counts else "No activity yet"
        top_agent = max(agent_counts, key=agent_counts.get) if agent_counts else "No active agent"
        top_anomaly = max(anomaly_counts, key=anomaly_counts.get) if anomaly_counts else "No anomalies detected"

        total_recent = len(recent_events)
        success_recent = sum(
            1
            for event in recent_events
            if event["event_status"].strip().lower() in SUCCESS_STATUSES
        )
        total_cost_recent = sum(float(event["cost_usd"] or 0.0) for event in recent_events)

        return {
            "generated_at": _utcnow_iso(),
            "period_days": max(days, 1),
            "workspace": workspace or {"name": "All Workspaces", "slug": "all"},
            "metrics": {
                "total_events": total_recent,
                "anomaly_events": len(recent_anomalies),
                "success_rate": round((success_recent / total_recent * 100.0), 1) if total_recent else 0.0,
                "total_cost_usd": round(total_cost_recent, 4),
                "active_agents": len(agent_counts),
                "active_sources": len(runtime_counts),
            },
            "top_runtime": top_runtime,
            "top_agent": top_agent,
            "top_anomaly": top_anomaly,
            "recent_anomalies": recent_anomalies[:6],
        }
