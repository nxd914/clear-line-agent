from __future__ import annotations

import pandas as pd

from .schema import DISCREPANCY_COLUMNS, REVIEWED_LEDGER_COLUMNS, SUCCESS_STATUSES


KNOWN_ACTION_TYPES = {
    "ACTION", "AGENT_RESPONSE", "CHAIN_STEP", "chat.completion",
    "tool_call", "tool_result", "browser", "shell", "edit", "read",
}

RULE_DEFINITIONS = (
    (
        "Failed action",
        "Review the agent run log and identify whether the failure is transient or requires intervention.",
        lambda ledger: ~ledger["action_status"].isin(SUCCESS_STATUSES),
    ),
    (
        "Missing auth key",
        "Verify the API key is set in the agent's environment and has not been rotated or revoked.",
        lambda ledger: ledger["auth_key"].astype(str).str.strip().eq(""),
    ),
    (
        "Anomalous action type",
        "Review this action type against known platform action types and confirm it is expected behavior.",
        lambda ledger: ~ledger["action_type"].isin(KNOWN_ACTION_TYPES),
    ),
    (
        "Duplicate action",
        "Check for duplicate export rows or runaway loop behavior in this session.",
        lambda ledger: ledger.duplicated(subset=["processor", "action_id"], keep=False),
    ),
    (
        "High-cost call",
        "Large single-call cost. Validate model selection and prompt length before next run.",
        lambda ledger: ledger["amount"].abs().ge(2.0),
    ),
)


def build_discrepancy_table(ledger: pd.DataFrame) -> pd.DataFrame:
    findings: list[pd.DataFrame] = []
    for rule_order, (discrepancy_type, recommended_action, mask_builder) in enumerate(
        RULE_DEFINITIONS
    ):
        mask = mask_builder(ledger)
        if not mask.any():
            continue
        finding_rows = ledger.loc[
            mask,
            [
                "event_id",
                "event_at",
                "business_date",
                "processor",
                "agent_context",
                "session_id",
                "action_id",
                "action_type",
                "amount",
                "action_status",
                "auth_key",
            ],
        ].copy()
        finding_rows["record_type"] = "event"
        finding_rows["rule_order"] = rule_order
        finding_rows["source_system"] = ""
        finding_rows["expected_amount"] = pd.NA
        finding_rows["actual_amount"] = pd.NA
        finding_rows["variance_amount"] = pd.NA
        finding_rows["expected_event_count"] = pd.NA
        finding_rows["actual_event_count"] = pd.NA
        finding_rows["discrepancy_type"] = discrepancy_type
        finding_rows["diagnosis"] = ""
        finding_rows["recommended_action"] = recommended_action
        findings.append(finding_rows)

    if not findings:
        return pd.DataFrame(columns=DISCREPANCY_COLUMNS)

    discrepancies = pd.concat(findings, ignore_index=True)
    discrepancies = discrepancies.sort_values(
        ["event_at", "processor", "action_id", "rule_order"],
        kind="mergesort",
    ).reset_index(drop=True)
    discrepancies = discrepancies.drop(columns=["rule_order"])
    return discrepancies.loc[:, DISCREPANCY_COLUMNS]


def build_reviewed_ledger(ledger: pd.DataFrame, discrepancies: pd.DataFrame) -> pd.DataFrame:
    reviewed = ledger.copy()
    if discrepancies.empty:
        reviewed["discrepancy_count"] = 0
        reviewed["discrepancy_types"] = ""
        reviewed["recommended_actions"] = ""
        return reviewed.loc[:, REVIEWED_LEDGER_COLUMNS]

    aggregated = (
        discrepancies.groupby("event_id", sort=False)
        .agg(
            discrepancy_count=("discrepancy_type", "count"),
            discrepancy_types=("discrepancy_type", _join_distinct),
            recommended_actions=("recommended_action", _join_distinct),
        )
        .reset_index()
    )
    reviewed = reviewed.merge(aggregated, on="event_id", how="left")
    reviewed["discrepancy_count"] = reviewed["discrepancy_count"].fillna(0).astype(int)
    reviewed["discrepancy_types"] = reviewed["discrepancy_types"].fillna("")
    reviewed["recommended_actions"] = reviewed["recommended_actions"].fillna("")
    return reviewed.loc[:, REVIEWED_LEDGER_COLUMNS]


def _join_distinct(values: pd.Series) -> str:
    ordered_unique = list(dict.fromkeys(values.tolist()))
    return " | ".join(ordered_unique)
