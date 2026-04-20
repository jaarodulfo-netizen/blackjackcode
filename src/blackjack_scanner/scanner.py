"""HID barcode scanner input.

Most USB/Bluetooth barcode scanners operate in "keyboard wedge" mode: each scan
is typed as a sequence of characters followed by Enter. Reading them is
therefore equivalent to reading lines from stdin.

``Scanner`` wraps a text stream and yields ``ScanEvent``s. The default stream
is ``sys.stdin``. Tests and automation can pass an ``io.StringIO`` instead.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import IO

from .card import BarcodeError, BarcodeParser, Card


@dataclass(frozen=True, slots=True)
class ScanEvent:
    raw: str
    card: Card | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.card is not None


class Scanner:
    def __init__(self, parser: BarcodeParser, stream: IO[str] | None = None) -> None:
        self._parser = parser
        self._stream: IO[str] = stream if stream is not None else sys.stdin

    def read_line(self) -> str | None:
        """Blocking read of a single line. Returns ``None`` at EOF."""
        line = self._stream.readline()
        if line == "":
            return None
        return line.rstrip("\r\n")

    def scan(self) -> ScanEvent | None:
        """Read one scan and parse it into a card. Returns ``None`` at EOF."""
        line = self.read_line()
        if line is None:
            return None
        return parse_line(line, self._parser)

    def __iter__(self) -> Iterator[ScanEvent]:
        while True:
            event = self.scan()
            if event is None:
                return
            yield event


def parse_line(line: str, parser: BarcodeParser) -> ScanEvent:
    stripped = line.strip()
    if not stripped:
        return ScanEvent(raw=line, card=None, error="empty scan")
    try:
        card = parser.parse(stripped)
    except BarcodeError as exc:
        return ScanEvent(raw=line, card=None, error=str(exc))
    return ScanEvent(raw=line, card=card)


def iter_lines(lines: Iterable[str], parser: BarcodeParser) -> Iterator[ScanEvent]:
    """Helper for tests: turn an iterable of strings into ``ScanEvent``s."""
    for line in lines:
        yield parse_line(line, parser)
