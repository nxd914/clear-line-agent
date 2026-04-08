# Vequil Setup Instructions

Complete setup guide for Supabase, Railway, and OpenClaw MCP integration.

---

## 1. Supabase — Durable Lead Capture

Supabase stores waitlist signups from `/api/demo` durably in the cloud.

### Create the table

1. Go to [supabase.com](https://supabase.com) → New Project
2. Open **SQL Editor** and run:

```sql
create table leads (
  id uuid default gen_random_uuid() primary key,
  email text not null unique,
  created_at timestamptz default now()
);

-- Optional: enable row-level security (recommended for production)
alter table leads enable row level security;
```

### Get your keys

1. Go to **Project Settings → API**
2. Copy:
   - **Project URL** → this is your `SUPABASE_URL`
   - **service_role** secret key → this is your `SUPABASE_SERVICE_KEY`

Keep the `service_role` key secret — never expose it in frontend code.

---

## 2. Railway — Deploy the Backend

Railway runs the Vequil Python backend (FastAPI + gunicorn). The backend also serves the frontend HTML.

### Deploy

1. Install Railway CLI: `npm install -g @railway/cli`
2. Login: `railway login`
3. From the project root:

```bash
railway init          # creates a new Railway project
railway up            # deploys (uses railway.toml automatically)
```

4. Once deployed, Railway gives you a URL like `vequil-production.up.railway.app`. Copy it.

### Set environment variables

In the Railway dashboard → your project → **Variables**, add:

| Variable | Value |
|---|---|
| `DASHBOARD_API_KEY` | Generate a strong random string (e.g. `openssl rand -hex 32`) |
| `OPENAI_API_KEY` | Your OpenAI key (enables AI diagnosis; optional but recommended) |
| `SUPABASE_URL` | From step 1 above |
| `SUPABASE_SERVICE_KEY` | From step 1 above |
| `VEQUIL_REQUIRE_AUTH` | `1` |
| `SLACK_WEBHOOK_URL` | Optional — Slack webhook for anomaly alerts |

Railway sets `PORT` automatically — the `railway.toml` already handles this.

### Verify

```bash
curl https://your-domain.up.railway.app/health
# → {"status":"ok"}

curl -X POST https://your-domain.up.railway.app/api/demo \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com"}'
# → {"status":"ok"}
```

Your landing page is live at `https://your-domain.up.railway.app`.

### Custom domain (optional)

In Railway dashboard → your project → **Settings → Domains** → add your domain and point DNS to Railway.

---

## 3. OpenClaw MCP Integration

The Vequil MCP server lets Claude Code query your Vequil data directly from the editor — list anomalies, resolve issues, get report cards, and log events without leaving your workflow.

### How it works

Claude Code starts the MCP server as a local subprocess. The server connects to your deployed Vequil instance and exposes tools Claude Code can call natively.

### Setup

**Step 1** — The MCP server is already configured. Update `.claude/settings.json` in the project root with your deployed URL and API key:

```json
{
  "mcpServers": {
    "vequil": {
      "command": "python",
      "args": ["src/vequil/mcp_server.py"],
      "env": {
        "VEQUIL_URL": "https://your-domain.up.railway.app",
        "VEQUIL_API_KEY": "your-DASHBOARD_API_KEY",
        "VEQUIL_WORKSPACE": ""
      }
    }
  }
}
```

**Step 2** — Restart Claude Code. The Vequil tools appear automatically.

**Step 3** — Test it. In any Claude Code session in this project, you can now say things like:

- "Check vequil for any open anomalies"
- "Get the Vequil overview for workspace 1"
- "Resolve event 42 — the auth key was rotated"
- "Show me the Vequil report card for the last 7 days"

### Available tools

| Tool | What it does |
|---|---|
| `vequil_health` | Check if Vequil is reachable |
| `vequil_get_overview` | Current metrics: events, anomalies, cost, success rate |
| `vequil_list_anomalies` | Flagged events needing review |
| `vequil_resolve_anomaly` | Mark a flagged event as resolved with a note |
| `vequil_get_report` | Public report card for a workspace |
| `vequil_list_workspaces` | List all workspaces and their IDs |
| `vequil_ingest_event` | Log an agent action directly from Claude Code |

### OpenClaw plugin

To stream OpenClaw agent actions into Vequil automatically:

```bash
# Copy the plugin into your OpenClaw hooks directory
cp misc/openclaw/hooks/vequil_plugin.py ~/.openclaw/workspace/skills/vequil/

# Set your Vequil endpoint and API key
export VEQUIL_API_KEY=your-workspace-ingest-key
export VEQUIL_URL=https://your-domain.up.railway.app/api/log
```

Every `tool_result_persist` event in OpenClaw will now stream to Vequil automatically.

---

## 4. First Run Checklist

After Railway is deployed and env vars are set:

```bash
# 1. Create your first workspace
curl -X POST https://your-domain.up.railway.app/api/workspaces \
  -H "X-API-Key: YOUR_DASHBOARD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "My Agent", "slug": "my-agent"}'
# → returns ingest_api_key: "vk_ws_..."

# 2. Send your first event
curl -X POST https://your-domain.up.railway.app/api/ingest \
  -H "X-Workspace-Key: vk_ws_..." \
  -H "Content-Type: application/json" \
  -d '{
    "source": "openclaw",
    "event_type": "tool_call",
    "event_status": "success",
    "event_at": "2026-04-08T12:00:00Z",
    "agent_id": "my-agent-1",
    "cost_usd": 0.012
  }'

# 3. Open the dashboard
open https://your-domain.up.railway.app/dashboard.html

# 4. Get a shareable report card
open https://your-domain.up.railway.app/report/my-agent
```

---

## 5. Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Generate synthetic test data
PYTHONPATH=src python src/vequil/synthetic_data.py

# Start the server
PYTHONPATH=src uvicorn vequil.asgi:app --reload

# Run tests
PYTHONPATH=src pytest tests/ -q
```

Server runs at `http://localhost:8000`. Dashboard at `http://localhost:8000/dashboard.html`.

---

## Environment Variable Reference

| Variable | Required | Where to get it |
|---|---|---|
| `DASHBOARD_API_KEY` | Yes (prod) | Generate: `openssl rand -hex 32` |
| `VEQUIL_REQUIRE_AUTH` | No | Set to `1` in production |
| `OPENAI_API_KEY` | No | platform.openai.com → API keys |
| `SUPABASE_URL` | No | Supabase → Project Settings → API |
| `SUPABASE_SERVICE_KEY` | No | Supabase → Project Settings → API → service_role |
| `SLACK_WEBHOOK_URL` | No | Slack → Apps → Incoming Webhooks |
