from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import BASELINE_CONFIG_PATH, PROCESSORS_CONFIG_PATH


@dataclass(frozen=True)
class ProcessorConfig:
    name: str
    filename: str
    timestamp_columns: tuple[str, ...]
    source_timezone: str | None
    target_timezone: str | None
    column_map: dict[str, str]
    constants: dict[str, str]
    date_format: str | None = None
    amount_format: str | None = None

    @property
    def required_columns(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys([*self.timestamp_columns, *self.column_map.values()]))


@dataclass(frozen=True)
class BaselineConfig:
    name: str
    filename: str
    field_map: dict[str, str]
    amount_tolerance: float
    count_tolerance: int

    @property
    def required_columns(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.field_map.values()))


def load_processor_configs(path: Path = PROCESSORS_CONFIG_PATH) -> tuple[ProcessorConfig, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        ProcessorConfig(
            name=item["name"],
            filename=item["filename"],
            timestamp_columns=tuple(item["timestamp_columns"]),
            source_timezone=item.get("source_timezone"),
            target_timezone=item.get("target_timezone"),
            column_map=dict(item["column_map"]),
            constants=dict(item.get("constants", {})),
            date_format=item.get("date_format"),
            amount_format=item.get("amount_format"),
        )
        for item in payload["processors"]
    )


def get_processor_config(name: str, path: Path = PROCESSORS_CONFIG_PATH) -> ProcessorConfig:
    for config in load_processor_configs(path):
        if config.name == name:
            return config
    raise KeyError(f"Unknown processor config: {name}")


def load_baseline_config(path: Path = BASELINE_CONFIG_PATH) -> BaselineConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return BaselineConfig(
        name=payload["name"],
        filename=payload["filename"],
        field_map=dict(payload["field_map"]),
        amount_tolerance=float(payload.get("amount_tolerance", 0.0)),
        count_tolerance=int(payload.get("count_tolerance", 0)),
    )
