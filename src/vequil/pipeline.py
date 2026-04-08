from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

import requests
from .config import OUTPUT_DIR, RAW_DATA_DIR, SLACK_WEBHOOK_URL
from .baseline import (
    build_baseline_comparison,
    build_baseline_discrepancies,
    load_baseline,
)
from .notifier import notifier
from .normalizers import generate_unified_ledger
from .rules import build_discrepancy_table, build_reviewed_ledger
from .schema import BASELINE_COMPARISON_COLUMNS, DISCREPANCY_COLUMNS, RECENT_ACTIVITY_COLUMNS
from .settings import load_baseline_config


@dataclass(frozen=True)
class PipelineArtifacts:
    ledger_path: Path
    discrepancy_path: Path
    comparison_path: Path
    dashboard_path: Path
    report_path: Path


def build_dashboard_payload(
    reviewed: pd.DataFrame,
    discrepancies: pd.DataFrame,
    baseline_comparison: pd.DataFrame,
) -> dict:
    flagged_events = reviewed["discrepancy_count"].gt(0)
    total_volume = float(reviewed["amount"].sum())
    cleared_volume = float(reviewed.loc[~flagged_events, "amount"].sum())
    at_risk_volume = float(reviewed.loc[flagged_events, "amount"].sum())
    baseline_volume = float(baseline_comparison["expected_amount"].sum())
    expected_variance = float(baseline_comparison["variance_amount"].sum())
    metrics = {
        "total_events": int(len(reviewed)),
        "flagged_events": int(flagged_events.sum()),
        "total_findings": int(len(discrepancies)),
        "total_volume": round(total_volume, 2),
        "cleared_volume": round(cleared_volume, 2),
        "at_risk_volume": round(at_risk_volume, 2),
        "baseline_volume": round(baseline_volume, 2),
        "net_variance": round(expected_variance, 2),
    }

    processor_summary = (
        reviewed.groupby("processor", dropna=False)
        .agg(
            events=("action_id", "count"),
            total_amount=("amount", "sum"),
            flagged_events=("discrepancy_count", lambda s: int((s > 0).sum())),
        )
        .reset_index()
    )
    findings_by_processor = (
        discrepancies.groupby("processor", dropna=False)
        .agg(findings=("event_id", "count"))
        .reset_index()
    )
    processor_summary = processor_summary.merge(
        findings_by_processor, on="processor", how="left"
    )
    processor_summary["findings"] = processor_summary["findings"].fillna(0).astype(int)

    discrepancy_summary = (
        discrepancies.groupby("discrepancy_type", dropna=False)
        .agg(
            count=("event_id", "count"),
            total_amount=("amount", "sum"),
        )
        .reset_index()
        .sort_values(["count", "total_amount"], ascending=[False, False])
    )

    baseline_variance_summary = baseline_comparison.loc[
        baseline_comparison["finding_count"].gt(0),
        BASELINE_COMPARISON_COLUMNS,
    ].copy()
    baseline_variance_summary = baseline_variance_summary.sort_values(
        ["finding_count", "variance_amount"],
        ascending=[False, False],
        key=lambda series: series.abs() if series.name == "variance_amount" else series,
    ).head(8)

    recent = reviewed.sort_values("event_at", ascending=False).head(12)
    discrepancy_rows = _serialize_records(
        discrepancies.sort_values(
            ["business_date", "record_type", "event_at", "action_id"],
            ascending=[False, True, False, True],
            na_position="last",
        )[DISCREPANCY_COLUMNS]
    )
    recent = _serialize_records(recent[RECENT_ACTIVITY_COLUMNS])
    payload = {
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "metrics": metrics,
        "processor_summary": processor_summary.to_dict(orient="records"),
        "discrepancy_summary": discrepancy_summary.to_dict(orient="records"),
        "baseline_variance_summary": _serialize_records(baseline_variance_summary),
        "discrepancies": discrepancy_rows,
        "recent_activity": recent,
    }
    return payload


