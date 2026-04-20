"""Basic strategy recommendations for multi-deck blackjack.

Tables are the canonical basic-strategy charts for 4/6/8 decks, dealer stands
on soft 17 (S17) or hits soft 17 (H17), double after split allowed, late
surrender allowed. They are intentionally written out in full so they're easy
to audit rather than derived from a compressed encoding.
"""

from __future__ import annotations

from .card import Card, Rank
from .game import Action, Hand

# Dealer upcard numeric values used for chart lookup. Ace is represented as 11.
_DealerKey = int  # 2..11


def _dealer_key(card: Card) -> _DealerKey:
    if card.rank is Rank.ACE:
        return 11
    if card.rank.is_ten_valued:
        return 10
    return card.rank.blackjack_values[0]


# Key letters:
#   H  = hit
#   S  = stand
#   D  = double if allowed else hit
#   Ds = double if allowed else stand (only used for soft hands)
#   P  = split
#   Ph = split if double-after-split allowed, else hit (only used for pair of 2s/3s/6s/7s at some totals)
#   R  = surrender if allowed else hit
#   Rs = surrender if allowed else stand

# Hard totals 5..21, dealer up 2..11.
_HARD: dict[int, dict[int, str]] = {
    5:  {2: "H", 3: "H", 4: "H", 5: "H", 6: "H", 7: "H", 8: "H", 9: "H", 10: "H", 11: "H"},
    6:  {2: "H", 3: "H", 4: "H", 5: "H", 6: "H", 7: "H", 8: "H", 9: "H", 10: "H", 11: "H"},
    7:  {2: "H", 3: "H", 4: "H", 5: "H", 6: "H", 7: "H", 8: "H", 9: "H", 10: "H", 11: "H"},
    8:  {2: "H", 3: "H", 4: "H", 5: "H", 6: "H", 7: "H", 8: "H", 9: "H", 10: "H", 11: "H"},
    9:  {2: "H", 3: "D", 4: "D", 5: "D", 6: "D", 7: "H", 8: "H", 9: "H", 10: "H", 11: "H"},
    10: {2: "D", 3: "D", 4: "D", 5: "D", 6: "D", 7: "D", 8: "D", 9: "D", 10: "H", 11: "H"},
    11: {2: "D", 3: "D", 4: "D", 5: "D", 6: "D", 7: "D", 8: "D", 9: "D", 10: "D", 11: "D"},
    12: {2: "H", 3: "H", 4: "S", 5: "S", 6: "S", 7: "H", 8: "H", 9: "H", 10: "H", 11: "H"},
    13: {2: "S", 3: "S", 4: "S", 5: "S", 6: "S", 7: "H", 8: "H", 9: "H", 10: "H", 11: "H"},
    14: {2: "S", 3: "S", 4: "S", 5: "S", 6: "S", 7: "H", 8: "H", 9: "H", 10: "H", 11: "H"},
    15: {2: "S", 3: "S", 4: "S", 5: "S", 6: "S", 7: "H", 8: "H", 9: "H", 10: "R", 11: "R"},
    16: {2: "S", 3: "S", 4: "S", 5: "S", 6: "S", 7: "H", 8: "H", 9: "R", 10: "R", 11: "R"},
    17: {2: "S", 3: "S", 4: "S", 5: "S", 6: "S", 7: "S", 8: "S", 9: "S", 10: "S", 11: "Rs"},
    18: {2: "S", 3: "S", 4: "S", 5: "S", 6: "S", 7: "S", 8: "S", 9: "S", 10: "S", 11: "S"},
    19: {2: "S", 3: "S", 4: "S", 5: "S", 6: "S", 7: "S", 8: "S", 9: "S", 10: "S", 11: "S"},
    20: {2: "S", 3: "S", 4: "S", 5: "S", 6: "S", 7: "S", 8: "S", 9: "S", 10: "S", 11: "S"},
    21: {2: "S", 3: "S", 4: "S", 5: "S", 6: "S", 7: "S", 8: "S", 9: "S", 10: "S", 11: "S"},
}

