# Vequil — Project Briefing for Claude Code

## What This Is

Vequil is a **reliability and observability layer for AI agent operators**. Think Stripe-level infrastructure seriousness. The goal is mass adoption — not a niche tool, but the layer the entire agentic web runs on.

This is NOT a stadium/venue reconciliation tool. That was a prior era. Do not touch, restore, or reference any stadium/venue-era code, schemas, or data.

## Core Product

- **Agent activity monitoring and audit logging** — ingest action logs from OpenClaw, Claude, LangChain, OpenAI
- **Anomaly detection** — logic loops, runaway spend, injection attempts, missing auth keys, high-cost reasoning calls
- **Weekly shareable "Report Cards"** — prove agent reliability to teams and investors with a public URL
- **Built for OpenClaw and Moltbook operators first**, then the broader agent ecosystem

## Stack

- **Frontend:** `web/static/index.html` (vanilla HTML/JS), `dashboard.html`, `report.html`, `app.js`, `app.css`
- **Backend:** Python in `src/vequil/` — `asgi.py` (FastAPI), `storage.py` (SQLite), `agent.py` (AI diagnosis), `pipeline.py`, `normalizers.py`, `rules.py`, `schema.py`, `settings.py`, `config.py`, `notifier.py`
- **Synthetic data:** `src/vequil/synthetic_data.py` — generates realistic OpenClaw/Claude/LangChain/OpenAI logs with injected anomalies
- **OpenClaw plugin:** `misc/openclaw/hooks/vequil_plugin.py` — streams agent actions into Vequil
- **Tests:** `tests/`
- **Docs:** `docs/` — pitch deck, roadmap, GTM playbook

## Hosting Plan

- **Backend:** Move to **Railway** (Python/FastAPI with gunicorn + uvicorn). Do NOT deploy to Netlify. The `netlify.toml` and `scripts/netlify_publish.sh` are legacy artifacts.
- **Database/waitlist:** Move to **Supabase** (replace SQLite). The `/api/demo` waitlist endpoint must write to Supabase so signups are captured durably.
- Current `Procfile` and `render.yaml` are for Render (old plan) — Railway replaces these.

## Tone Guidelines

Confident infrastructure company. Stripe, Linear, Vercel energy. Writing should feel like you're building the picks-and-shovels for a new era of computing — because you are.

- Direct and technical
- No growth-hack language
- No startup buzzwords
- Operators trust tools that sound serious

## DO NOT

- Use the word "viral" or "viral-proof" anywhere
- Deploy to Netlify
- Touch, restore, or reference anything from the stadium/venue era:
  - No `venue_area`, `terminal_id` (as venue concepts), `expected_sales`, `Shift4`, `FreedomPay`, `Amazon JWO`, `SeatGeek`, `Mashgin`, `Tapin2`
  - No `data/raw/amazon_jwo_settlement.csv`, `shift4_settlement.csv`, `freedompay_settlement.csv`
  - No `src/clearline/` (old product name, fully deleted)
  - No stadium imagery or stadium-era pitch language
- Amend or restore deleted files without explicit user approval

## Key Files — Core Vequil Product

| File | Role |
|---|---|
| `src/vequil/asgi.py` | FastAPI app — all API routes |
| `src/vequil/storage.py` | SQLite storage — workspaces, API keys, ingest events, leads |
| `src/vequil/agent.py` | AI diagnosis engine (OpenAI) |
| `src/vequil/pipeline.py` | Ingestion pipeline — normalizes agent logs into unified ledger |
| `src/vequil/normalizers.py` | Per-platform normalizers (OpenClaw, Claude, LangChain, OpenAI) |
| `src/vequil/rules.py` | Deterministic anomaly detection rules |
| `src/vequil/schema.py` | Shared dataclasses and column definitions |
| `src/vequil/settings.py` | ProcessorConfig loader from JSON |
| `src/vequil/config.py` | Paths and env setup |
| `src/vequil/notifier.py` | Slack + email alerts |
| `src/vequil/synthetic_data.py` | Generate realistic agent log data with injected anomalies |
| `configs/processors.json` | Platform ingestion configs (OpenClaw, Claude, LangChain, OpenAI) |
| `web/static/index.html` | Marketing/waitlist landing page |
| `web/static/dashboard.html` | Operator dashboard |
| `web/static/report.html` | Public report card |
| `web/static/app.js` | Frontend logic |
| `misc/openclaw/hooks/vequil_plugin.py` | OpenClaw integration hook |
| `scripts/moltbook_campaign.py` | Moltbook post generator |
| `docs/pitch_deck.md` | Investor pitch deck |
| `docs/roadmap.md` | Product roadmap |
| `docs/moltbook_go_to_market.md` | GTM playbook |

## Architecture Notes

- `storage.py` implements `VequilStorage` using SQLite with tables: `workspaces`, `workspace_api_keys`, `ingest_events`, and (check current schema) `leads`
- `configs/processors.json` maps platform-specific column names to the unified Vequil schema — this is the translation layer
- `configs/expected_sales.json` maps the "resource baseline" / budget comparison feed — repurposed from venue-era but currently used for agent cost baseline comparisons
- The column names in `schema.py` (`venue_area`, `terminal_id`, etc.) are **venue-era artifacts used as generic slot names** in the current unified ledger — they should eventually be renamed to `agent_context`, `session_id`, etc., but do not rename without explicit user instruction
