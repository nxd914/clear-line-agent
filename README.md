# Vequil

Reliability and observability infrastructure for AI agent operators.

## The Problem

AI agents take actions, spend money, and make decisions autonomously — with no accountability layer beneath them. Operators have no standard way to audit what their agents did, catch runaway loops or cost spikes before they compound, or prove reliability to their teams and investors.

## The Solution

Vequil is the reliability layer for the agentic era. Connect any agent runtime and Vequil records every action, flags anomalies in real time, and generates shareable weekly report cards that prove your agents are running correctly.

- **Ingest**: structured action logs from OpenClaw, Claude, OpenAI, LangChain — any runtime that can POST JSON
- **Detect**: deterministic rules catch failed actions, missing auth keys, runaway loops, duplicate execution, and high-cost calls
- **Diagnose**: AI audit engine explains anomalies in plain English and recommends operator actions
- **Report**: public report card URLs your team and investors can verify

## Why Now

The infrastructure layer for the agentic economy does not exist yet. Every tool category that matters at internet scale — databases, payment processors, monitoring — has a dominant infrastructure layer. Vequil is building that layer for agent operations.

## Quick Start

Requires Python 3.10+.

```bash
git clone https://github.com/nxd914/vequil.git
cd vequil
pip install -r requirements.txt
PYTHONPATH=src uvicorn vequil.asgi:app --reload
```

Open `http://localhost:8000/dashboard.html`.

## Ingest API

Create a workspace:

```bash
curl -X POST http://localhost:8000/api/workspaces \
  -H "X-API-Key: $DASHBOARD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "My Agent", "slug": "my-agent"}'
```

Send events using the returned `ingest_api_key`:

```bash
curl -X POST http://localhost:8000/api/ingest \
  -H "X-Workspace-Key: vk_ws_..." \
  -H "Content-Type: application/json" \
  -d '{
    "source": "openclaw",
    "event_type": "tool_call",
    "event_status": "success",
    "event_at": "2026-04-08T01:30:00Z",
    "agent_id": "ops-agent-1",
    "session_id": "session-123",
    "tool_name": "bash",
    "cost_usd": 0.012,
    "metadata": {"project": "vequil"}
  }'
```

Vequil is runtime-agnostic. Any system that can POST JSON can send activity to `/api/ingest`.

## OpenClaw Integration

```bash
cp misc/openclaw/hooks/vequil_plugin.py ~/.openclaw/workspace/skills/vequil/
export VEQUIL_API_KEY=your-key
export VEQUIL_URL=http://localhost:8000/api/log
```

Full guide: [misc/openclaw/README_OPENCLAW.md](misc/openclaw/README_OPENCLAW.md)

## Architecture

```
Platform logs (OpenClaw, Claude, LangChain, OpenAI)
    → Normalizer (platform-specific column maps in configs/processors.json)
    → Unified event ledger
    → Deterministic anomaly rules
    → AI diagnosis engine (gpt-4o-mini, falls back to rule-based mock)
    → Dashboard + public report card
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DASHBOARD_API_KEY` | Yes (prod) | API key for admin endpoints |
| `VEQUIL_REQUIRE_AUTH` | No | Set to `1` to enforce auth (default in prod) |
| `OPENAI_API_KEY` | No | Enables AI diagnosis; falls back to rule-based mock |
| `SLACK_WEBHOOK_URL` | No | Sends anomaly alerts to Slack |
| `SUPABASE_URL` | No | Syncs waitlist leads to Supabase |
| `SUPABASE_SERVICE_KEY` | No | Service key for Supabase REST API |

## Deploying to Railway

Set the required environment variables in Railway dashboard. The `railway.toml` handles build and start configuration automatically.

Supabase `leads` table (run once in your Supabase SQL editor):

```sql
create table leads (
  id uuid default gen_random_uuid() primary key,
  email text not null unique,
  created_at timestamptz default now()
);
```

## Integrations

| Runtime | Status |
|---|---|
| OpenClaw | Live |
| Anthropic Claude | Live |
| OpenAI | Live |
| LangChain | Live |
| Moltbook | Live |

## Roadmap

See [docs/roadmap.md](docs/roadmap.md).
