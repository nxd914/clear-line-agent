from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import RAW_DATA_DIR
from .schema import BASELINE_COLUMNS, BASELINE_COMPARISON_COLUMNS, DISCREPANCY_COLUMNS
from .settings import BaselineConfig, load_baseline_config


def load_baseline(
    raw_data_dir: Path = RAW_DATA_DIR,
    baseline_config: BaselineConfig | None = None,
) -> pd.DataFrame:
    config = baseline_config or load_baseline_config()
    path = raw_data_dir / config.filename
    df = pd.read_csv(path)

    missing_columns = [column for column in config.required_columns if column not in df.columns]
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise ValueError(f"{config.name} file {path.name} is missing required columns: {missing}")

    normalized = pd.DataFrame(
        {
            "business_date": pd.to_datetime(df[config.field_map["business_date"]]).dt.strftime("%Y-%m-%d"),
            "source_system": df[config.field_map["source_system"]],
            "agent_context": df[config.field_map["agent_context"]],
            "session_id": df[config.field_map.get("session_id", "")].fillna("") if "session_id" in config.field_map else "",
            "expected_amount": df[config.field_map["expected_amount"]].astype(float).round(2),
            "expected_event_count": df[config.field_map["expected_event_count"]].astype(int),
            "source_file": path.name,
        }
    )
    normalized.insert(
        0,
        "baseline_group_id",
        normalized["business_date"] + ":" + normalized["agent_context"] + ":" + normalized["session_id"].astype(str),
    )
    return normalized.loc[:, BASELINE_COLUMNS]


def build_baseline_comparison(
    ledger: pd.DataFrame,
    baseline: pd.DataFrame,
    baseline_config: BaselineConfig,
) -> pd.DataFrame:
    group_cols = ["business_date", "agent_context"]
    if "session_id" in baseline_config.field_map:
        group_cols.append("session_id")

    actual_summary = (
        ledger.groupby(group_cols, dropna=False)
        .agg(
            actual_amount=("amount", "sum"),
            actual_event_count=("event_id", "count"),
        )
        .reset_index()
    )

    comparison = baseline.merge(
        actual_summary,
        on=group_cols,
        how="outer",
    )
    comparison["source_system"] = comparison["source_system"].fillna(baseline_config.name)
    comparison["expected_amount"] = comparison["expected_amount"].fillna(0.0).astype(float).round(2)
    comparison["actual_amount"] = comparison["actual_amount"].fillna(0.0).astype(float).round(2)
    comparison["expected_event_count"] = (
        comparison["expected_event_count"].fillna(0).astype(int)
    )
    comparison["actual_event_count"] = (
        comparison["actual_event_count"].fillna(0).astype(int)
    )
    comparison["baseline_group_id"] = (
        comparison["business_date"].astype(str) + ":" + comparison["agent_context"].astype(str)
    )
    comparison["variance_amount"] = (
        comparison["actual_amount"] - comparison["expected_amount"]
    ).round(2)
    comparison["finding_count"] = comparison.apply(
        lambda row: len(_build_findings(row, baseline_config)),
        axis=1,
    )
    comparison = comparison.sort_values(
        ["business_date", "agent_context"], ascending=[False, True]
    ).reset_index(drop=True)
    return comparison.loc[:, BASELINE_COMPARISON_COLUMNS]


def build_baseline_discrepancies(
    comparison: pd.DataFrame,
    baseline_config: BaselineConfig,
) -> pd.DataFrame:
    findings: list[dict[str, object]] = []
    for row in comparison.to_dict(orient="records"):
        for discrepancy_type, recommended_action in _build_findings(pd.Series(row), baseline_config):
            findings.append(
                {
                    "record_type": "baseline",
                    "event_id": "",
                    "event_at": pd.NaT,
                    "business_date": row["business_date"],
                    "processor": "Cost Baseline",
                    "source_system": row["source_system"],
                    "agent_context": row["agent_context"],
                    "session_id": "",
                    "action_id": row["baseline_group_id"],
                    "action_type": "SUMMARY",
                    "amount": row["variance_amount"],
                    "action_status": "",
                    "auth_key": "",
                    "expected_amount": row["expected_amount"],
                    "actual_amount": row["actual_amount"],
                    "variance_amount": row["variance_amount"],
                    "expected_event_count": row["expected_event_count"],
                    "actual_event_count": row["actual_event_count"],
                    "discrepancy_type": discrepancy_type,
                    "diagnosis": "",
                    "recommended_action": recommended_action,
                }
            )

    if not findings:
        return pd.DataFrame(columns=DISCREPANCY_COLUMNS)

    discrepancies = pd.DataFrame(findings)
    discrepancies = discrepancies.sort_values(
        ["business_date", "agent_context", "discrepancy_type"],
        ascending=[False, True, True],
    ).reset_index(drop=True)
    return discrepancies.loc[:, DISCREPANCY_COLUMNS]


def _build_findings(
    row: pd.Series,
    baseline_config: BaselineConfig,
) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    has_baseline = row["expected_event_count"] > 0 or row["expected_amount"] != 0
    has_actual = row["actual_event_count"] > 0 or row["actual_amount"] != 0
    variance = float(row["variance_amount"])
    count_delta = int(row["actual_event_count"] - row["expected_event_count"])

    if has_actual and not has_baseline:
        findings.append(
            (
                "Missing cost baseline record",
                "Add or regenerate the cost baseline for this business date and agent context.",
            )
        )
    if has_baseline and not has_actual:
        findings.append(
            (
                "Missing agent activity",
                "Confirm whether the agent ran for this context on this date; data may be missing.",
            )
        )
    if has_baseline and has_actual and abs(variance) > baseline_config.amount_tolerance:
        if variance > 0:
            discrepancy_type = "Actual cost exceeds baseline"
        else:
            discrepancy_type = "Cost below baseline"
        findings.append(
            (
                discrepancy_type,
                f"Investigate the variance against {row['source_system']} and explain the delta before next billing cycle.",
            )
        )
    if has_baseline and has_actual and abs(count_delta) > baseline_config.count_tolerance:
        findings.append(
            (
                "Event count mismatch",
                f"Review event counts against {row['source_system']} for missing or duplicate action records.",
            )
        )
    return findings
