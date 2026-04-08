from pathlib import Path

import pytest

from vequil.normalizers import generate_unified_ledger, normalize_openclaw, normalize_claude


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_generate_unified_ledger_assigns_event_ids_and_schema() -> None:
    ledger = generate_unified_ledger(PROJECT_ROOT / "data" / "raw")

    assert ledger["event_id"].tolist()[:3] == ["evt-00001", "evt-00002", "evt-00003"]
    assert ledger["event_id"].is_unique
    assert len(ledger) == 25000


def test_openclaw_normalizer_maps_agent_context() -> None:
    ledger = generate_unified_ledger(PROJECT_ROOT / "data" / "raw")
    openclaw_rows = ledger.loc[ledger["processor"] == "OpenClaw"]

    assert len(openclaw_rows) == 10000
    assert openclaw_rows["agent_context"].nunique() == 3  # 3 projects in synthetic data


def test_normalizer_raises_clear_error_when_required_columns_are_missing(tmp_path: Path) -> None:
    path = tmp_path / "openclaw_logs.csv"
    path.write_text("Timestamp,Project\n2026-04-07T09:00:00Z,vequil-alpha\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required columns"):
        normalize_openclaw(path)
