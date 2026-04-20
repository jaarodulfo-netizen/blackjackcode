from __future__ import annotations

import json
from pathlib import Path

import pytest

from blackjack_scanner.aws_client import (
    ApiGatewayEventSink,
    EventSink,
    StubEventSink,
)
from blackjack_scanner.config import Config
from blackjack_scanner.events import event
from blackjack_scanner.sink_factory import build_sink


def test_stub_sink_writes_jsonl(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    sink = StubEventSink(p)
    sink.emit(event("test.a", "sess", {"x": 1}))
    sink.emit(event("test.b", "sess", {"x": 2}))
    sink.close()
    lines = p.read_text().strip().splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["type"] == "test.a"
    assert parsed[0]["payload"] == {"x": 1}
    assert parsed[1]["type"] == "test.b"


def test_stub_sink_creates_parent_dir(tmp_path: Path) -> None:
    p = tmp_path / "nested" / "dir" / "events.jsonl"
    sink = StubEventSink(p)
    sink.emit(event("t", "s", {}))
    sink.close()
    assert p.exists()


def test_api_gateway_requires_endpoint() -> None:
    with pytest.raises(ValueError):
        ApiGatewayEventSink("")


def test_sink_factory_stub(tmp_path: Path) -> None:
    cfg = Config(aws_mode="stub", event_log=str(tmp_path / "e.jsonl"))
    sink = build_sink(cfg)
    assert isinstance(sink, EventSink)
    sink.close()


def test_sink_factory_apigateway_requires_endpoint() -> None:
    cfg = Config(aws_mode="apigateway", aws_endpoint=None)
    with pytest.raises(ValueError):
        build_sink(cfg)


def test_sink_factory_dynamodb_requires_table() -> None:
    cfg = Config(aws_mode="dynamodb", aws_table=None)
    with pytest.raises(ValueError):
        build_sink(cfg)


def test_sink_factory_unknown_mode() -> None:
    cfg = Config(aws_mode="lolwat")
    with pytest.raises(ValueError):
        build_sink(cfg)