# Soft totals (one ace counted as 11). Key is the *full* hand total (A+x => 11+x).
# Soft 13 = A,2 ... Soft 20 = A,9.
_SOFT: dict[int, dict[int, str]] = {
    13: {2: "H",  3: "H",  4: "H",  5: "D",  6: "D",  7: "H", 8: "H", 9: "H", 10: "H", 11: "H"},
    14: {2: "H",  3: "H",  4: "H",  5: "D",  6: "D",  7: "H", 8: "H", 9: "H", 10: "H", 11: "H"},
    15: {2: "H",  3: "H",  4: "D",  5: "D",  6: "D",  7: "H", 8: "H", 9: "H", 10: "H", 11: "H"},
    16: {2: "H",  3: "H",  4: "D",  5: "D",  6: "D",  7: "H", 8: "H", 9: "H", 10: "H", 11: "H"},
    17: {2: "H",  3: "D",  4: "D",  5: "D",  6: "D",  7: "H", 8: "H", 9: "H", 10: "H", 11: "H"},
    18: {2: "Ds", 3: "Ds", 4: "Ds", 5: "Ds", 6: "Ds", 7: "S", 8: "S", 9: "H", 10: "H", 11: "H"},
    19: {2: "S",  3: "S",  4: "S",  5: "S",  6: "S",  7: "S", 8: "S", 9: "S", 10: "S", 11: "S"},
    20: {2: "S",  3: "S",  4: "S",  5: "S",  6: "S",  7: "S", 8: "S", 9: "S", 10: "S", 11: "S"},
    21: {2: "S",  3: "S",  4: "S",  5: "S",  6: "S",  7: "S", 8: "S", 9: "S", 10: "S", 11: "S"},
}

# Pair splits. Key is pair value (Ace=11, Ten=10).
_PAIRS: dict[int, dict[int, str]] = {
    2:  {2: "Ph", 3: "Ph", 4: "P",  5: "P",  6: "P",  7: "P", 8: "H", 9: "H", 10: "H", 11: "H"},
    3:  {2: "Ph", 3: "Ph", 4: "P",  5: "P",  6: "P",  7: "P", 8: "H", 9: "H", 10: "H", 11: "H"},
    4:  {2: "H",  3: "H",  4: "H",  5: "Ph", 6: "Ph", 7: "H", 8: "H", 9: "H", 10: "H", 11: "H"},
    5:  {2: "D",  3: "D",  4: "D",  5: "D",  6: "D",  7: "D", 8: "D", 9: "D", 10: "H", 11: "H"},
    6:  {2: "Ph", 3: "P",  4: "P",  5: "P",  6: "P",  7: "H", 8: "H", 9: "H", 10: "H", 11: "H"},
    7:  {2: "P",  3: "P",  4: "P",  5: "P",  6: "P",  7: "P", 8: "H", 9: "H", 10: "H", 11: "H"},
    8:  {2: "P",  3: "P",  4: "P",  5: "P",  6: "P",  7: "P", 8: "P", 9: "P", 10: "P", 11: "P"},
    9:  {2: "P",  3: "P",  4: "P",  5: "P",  6: "P",  7: "S", 8: "P", 9: "P", 10: "S", 11: "S"},
    10: {2: "S",  3: "S",  4: "S",  5: "S",  6: "S",  7: "S", 8: "S", 9: "S", 10: "S", 11: "S"},
    11: {2: "P",  3: "P",  4: "P",  5: "P",  6: "P",  7: "P", 8: "P", 9: "P", 10: "P", 11: "P"},
}


def _code_to_action(
    code: str,
    *,
    can_double: bool,
    can_split: bool,
    can_surrender: bool,
) -> Action:
    if code == "H":
        return Action.HIT
    if code == "S":
        return Action.STAND
    if code == "D":
        return Action.DOUBLE if can_double else Action.HIT
    if code == "Ds":
        return Action.DOUBLE if can_double else Action.STAND
    if code == "P":
        return Action.SPLIT if can_split else Action.HIT
    if code == "Ph":
        # "Split if DAS, else Hit" — we approximate "DAS allowed" as simply
        # whether the engine is willing to split right now. Most tables do DAS.
        return Action.SPLIT if can_split else Action.HIT
    if code == "R":
        return Action.SURRENDER if can_surrender else Action.HIT
    if code == "Rs":
        return Action.SURRENDER if can_surrender else Action.STAND
    raise ValueError(f"unknown strategy code: {code!r}")


def recommend(hand: Hand, dealer_upcard: Card) -> Action:
    """Recommend an action given a player hand and the dealer's upcard.

    Respects the hand's current capabilities (double/split/surrender may not be
    available after the first decision) and falls back to the next-best action
    when the charted action is not legal.
    """
    dk = _dealer_key(dealer_upcard)

    # Pair split decisions only apply on the opening two cards.
    if hand.can_split() and (hand.is_pair() or hand.is_ten_pair()):
        pair_rank = hand.cards[0].rank
        pair_key = 11 if pair_rank is Rank.ACE else (10 if pair_rank.is_ten_valued else pair_rank.blackjack_values[0])
        code = _PAIRS[pair_key][dk]
        action = _code_to_action(
            code,
            can_double=hand.can_double(),
            can_split=hand.can_split(),
            can_surrender=hand.can_surrender(),
        )
        return action

    total = hand.total()
    if hand.is_soft() and total <= 21:
        code = _SOFT[max(13, min(21, total))][dk]
    else:
        hard_total = max(5, min(21, total))
        code = _HARD[hard_total][dk]

    return _code_to_action(
        code,
        can_double=hand.can_double(),
        can_split=hand.can_split(),
        can_surrender=hand.can_surrender(),
    )
