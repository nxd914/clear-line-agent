import json
from pathlib import Path

import pandas as pd

from vequil.pipeline import run_pipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pipeline_writes_reviewed_ledger_and_finding_table(tmp_path: Path) -> None:
    artifacts = run_pipeline(
        raw_data_dir=PROJECT_ROOT / "data" / "raw",
        output_dir=tmp_path,
    )

    reviewed = pd.read_csv(artifacts.ledger_path)
    discrepancies = pd.read_csv(artifacts.discrepancy_path)
    comparison = pd.read_csv(artifacts.comparison_path)
    dashboard = json.loads(artifacts.dashboard_path.read_text(encoding="utf-8"))

    assert len(reviewed) == 25000
    assert len(discrepancies) > 0
    assert int((reviewed["discrepancy_count"] > 0).sum()) == dashboard["metrics"]["flagged_events"]
    assert dashboard["metrics"]["total_findings"] == len(discrepancies)


def test_pipeline_detects_duplicate_actions(tmp_path: Path) -> None:
    artifacts = run_pipeline(
        raw_data_dir=PROJECT_ROOT / "data" / "raw",
        output_dir=tmp_path,
    )
    discrepancies = pd.read_csv(artifacts.discrepancy_path)

    duplicate_rows = discrepancies.loc[
        discrepancies["discrepancy_type"] == "Duplicate action"
    ]
    assert len(duplicate_rows) > 0
    assert duplicate_rows["action_id"].nunique() > 0


def test_pipeline_includes_baseline_findings(tmp_path: Path) -> None:
    artifacts = run_pipeline(
        raw_data_dir=PROJECT_ROOT / "data" / "raw",
        output_dir=tmp_path,
    )
    discrepancies = pd.read_csv(artifacts.discrepancy_path)
    comparison = pd.read_csv(artifacts.comparison_path)

    baseline_rows = discrepancies.loc[discrepancies["record_type"] == "baseline"]
    assert len(baseline_rows) > 0
    flagged_groups = comparison.loc[comparison["finding_count"] > 0]
    assert len(flagged_groups) > 0
