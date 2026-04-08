import pandas as pd

from vequil.rules import build_discrepancy_table, build_reviewed_ledger


def _make_event(**kwargs) -> dict:
    base = {
        "event_id": "evt-00001",
        "event_at": pd.Timestamp("2026-04-07 09:00:00"),
        "business_date": "2026-04-07",
        "processor": "OpenClaw",
        "agent_context": "vequil-alpha",
        "session_id": "OC-SESS-1234",
        "action_id": "ACT-100000",
        "auth_key": "sk-valid-key",
        "model_id": "gpt-4o",
        "action_type": "ACTION",
        "amount": 0.05,
        "action_status": "COMPLETED",
        "deployment_id": "PROD-A",
        "source_file": "openclaw_logs.csv",
    }
    base.update(kwargs)
    return base


def test_rules_emit_multiple_findings_for_one_event() -> None:
    ledger = pd.DataFrame([
        _make_event(
            auth_key="",
            action_status="FAILED_SYSCALL",
            amount=5.00,
        )
    ])

    discrepancies = build_discrepancy_table(ledger)
    reviewed = build_reviewed_ledger(ledger, discrepancies)

    types = discrepancies["discrepancy_type"].tolist()
    assert "Failed action" in types
    assert "Missing auth key" in types
    assert "High-cost call" in types
    assert reviewed.loc[0, "discrepancy_count"] == 3


def test_duplicate_action_finds_both_events() -> None:
    ledger = pd.DataFrame([
        _make_event(event_id="evt-00001", action_id="ACT-100", action_status="COMPLETED", auth_key="sk-key"),
        _make_event(event_id="evt-00002", action_id="ACT-100", action_status="COMPLETED", auth_key="sk-key"),
    ])

    discrepancies = build_discrepancy_table(ledger)

    assert discrepancies["discrepancy_type"].tolist() == [
        "Duplicate action",
        "Duplicate action",
    ]
