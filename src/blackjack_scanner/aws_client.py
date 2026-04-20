"""AWS event sinks.

The default ``StubEventSink`` appends JSON lines to a local file so the game is
fully functional without AWS. ``ApiGatewayEventSink`` POSTs to a REST/HTTP API
endpoint (no boto3 required — uses stdlib ``urllib``). ``DynamoDBEventSink``
writes events directly to a table and requires ``boto3`` (installed via the
``aws`` extra).

All sinks implement the ``EventSink`` protocol so swapping implementations is a
one-line change in ``config.py``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from urllib import request as urlrequest
from urllib.error import URLError

logger = logging.getLogger(__name__)


@runtime_checkable
class EventSink(Protocol):
    """Anything that can accept structured events. ``close`` is optional but
    must be a no-op if not needed."""

    def emit(self, event: dict[str, Any]) -> None: ...

    def close(self) -> None: ...


class StubEventSink:
    """Appends events as JSON lines to a local file. Default sink when AWS is
    not configured. Flushes after every write so a crash doesn't lose events."""

    def __init__(self, path: str | Path = "events.jsonl") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Open in append mode; keep the handle for the lifetime of the sink.
        self._fh = self._path.open("a", encoding="utf-8")

    def emit(self, event: dict[str, Any]) -> None:
        self._fh.write(json.dumps(event, separators=(",", ":")) + "\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:  # pragma: no cover - best effort
            logger.exception("error closing stub event sink")


class ApiGatewayEventSink:
    """POSTs events to an API Gateway HTTP/REST endpoint using stdlib urllib.

    A single-event-per-request client is fine for a casino-table-rate workload
    (a few events per second at most). For higher throughput, batch with SQS
    or Kinesis.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        api_key: str | None = None,
        timeout: float = 5.0,
    ) -> None:
        if not endpoint:
            raise ValueError("ApiGatewayEventSink requires a non-empty endpoint URL")
        self._endpoint = endpoint
        self._api_key = api_key
        self._timeout = timeout

    def emit(self, event: dict[str, Any]) -> None:
        body = json.dumps(event, separators=(",", ":")).encode("utf-8")
        req = urlrequest.Request(
            self._endpoint,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        if self._api_key:
            req.add_header("x-api-key", self._api_key)
        try:
            with urlrequest.urlopen(req, timeout=self._timeout) as resp:
                # Drain body so the connection can be pooled.
                resp.read()
        except URLError as exc:
            logger.warning("failed to POST event to %s: %s", self._endpoint, exc)

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


class DynamoDBEventSink:
    """Writes events to a DynamoDB table. Requires boto3.

    Schema assumption: the table has a composite key ``(session_id, ts)`` where
    ``session_id`` is the partition key (string) and ``ts`` is the sort key
    (number). Adjust ``_to_item`` if your schema differs.
    """

    def __init__(self, table_name: str, *, region: str = "us-east-1") -> None:
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ImportError(
                "DynamoDBEventSink requires boto3 — install with `pip install .[aws]`"
            ) from exc
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def emit(self, event: dict[str, Any]) -> None:  # pragma: no cover - requires boto3
        self._table.put_item(Item=self._to_item(event))

    @staticmethod
    def _to_item(event: dict[str, Any]) -> dict[str, Any]:
        # DynamoDB doesn't accept floats; convert to Decimal-friendly strings.
        return {
            "session_id": event["session_id"],
            "ts": str(event["ts"]),
            "type": event["type"],
            "payload": json.dumps(event["payload"]),
        }

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass
