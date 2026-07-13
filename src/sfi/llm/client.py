"""Thin Anthropic wrapper: structured-output call, retries, usage log.
L1 — imports common only (plus the anthropic SDK).

Every call appends one line to data/llm_usage.jsonl (tokens in/out, purpose)
so total spend is auditable against the J1 estimate.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from ..common import config

USAGE_LOG_PATH = config.DATA_DIR / "llm_usage.jsonl"


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        log_path: Path | None = None,
    ):
        self.model = model or config.MODEL
        self.log_path = USAGE_LOG_PATH if log_path is None else log_path
        self._client = anthropic.Anthropic(api_key=api_key or config.api_key())

    def structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict,
        purpose: str,
        max_tokens: int = 16000,
    ) -> dict:
        """One structured-outputs call; the API guarantees schema-valid JSON,
        so parsing the reply is never string-munging."""
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        self._log_usage(purpose, response)
        if response.stop_reason == "refusal":
            raise LLMError(f"{purpose}: model refused")
        if response.stop_reason == "max_tokens":
            raise LLMError(f"{purpose}: output truncated at {max_tokens} tokens")
        text = "".join(b.text for b in response.content if b.type == "text")
        return json.loads(text)

    def _log_usage(self, purpose: str, response) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": self.model,
            "purpose": purpose,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "stop_reason": response.stop_reason,
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
