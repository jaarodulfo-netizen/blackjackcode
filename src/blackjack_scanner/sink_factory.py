"""Factory that builds the configured ``EventSink`` from a ``Config``."""

from __future__ import annotations

from .aws_client import ApiGatewayEventSink, DynamoDBEventSink, EventSink, StubEventSink
from .config import Config


def build_sink(config: Config) -> EventSink:
    mode = config.aws_mode.lower()
    if mode == "stub":
        return StubEventSink(config.event_log)
    if mode == "apigateway":
        if not config.aws_endpoint:
            raise ValueError("BJS_AWS_MODE=apigateway requires BJS_AWS_ENDPOINT")
        return ApiGatewayEventSink(config.aws_endpoint, api_key=config.aws_api_key)
    if mode == "dynamodb":
        if not config.aws_table:
            raise ValueError("BJS_AWS_MODE=dynamodb requires BJS_AWS_TABLE")
        return DynamoDBEventSink(config.aws_table, region=config.aws_region)
    raise ValueError(f"unknown BJS_AWS_MODE: {config.aws_mode!r}")
