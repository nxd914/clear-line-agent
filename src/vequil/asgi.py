from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict, deque
from http import HTTPStatus
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .config import WEB_DIR
from .storage import VequilStorage


app = FastAPI(title="Vequil", version="0.2")

_storage = VequilStorage()

_API_KEY: str | None = os.getenv("DASHBOARD_API_KEY")
_AUTH_REQUIRED: bool = os.getenv("VEQUIL_REQUIRE_AUTH", "0").strip() != "0"
_CORS_ALLOW_ORIGIN: str = os.getenv("VEQUIL_CORS_ALLOW_ORIGIN", "*")
_PUBLIC_RATE_LIMIT_PER_MINUTE = int(os.getenv("VEQUIL_PUBLIC_RATE_LIMIT", "60"))

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_WORKSPACE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9 _\-]{2,80}$")
_WORKSPACE_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-]{1,62}[a-z0-9]$")
_RESOLUTION_MAX_LEN = 2000

_buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_limited(ip: str, endpoint: str) -> bool:
    now = time.time()
    key = (ip, endpoint)
    bucket = _buckets[key]
    window_start = now - 60.0
    while bucket and bucket[0] < window_start:
        bucket.popleft()
    if len(bucket) >= _PUBLIC_RATE_LIMIT_PER_MINUTE:
        return True
    bucket.append(now)
    return False


def _audit_log(action: str, request: Request, **fields: Any) -> None:
    payload = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "action": action,
        "method": request.method,
        "path": str(request.url.path),
        "ip": _client_ip(request),
        **fields,
    }
    print(json.dumps(payload, ensure_ascii=True))


def _file_or_404(path: Path) -> FileResponse:
    if not path.exists():
        raise HTTPException(status_code=int(HTTPStatus.NOT_FOUND), detail="Not found")
    return FileResponse(path)


def _normalize_workspace_slug(value: str | None) -> str | None:
    slug = (value or "").strip().lower()
    if not slug:
        return None
    if slug in {"all", "latest"}:
        return slug
    if not _WORKSPACE_SLUG_PATTERN.match(slug):
        return None
    return slug


def _normalize_legacy_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9\-]+", "-", value.strip().lower()).strip("-")
    return slug[:63] or "legacy-runtime"


def _anomaly_label(event_status: str, metadata: dict[str, Any]) -> str | None:
    for key in ("anomaly_label", "anomaly_type", "risk_label", "flag", "issue", "alert"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]

    if metadata.get("loop_detected"):
        return "Loop detected"
    if metadata.get("blocked"):
        return "Blocked action"
    if metadata.get("cost_spike"):
        return "Cost spike"
    if metadata.get("approval_required"):
        return "Approval required"

    status = event_status.strip().lower()
    mapping = {
        "error": "Execution error",
        "failed": "Execution error",
        "failure": "Execution error",
        "timeout": "Timed out",
        "timed_out": "Timed out",
        "blocked": "Blocked action",
        "denied": "Blocked action",
        "warning": "Warning",
        "cancelled": "Cancelled run",
    }
    return mapping.get(status)


