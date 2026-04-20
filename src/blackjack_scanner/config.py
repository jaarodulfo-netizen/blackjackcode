"""Environment-driven configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class Config:
    decks: int = 6
    penetration: float = 0.75
    dealer_hits_soft_17: bool = False
    parser_name: str = "human"
    aws_mode: str = "stub"  # "stub" | "apigateway" | "dynamodb"
    aws_endpoint: str | None = None
    aws_table: str | None = None
    aws_region: str = "us-east-1"
    aws_api_key: str | None = None
    event_log: str = "./events.jsonl"

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            decks=_env_int("BJS_DECKS", 6),
            penetration=_env_float("BJS_PENETRATION", 0.75),
            dealer_hits_soft_17=_env_bool("BJS_DEALER_HITS_SOFT_17", False),
            parser_name=os.environ.get("BJS_PARSER", "human"),
            aws_mode=os.environ.get("BJS_AWS_MODE", "stub"),
            aws_endpoint=os.environ.get("BJS_AWS_ENDPOINT") or None,
            aws_table=os.environ.get("BJS_AWS_TABLE") or None,
            aws_region=os.environ.get("BJS_AWS_REGION", "us-east-1"),
            aws_api_key=os.environ.get("BJS_AWS_API_KEY") or None,
            event_log=os.environ.get("BJS_EVENT_LOG", "./events.jsonl"),
        )
