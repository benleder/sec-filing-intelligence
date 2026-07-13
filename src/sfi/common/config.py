"""Paths, .env loading, and project-wide constants. L0 — stdlib only."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
MANIFEST_DIR = DATA_DIR / "manifest"
MANIFEST_PATH = MANIFEST_DIR / "manifest.json"
STORE_DIR = DATA_DIR / "store"
DB_PATH = STORE_DIR / "facts.sqlite"
EDGAR_LOG_PATH = DATA_DIR / "edgar_log.jsonl"
NOTES_DIR = ROOT / "notes"
BENCH_DIR = ROOT / "benchmark"

# J1: one model for all three LLM roles; verified against Anthropic docs
# 2026-07-12 ($5/$25 per MTok, structured outputs supported).
MODEL = "claude-opus-4-8"
SEC_USER_AGENT = "sec-filing-intelligence lederbenjamin@gmail.com"
TICKERS = ("TSLA", "AAPL")


class ConfigError(Exception):
    pass


def load_env(path: Path | None = None) -> dict[str, str]:
    """Tiny .env parser (rule 15: stdlib-first — the file is KEY=value lines)."""
    path = ROOT / ".env" if path is None else path
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip("'\"")
    return env


def api_key(path: Path | None = None) -> str:
    key = load_env(path).get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ConfigError("ANTHROPIC_API_KEY missing from .env")
    return key


def ensure_dirs() -> None:
    for d in (DATA_DIR, RAW_DIR, MANIFEST_DIR, STORE_DIR, NOTES_DIR):
        d.mkdir(parents=True, exist_ok=True)
