from __future__ import annotations

import os
import re

import pandas as pd

# ---------------------------------------------------------------------------
# Real OpenAI client — only imported if the API key is present at runtime.
# This keeps the module importable even without the package installed.
# ---------------------------------------------------------------------------
_openai_client = None


def _get_openai_client():
    """Lazily initialise the OpenAI client once, then cache it."""
    global _openai_client
    if _openai_client is not None:
        return _openai_client
    try:
        from openai import OpenAI  # type: ignore
        _openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        return _openai_client
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are Vequil's Agent Audit Engine — an expert in observing and auditing AI agent behavior.
Your job is to diagnose anomalies in agent action logs (OpenClaw, Claude, OpenAI, LangChain)
and produce a plain-English root cause and a concrete, one-sentence recommendation for the operator.

Rules:
- Be specific about the platform (OpenClaw, Claude, OpenAI, LangChain).
- Show awareness of common agent failure modes: runaway loops, tool call failures,
  API cost spikes, and missing authentication keys.
- Keep diagnosis ≤ 2 sentences. Keep recommended_action ≤ 1 sentence.
- Return ONLY valid JSON in this exact shape:
  {"diagnosis": "...", "recommended_action": "..."}
"""


def create_prompt(row: pd.Series) -> str:
    """Build a focused user-level prompt from an anomaly row."""
    action_id = row.get("action_id",       "Unknown")
    proc      = row.get("processor",       "Unknown")
    context   = row.get("agent_context",   "Unknown")
    session   = row.get("session_id",      "Unknown")
    amount    = row.get("amount",          0)
    d_type    = row.get("discrepancy_type","Unknown Anomaly")
    status    = row.get("action_status",   "")
    auth      = row.get("auth_key",        "")

    amount_str = f"${float(amount):.4f}" if pd.notna(amount) else "Unknown"

    return (
        f"Diagnose this AI agent action anomaly.\n"
        f"Platform:          {proc}\n"
        f"Agent Context:     {context}\n"
        f"Session ID:        {session}\n"
        f"Action ID:         {action_id}\n"
        f"Cost:              {amount_str}\n"
        f"Action Status:     {status}\n"
        f"Auth Key:          {auth if auth else '(missing)'}\n"
        f"Flagged As:        {d_type}\n\n"
        f"Return JSON only."
    )


# ---------------------------------------------------------------------------
# LLM call — real or mock
# ---------------------------------------------------------------------------

def _call_llm(prompt: str) -> dict:
    """Try the real OpenAI API first; fall back to the mock on any failure."""
    client = _get_openai_client()
    if client is not None:
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.2,
                max_tokens=200,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
            )
            raw = response.choices[0].message.content.strip()
            raw = re.sub(r"^```(?:json)?", "", raw).strip().rstrip("```").strip()
            import json
            return json.loads(raw)
        except Exception as exc:
            print(f"[agent] OpenAI call failed ({exc}), falling back to mock.")

    return _mock_llm(prompt)


def _mock_llm(prompt: str) -> dict:
    """
    High-quality rule-based mock. Used when OPENAI_API_KEY is not set or the
    API call fails.
    """
    p = prompt.lower()

    if "failed_syscall" in p or "failed action" in p:
        if "openclaw" in p:
            return {
                "diagnosis": (
                    "OpenClaw attempted to browse a restricted analytics endpoint and was "
                    "blocked by the sandbox — it appears to have found a reference to an "
                    "unauthorized URL in local docs and went off-script."
                ),
                "recommended_action": (
                    "Review the agent's web permissions or update local docs to remove "
                    "unauthorized URL references."
                ),
            }
        return {
            "diagnosis": "Action reported a non-terminal status after an unexpected failure — the agent went off-script.",
            "recommended_action": "Check the project's system logs for unauthorized directory traversals.",
        }

    if "missing auth key" in p or "auth" in p:
        return {
            "diagnosis": (
                "The agent attempted an API call with a missing or revoked authentication key. "
                "It may be targeting an unconfigured model platform."
            ),
            "recommended_action": (
                "Verify your environment secrets and confirm the agent does not have access "
                "to hardcoded third-party model endpoints."
            ),
        }

    if "duplicate action" in p or "loop" in p:
        return {
            "diagnosis": (
                "Identified a recursive loop — the agent has been repeating the same action "
                "across multiple iterations, indicating a runaway reasoning chain."
            ),
            "recommended_action": (
                "Implement a strict max_steps limit in your agent config to break "
                "runaway reasoning chains."
            ),
        }

    if "high-cost call" in p or "cost" in p:
        return {
            "diagnosis": (
                "Individual call cost spiked — the agent escalated this request to a "
                "high-cost reasoning path, consuming significant budget in a single step."
            ),
            "recommended_action": (
                "Set a hard token and cost limit on the agent executor to prevent "
                "accidental budget burn during reasoning-heavy tasks."
            ),
        }

    return {
        "diagnosis": "An unclassified anomaly was detected — the agent is operating in an unexpected pattern.",
        "recommended_action": "Escalate to the operator to check for unauthorized model calls or tool injections.",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def diagnose_discrepancies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich a discrepancies DataFrame with 'diagnosis' and 'recommended_action'
    columns by querying either the real OpenAI API or the high-quality mock.
    """
    if df.empty:
        df = df.copy()
        df["diagnosis"] = []
        df["recommended_action"] = []
        return df

    using_real_llm = _get_openai_client() is not None
    if using_real_llm:
        print(f"[agent] OpenAI API key detected — using gpt-4o-mini for {len(df)} rows.")
    else:
        print(f"[agent] No API key — using high-quality mock for {len(df)} rows.")

    diagnoses: list[str] = []
    actions: list[str] = []

    for _, row in df.iterrows():
        result = _call_llm(create_prompt(row))
        diagnoses.append(result.get("diagnosis", ""))
        actions.append(result.get("recommended_action", ""))

    out = df.copy()
    out["diagnosis"] = diagnoses
    out["recommended_action"] = actions
    return out
