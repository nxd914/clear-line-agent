from pathlib import Path

from vequil.settings import load_baseline_config, load_processor_configs


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_load_processor_configs_reads_json_mappings() -> None:
    configs = load_processor_configs(PROJECT_ROOT / "configs" / "processors.json")

    assert [config.name for config in configs] == ["OpenClaw", "Claude", "LangChain", "OpenAI"]
    assert configs[0].column_map["agent_context"] == "Project"
    assert configs[1].column_map["auth_key"] == "Auth_Key_ID"


def test_load_baseline_config_reads_thresholds() -> None:
    config = load_baseline_config(PROJECT_ROOT / "configs" / "baseline.json")

    assert config.filename == "pos_expected_sales.csv"
    assert config.amount_tolerance == 5.0
    assert config.count_tolerance == 0