def require_auth(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if not _AUTH_REQUIRED:
        return
    if not _API_KEY or x_api_key != _API_KEY:
        raise HTTPException(status_code=int(HTTPStatus.UNAUTHORIZED), detail="Unauthorized")


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    slug: str = Field(min_length=3, max_length=64)


class IngestEventRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str = Field(min_length=1, max_length=80)
    event_type: str = Field(min_length=1, max_length=80)
    event_status: str = Field(min_length=1, max_length=40)
    event_at: str = Field(min_length=10, max_length=64)
    agent_id: str = Field(min_length=1, max_length=120)
    session_id: str | None = Field(default=None, max_length=120)
    tool_name: str | None = Field(default=None, max_length=120)
    cost_usd: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    resp: Response = await call_next(request)
    resp.headers["Access-Control-Allow-Origin"] = _CORS_ALLOW_ORIGIN
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key, X-Workspace-Key"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return resp


app.mount("/static", StaticFiles(directory=str(WEB_DIR), html=False), name="static")


@app.get("/")
def landing():
    return _file_or_404(WEB_DIR / "index.html")


@app.get("/dashboard.html")
@app.get("/console")
def dashboard():
    return _file_or_404(WEB_DIR / "dashboard.html")


@app.get("/report/{workspace_slug}")
def report_card(workspace_slug: str):
    normalized = _normalize_workspace_slug(workspace_slug)
    if normalized is None:
        raise HTTPException(status_code=int(HTTPStatus.BAD_REQUEST), detail="Invalid workspace slug")
    return _file_or_404(WEB_DIR / "report.html")


@app.get("/app.js")
def app_js():
    return _file_or_404(WEB_DIR / "app.js")


@app.get("/app.css")
def app_css():
    return _file_or_404(WEB_DIR / "app.css")


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/robots.txt", include_in_schema=False)
def robots():
    return _file_or_404(WEB_DIR / "robots.txt")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    return _file_or_404(WEB_DIR / "sitemap.xml")


@app.get("/api/health")
def health(_: None = Depends(require_auth)):
    return {"status": "ok", "auth": bool(_API_KEY) if _AUTH_REQUIRED else False}


@app.get("/api/workspaces")
def list_workspaces(_: None = Depends(require_auth)):
    return {"workspaces": _storage.list_workspaces()}


@app.post("/api/workspaces")
def create_workspace(body: WorkspaceCreateRequest, _: None = Depends(require_auth)):
    name = body.name.strip()
    slug = body.slug.strip().lower()
    if not _WORKSPACE_NAME_PATTERN.match(name):
        raise HTTPException(status_code=int(HTTPStatus.BAD_REQUEST), detail="Invalid workspace name")
    if not _WORKSPACE_SLUG_PATTERN.match(slug):
        raise HTTPException(status_code=int(HTTPStatus.BAD_REQUEST), detail="Invalid workspace slug")
    try:
        created = _storage.create_workspace(name=name, slug=slug)
    except Exception as exc:
        raise HTTPException(
            status_code=int(HTTPStatus.CONFLICT),
            detail="Workspace name or slug already exists",
        ) from exc
    return {"workspace": created}


@app.get("/api/workspaces/{workspace_id}/keys")
def list_workspace_keys(workspace_id: int, _: None = Depends(require_auth)):
    if not _storage.workspace_exists(workspace_id):
        raise HTTPException(status_code=int(HTTPStatus.NOT_FOUND), detail="Workspace not found")
    return {"keys": _storage.list_workspace_api_keys(workspace_id)}


@app.post("/api/workspaces/{workspace_id}/keys")
def create_workspace_key(workspace_id: int, _: None = Depends(require_auth)):
    if not _storage.workspace_exists(workspace_id):
        raise HTTPException(status_code=int(HTTPStatus.NOT_FOUND), detail="Workspace not found")
    return {"key": _storage.create_workspace_api_key(workspace_id)}


@app.delete("/api/workspaces/{workspace_id}/keys/{key_id}")
def revoke_workspace_key(workspace_id: int, key_id: int, _: None = Depends(require_auth)):
    if not _storage.workspace_exists(workspace_id):
        raise HTTPException(status_code=int(HTTPStatus.NOT_FOUND), detail="Workspace not found")
    revoked = _storage.revoke_workspace_api_key(workspace_id, key_id)
    if not revoked:
        raise HTTPException(status_code=int(HTTPStatus.NOT_FOUND), detail="Active key not found")
    return {"status": "ok", "revoked_key_id": key_id}


@app.get("/api/onboarding/quickstart")
def onboarding_quickstart(_: None = Depends(require_auth)):
    return {
        "steps": [
            "Create a workspace with POST /api/workspaces",
            "Copy the ingest_api_key from the response",
            "Send your first event to POST /api/ingest with X-Workspace-Key",
            "Open /dashboard.html and refresh the console",
        ],
        "example_ingest_event": {
            "source": "openclaw",
            "event_type": "tool_call",
            "event_status": "success",
            "event_at": "2026-04-08T01:30:00Z",
            "agent_id": "main-agent",
            "session_id": "session-123",
            "tool_name": "bash",
            "cost_usd": 0.012,
            "metadata": {"action_id": "abc123", "project": "vequil"},
        },
    }


@app.get("/api/history")
def history(_: None = Depends(require_auth)):
    return {"workspaces": _storage.list_workspace_rollups()}


@app.get("/api/overview")
def overview(workspace_id: int | None = None, _: None = Depends(require_auth)):
    if workspace_id is not None and not _storage.workspace_exists(workspace_id):
        raise HTTPException(status_code=int(HTTPStatus.NOT_FOUND), detail="Workspace not found")
    return _storage.get_overview(workspace_id=workspace_id)


@app.post("/api/resolve")
async def resolve(request: Request, _: None = Depends(require_auth)):
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=int(HTTPStatus.BAD_REQUEST), detail="JSON payload must be an object")

    event_id = int(data.get("event_id") or 0)
    resolution = str(data.get("resolution", "")).strip()
    if event_id <= 0:
        raise HTTPException(status_code=int(HTTPStatus.BAD_REQUEST), detail="Missing event_id")
    if not resolution:
        raise HTTPException(status_code=int(HTTPStatus.BAD_REQUEST), detail="Resolution is required")
    if len(resolution) > _RESOLUTION_MAX_LEN:
        raise HTTPException(status_code=int(HTTPStatus.BAD_REQUEST), detail="Resolution too long")

    updated = _storage.resolve_ingest_event(event_id=event_id, note=resolution)
    if not updated:
        raise HTTPException(status_code=int(HTTPStatus.NOT_FOUND), detail="Event not found")
    _audit_log("resolution_saved", request, event_id=event_id)
    return {"status": "ok", "event_id": event_id}


