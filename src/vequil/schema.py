from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd


Normalizer = Callable[[Path], pd.DataFrame]


LEDGER_COLUMNS = [
    "event_id",
    "event_at",
    "business_date",
    "processor",
    "agent_context",
    "session_id",
    "action_id",
    "auth_key",
    "model_id",
    "action_type",
    "amount",
    "action_status",
    "deployment_id",
    "source_file",
]

BASELINE_COLUMNS = [
    "baseline_group_id",
    "business_date",
    "source_system",
    "agent_context",
    "expected_amount",
    "expected_event_count",
    "source_file",
]

BASELINE_COMPARISON_COLUMNS = [
    "baseline_group_id",
    "business_date",
    "source_system",
    "agent_context",
    "expected_amount",
    "actual_amount",
    "variance_amount",
    "expected_event_count",
    "actual_event_count",
    "finding_count",
]

REVIEWED_LEDGER_COLUMNS = LEDGER_COLUMNS + [
    "discrepancy_count",
    "discrepancy_types",
    "recommended_actions",
]

DISCREPANCY_COLUMNS = [
    "record_type",
    "event_id",
    "event_at",
    "business_date",
    "processor",
    "source_system",
    "agent_context",
    "session_id",
    "action_id",
    "action_type",
    "amount",
    "action_status",
    "auth_key",
    "expected_amount",
    "actual_amount",
    "variance_amount",
    "expected_event_count",
    "actual_event_count",
    "discrepancy_type",
    "diagnosis",
    "recommended_action",
]

RECENT_ACTIVITY_COLUMNS = [
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
    "discrepancy_count",
    "discrepancy_types",
    "recommended_actions",
]

SUCCESS_STATUSES = {"COMPLETED", "SUCCESS", "DONE", "200", "OK", "RESOLVED"}


@dataclass(frozen=True)
class ProcessorSpec:
    name: str
    filename: str
    required_columns: tuple[str, ...]
    normalizer: Normalizer
