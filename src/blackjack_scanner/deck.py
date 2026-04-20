"""Shoe / multi-deck tracking. Not used for simulated dealing (cards come from a
physical scanner) but useful for penetration, reshuffle prompts, and count-based
analytics that can be emitted to AWS."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .card import Card, Rank


@dataclass
class Shoe:
    """Tracks cards that have been dealt from a physical multi-deck shoe.

    The shoe does not *produce* cards — a real barcode scanner does. Instead it
    records every card that was scanned so we can compute penetration, a running
    Hi-Lo count, and detect reshuffle time.
    """

    decks: int = 6
    penetration: float = 0.75
    _dealt: Counter[str] = field(default_factory=Counter)
    _order: list[Card] = field(default_factory=list)

    @property
    def total_cards(self) -> int:
        return self.decks * 52

    @property
    def dealt_count(self) -> int:
        return len(self._order)

    @property
    def remaining(self) -> int:
        return max(self.total_cards - self.dealt_count, 0)

    @property
    def penetration_reached(self) -> bool:
        return self.dealt_count >= int(self.total_cards * self.penetration)

    def record(self, card: Card) -> None:
        self._dealt[card.short] += 1
        self._order.append(card)

    def reset(self) -> None:
        self._dealt.clear()
        self._order.clear()

    def running_count(self) -> int:
        """Standard Hi-Lo running count across everything dealt so far."""
        total = 0
        for short, n in self._dealt.items():
            rank_char = short[0]
            total += _hi_lo_value(rank_char) * n
        return total

    def true_count(self) -> float:
        decks_remaining = max(self.remaining / 52.0, 0.5)
        return round(self.running_count() / decks_remaining, 2)


def _hi_lo_value(rank_char: str) -> int:
    if rank_char in {"2", "3", "4", "5", "6"}:
        return 1
    if rank_char in {"7", "8", "9"}:
        return 0
    # T, J, Q, K, A
    if rank_char in {Rank.TEN.value, Rank.JACK.value, Rank.QUEEN.value, Rank.KING.value, Rank.ACE.value}:
        return -1
    return 0