@app.post("/api/ingest")
def ingest(
    body: IngestEventRequest,
    request: Request,
    x_workspace_key: str | None = Header(default=None, alias="X-Workspace-Key"),
):
    workspace_key = (x_workspace_key or "").strip()
    if not workspace_key:
        raise HTTPException(status_code=int(HTTPStatus.UNAUTHORIZED), detail="Missing X-Workspace-Key")
    workspace = _storage.resolve_workspace_by_key(workspace_key)
    if not workspace:
        raise HTTPException(status_code=int(HTTPStatus.UNAUTHORIZED), detail="Invalid workspace key")

    payload = body.model_dump()
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    event_id = _storage.insert_ingest_event(
        workspace_id=workspace["id"],
        event_type=body.event_type,
        event_status=body.event_status,
        event_at=body.event_at,
        source=body.source,
        agent_id=body.agent_id,
        session_id=body.session_id,
        tool_name=body.tool_name,
        cost_usd=body.cost_usd,
        payload=payload,
        anomaly_label=_anomaly_label(body.event_status, metadata),
    )
    _audit_log(
        "ingest_event",
        request,
        workspace_id=workspace["id"],
        event_id=event_id,
        event_type=body.event_type,
    )
    return {
        "status": "ok",
        "workspace": {"id": workspace["id"], "slug": workspace["slug"]},
        "event_id": event_id,
    }


@app.post("/api/log")
async def legacy_log(request: Request, _: None = Depends(require_auth)):
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=int(HTTPStatus.BAD_REQUEST), detail="JSON payload must be an object")

    project_name = str(data.get("Project") or "Legacy Runtime").strip() or "Legacy Runtime"
    workspace = _storage.ensure_workspace(name=project_name, slug=_normalize_legacy_slug(project_name))
    metadata = {
        "action_id": data.get("ActionID"),
        "model": data.get("Model"),
        "deployment": data.get("Deployment"),
    }
    payload = {
        "source": str(data.get("Runtime") or "legacy").strip() or "legacy",
        "event_type": str(data.get("ToolUsed") or "tool_result").strip() or "tool_result",
        "event_status": str(data.get("TaskStatus") or "success").strip() or "success",
        "event_at": str(data.get("Timestamp") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())).strip(),
        "agent_id": str(data.get("AgentID") or data.get("Model") or "legacy-agent").strip() or "legacy-agent",
        "session_id": str(data.get("SessionID") or "").strip() or None,
        "tool_name": str(data.get("ToolUsed") or "").strip() or None,
        "cost_usd": float(data.get("ComputeCost") or 0.0),
        "metadata": metadata,
    }
    event_id = _storage.insert_ingest_event(
        workspace_id=int(workspace["id"]),
        event_type=payload["event_type"],
        event_status=payload["event_status"],
        event_at=payload["event_at"],
        source=payload["source"],
        agent_id=payload["agent_id"],
        session_id=payload["session_id"],
        tool_name=payload["tool_name"],
        cost_usd=payload["cost_usd"],
        payload=payload,
        anomaly_label=_anomaly_label(payload["event_status"], metadata),
    )
    _audit_log("legacy_log_ingested", request, workspace_id=workspace["id"], event_id=event_id)
    return {"status": "ok", "event_id": event_id, "workspace": workspace}


class DemoRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


@app.post("/api/demo")
def demo_waitlist(body: DemoRequest, request: Request):
    ip = _client_ip(request)
    if _rate_limited(ip, "demo"):
        return JSONResponse({"error": "Rate limit exceeded"}, status_code=int(HTTPStatus.TOO_MANY_REQUESTS))
    email = body.email.strip().lower()
    if not _EMAIL_PATTERN.match(email):
        raise HTTPException(status_code=int(HTTPStatus.BAD_REQUEST), detail="Invalid email address")
    _storage.capture_lead(email)
    _audit_log("demo_waitlist", request, email=email)
    return {"status": "ok"}


@app.get("/api/public/report")
def public_report(request: Request, workspace_slug: str | None = None, days: int = 7):
    ip = _client_ip(request)
    if _rate_limited(ip, "public_report"):
        return JSONResponse({"error": "Rate limit exceeded"}, status_code=int(HTTPStatus.TOO_MANY_REQUESTS))

    normalized_slug = _normalize_workspace_slug(workspace_slug)
    if workspace_slug is not None and normalized_slug is None:
        return JSONResponse({"error": "Invalid workspace slug"}, status_code=int(HTTPStatus.BAD_REQUEST))

    payload = _storage.get_public_report(workspace_slug=normalized_slug, days=days)
    if payload is None:
        return JSONResponse({"error": "Report not found"}, status_code=int(HTTPStatus.NOT_FOUND))
    return payload
