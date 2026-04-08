import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
except ImportError:
    pass  # python-dotenv not installed — rely on environment variables


ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "configs"
DATA_DIR = ROOT / "data"
RAW_DATA_DIR = ROOT / "data" / "raw"
OUTPUT_DIR = ROOT / "data" / "output"
WEB_DIR = ROOT / "web" / "static"

PROCESSORS_CONFIG_PATH = CONFIG_DIR / "processors.json"
BASELINE_CONFIG_PATH = CONFIG_DIR / "baseline.json"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
