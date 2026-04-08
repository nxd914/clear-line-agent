import pandas as pd
from vequil.agent import diagnose_discrepancies, create_prompt


def test_diagnose_discrepancies_appends_columns():
    df = pd.DataFrame([
        {
            "event_id": "evt-001",
            "processor": "OpenClaw",
            "action_id": "ACT-100",
            "amount": 0.05,
            "discrepancy_type": "Failed action",
            "action_status": "FAILED_SYSCALL",
            "auth_key": "",
            "agent_context": "vequil-alpha",
            "session_id": "OC-SESS-1234",
        }
    ])
    result = diagnose_discrepancies(df)

    assert "diagnosis" in result.columns
    assert "recommended_action" in result.columns
    assert len(result) == 1
    assert len(result.iloc[0]["diagnosis"]) > 0


def test_diagnose_handles_empty_dataframe():
    df = pd.DataFrame()
    result = diagnose_discrepancies(df)
    assert "diagnosis" in result.columns
    assert "recommended_action" in result.columns
    assert len(result) == 0


def test_create_prompt_handles_missing_data():
    row = pd.Series({"amount": pd.NA})
    prompt = create_prompt(row)
    assert "Cost:              Unknown" in prompt
    assert "Unknown Anomaly" in prompt
