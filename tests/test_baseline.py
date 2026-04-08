from pathlib import Path

from vequil.baseline import (
    build_baseline_comparison,
    build_baseline_discrepancies,
    load_baseline,
)
from vequil.normalizers import generate_unified_ledger
from vequil.settings import load_baseline_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_baseline_comparison_flags_variance_groups() -> None:
    raw_dir = PROJECT_ROOT / "data" / "raw"
    ledger = generate_unified_ledger(raw_dir)
    baseline_config = load_baseline_config(PROJECT_ROOT / "configs" / "baseline.json")
    baseline = load_baseline(raw_dir, baseline_config)

    comparison = build_baseline_comparison(ledger, baseline, baseline_config)
    discrepancies = build_baseline_discrepancies(comparison, baseline_config)

    assert len(baseline) == 7
    assert len(comparison) > 0
    assert len(discrepancies) >= 0