def _serialize_records(df: pd.DataFrame) -> list[dict]:
    serializable = df.copy()
    for column in serializable.columns:
        if pd.api.types.is_datetime64_any_dtype(serializable[column]):
            serializable[column] = serializable[column].dt.strftime("%Y-%m-%d %H:%M:%S")
    serializable = serializable.fillna("")
    return serializable.to_dict(orient="records")


def run_pipeline(
    raw_data_dir: Path = RAW_DATA_DIR,
    output_dir: Path = OUTPUT_DIR,
    event_id: str | None = None
) -> PipelineArtifacts:
    if event_id:
        output_dir = output_dir / "events" / event_id

    output_dir.mkdir(parents=True, exist_ok=True)
    ledger = generate_unified_ledger(raw_data_dir=raw_data_dir)
    event_discrepancies = build_discrepancy_table(ledger)
    reviewed = build_reviewed_ledger(ledger, event_discrepancies)

    baseline_config = load_baseline_config()
    baseline = load_baseline(raw_data_dir=raw_data_dir, baseline_config=baseline_config)
    baseline_comparison = build_baseline_comparison(ledger, baseline, baseline_config)
    baseline_discrepancies = build_baseline_discrepancies(baseline_comparison, baseline_config)

    discrepancies = pd.concat(
        [event_discrepancies, baseline_discrepancies], ignore_index=True
    )
    from .agent import diagnose_discrepancies
    discrepancies = diagnose_discrepancies(discrepancies)
    dashboard = build_dashboard_payload(reviewed, discrepancies, baseline_comparison)

    report_path = output_dir / "agent_audit_report.xlsx"
    _write_excel_report(reviewed, discrepancies, baseline_comparison, report_path)

    net_variance = dashboard["metrics"]["net_variance"]
    notifier.notify_variance_alert(
        event_id=event_id,
        amount=net_variance,
        count=len(discrepancies)
    )

    ledger_path = output_dir / "unified_ledger.csv"
    discrepancy_path = output_dir / "discrepancies.csv"
    comparison_path = output_dir / "baseline_comparison.csv"
    dashboard_path = output_dir / "dashboard.json"

    reviewed.to_csv(ledger_path, index=False)
    discrepancies.to_csv(discrepancy_path, index=False)
    baseline_comparison.to_csv(comparison_path, index=False)
    dashboard_path.write_text(json.dumps(dashboard, indent=2), encoding="utf-8")

    return PipelineArtifacts(
        ledger_path=ledger_path,
        discrepancy_path=discrepancy_path,
        comparison_path=comparison_path,
        dashboard_path=dashboard_path,
        report_path=report_path,
    )


def _write_excel_report(
    reviewed: pd.DataFrame,
    discrepancies: pd.DataFrame,
    baseline_comparison: pd.DataFrame,
    path: Path,
) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary_data = {
            "Metric": [
                "Total Events",
                "Flagged Events",
                "Total Finding Count",
                "Total Cost Volume",
                "At-Risk Volume",
                "Net Baseline Variance",
            ],
            "Value": [
                len(reviewed),
                int(reviewed["discrepancy_count"].gt(0).sum()),
                len(discrepancies),
                reviewed["amount"].sum(),
                reviewed.loc[reviewed["discrepancy_count"].gt(0), "amount"].sum(),
                baseline_comparison["variance_amount"].sum(),
            ],
        }
        pd.DataFrame(summary_data).to_excel(writer, sheet_name="Summary", index=False)

        exceptions = discrepancies.sort_values(
            ["business_date", "event_at"], ascending=False
        )
        exceptions.to_excel(writer, sheet_name="Anomalies", index=False)

        reviewed.to_excel(writer, sheet_name="Unified Ledger", index=False)

        workbook = writer.book
        for sheetname in workbook.sheetnames:
            worksheet = workbook[sheetname]
            for col in worksheet.columns:
                max_length = 0
                column = col[0].column_letter
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except Exception:
                        pass
                worksheet.column_dimensions[column].width = min(max_length + 2, 60)


if __name__ == "__main__":
    artifacts = run_pipeline()
    print(f"Wrote {artifacts.ledger_path}")
    print(f"Wrote {artifacts.discrepancy_path}")
    print(f"Wrote {artifacts.comparison_path}")
    print(f"Wrote {artifacts.dashboard_path}")
