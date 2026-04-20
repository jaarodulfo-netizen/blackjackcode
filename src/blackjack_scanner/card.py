"""Card, rank, suit models and barcode parsing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Suit(Enum):
    SPADES = "S"
    HEARTS = "H"
    DIAMONDS = "D"
    CLUBS = "C"

    @property
    def glyph(self) -> str:
        return {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}[self.value]


class Rank(Enum):
    ACE = "A"
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"
    SIX = "6"
    SEVEN = "7"
    EIGHT = "8"
    NINE = "9"
    TEN = "T"
    JACK = "J"
    QUEEN = "Q"
    KING = "K"

    @property
    def blackjack_values(self) -> tuple[int, ...]:
        """Possible numeric values for this rank in blackjack."""
        if self is Rank.ACE:
            return (1, 11)
        if self in (Rank.TEN, Rank.JACK, Rank.QUEEN, Rank.KING):
            return (10,)
        return (int(self.value),)

    @property
    def is_face(self) -> bool:
        return self in (Rank.JACK, Rank.QUEEN, Rank.KING)

    @property
    def is_ten_valued(self) -> bool:
        return self in (Rank.TEN, Rank.JACK, Rank.QUEEN, Rank.KING)


_RANK_FROM_CHAR: dict[str, Rank] = {r.value: r for r in Rank}
# Accept "10" as alias for "T".
_RANK_ALIASES: dict[str, Rank] = {"10": Rank.TEN, "1": Rank.ACE}
_SUIT_FROM_CHAR: dict[str, Suit] = {s.value: s for s in Suit}


@dataclass(frozen=True, slots=True)
class Card:
    rank: Rank
    suit: Suit
    # Optional provenance fields that a real casino-grade scanner may report.
    deck_id: int | None = None
    raw_barcode: str | None = None

    def __str__(self) -> str:
        return f"{self.rank.value}{self.suit.glyph}"

    @property
    def short(self) -> str:
        """Canonical two-char form, e.g. "AS", "TH", "KC"."""
        return f"{self.rank.value}{self.suit.value}"


class BarcodeError(ValueError):
    """Raised when a barcode payload cannot be interpreted as a card."""


class BarcodeParser:
    """Base class for barcode → Card parsers."""

    name: str = "base"

    def parse(self, payload: str) -> Card:  # pragma: no cover - abstract
        raise NotImplementedError


class HumanBarcodeParser(BarcodeParser):
    """Parser for human-readable barcodes like ``AS``, ``10H``, ``KC``.

    Accepts uppercase or lowercase, optional whitespace, and the literal ``10``
    as an alias for the ten. Ignores any leading/trailing non-alphanumeric chars
    so a scanner suffix (e.g. CR/LF) does not break parsing.
    """

    name = "human"

    def parse(self, payload: str) -> Card:
        cleaned = "".join(ch for ch in payload.strip().upper() if ch.isalnum())
        if not cleaned:
            raise BarcodeError(f"empty barcode: {payload!r}")

        # Split rank (which may be "10") from suit (last char).
        suit_char = cleaned[-1]
        rank_part = cleaned[:-1]

        if suit_char not in _SUIT_FROM_CHAR:
            raise BarcodeError(f"unknown suit {suit_char!r} in {payload!r}")
        suit = _SUIT_FROM_CHAR[suit_char]

        if rank_part in _RANK_FROM_CHAR:
            rank = _RANK_FROM_CHAR[rank_part]
        elif rank_part in _RANK_ALIASES:
            rank = _RANK_ALIASES[rank_part]
        else:
            raise BarcodeError(f"unknown rank {rank_part!r} in {payload!r}")

        return Card(rank=rank, suit=suit, raw_barcode=payload)


# Numeric scheme: RRSD[...]
# RR = rank 01..13 (Ace=01, Two=02, ..., King=13)
# S  = suit 1..4 (1=Spades, 2=Hearts, 3=Diamonds, 4=Clubs)
# D  = deck id (0..9), optional and tolerated if absent.
# Any additional digits (checksum/whatever) are ignored.
# Example: "0111" = Ace of Spades, deck 1.
_NUMERIC_RANKS: dict[int, Rank] = {
    1: Rank.ACE,
    2: Rank.TWO,
    3: Rank.THREE,
    4: Rank.FOUR,
    5: Rank.FIVE,
    6: Rank.SIX,
    7: Rank.SEVEN,
    8: Rank.EIGHT,
    9: Rank.NINE,
    10: Rank.TEN,
    11: Rank.JACK,
    12: Rank.QUEEN,
    13: Rank.KING,
}
_NUMERIC_SUITS: dict[int, Suit] = {
    1: Suit.SPADES,
    2: Suit.HEARTS,
    3: Suit.DIAMONDS,
    4: Suit.CLUBS,
}


class NumericBarcodeParser(BarcodeParser):
    """Parser for numeric barcodes like ``0111`` (Ace of Spades, deck 1)."""

    name = "numeric"

    def parse(self, payload: str) -> Card:
        digits = "".join(ch for ch in payload.strip() if ch.isdigit())
        if len(digits) < 3:
            raise BarcodeError(f"numeric barcode too short: {payload!r}")
        try:
            rank_num = int(digits[0:2])
            suit_num = int(digits[2])
        except ValueError as exc:  # pragma: no cover - digits-only guarded above
            raise BarcodeError(f"non-numeric barcode: {payload!r}") from exc

        if rank_num not in _NUMERIC_RANKS:
            raise BarcodeError(f"unknown rank {rank_num} in {payload!r}")
        if suit_num not in _NUMERIC_SUITS:
            raise BarcodeError(f"unknown suit {suit_num} in {payload!r}")

        deck_id: int | None = int(digits[3]) if len(digits) >= 4 else None

        return Card(
            rank=_NUMERIC_RANKS[rank_num],
            suit=_NUMERIC_SUITS[suit_num],
            deck_id=deck_id,
            raw_barcode=payload,
        )


_PARSERS: dict[str, type[BarcodeParser]] = {
    HumanBarcodeParser.name: HumanBarcodeParser,
    NumericBarcodeParser.name: NumericBarcodeParser,
}


def get_parser(name: str) -> BarcodeParser:
    """Look up a parser by name. Raises KeyError if unknown."""
    try:
        cls = _PARSERS[name]
    except KeyError as exc:
        known = ", ".join(sorted(_PARSERS))
        raise KeyError(f"unknown parser {name!r}; known: {known}") from exc
    return cls()
