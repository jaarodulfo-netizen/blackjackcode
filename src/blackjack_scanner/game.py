"""Blackjack engine: hands, rounds, dealer logic, outcome resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .card import Card, Rank


class HandState(Enum):
    ACTIVE = "active"
    STOOD = "stood"
    BUST = "bust"
    BLACKJACK = "blackjack"
    DOUBLED = "doubled"
    SURRENDERED = "surrendered"


class Action(Enum):
    HIT = "hit"
    STAND = "stand"
    DOUBLE = "double"
    SPLIT = "split"
    SURRENDER = "surrender"


class Outcome(Enum):
    PLAYER_WIN = "player_win"
    PLAYER_BLACKJACK = "player_blackjack"
    DEALER_WIN = "dealer_win"
    PUSH = "push"
    SURRENDER = "surrender"


@dataclass
class Hand:
    cards: list[Card] = field(default_factory=list)
    bet: float = 0.0
    state: HandState = HandState.ACTIVE
    is_split: bool = False
    doubled: bool = False

    def add(self, card: Card) -> None:
        self.cards.append(card)
        if self.total() > 21:
            self.state = HandState.BUST
        elif self.total() == 21 and len(self.cards) == 2 and not self.is_split:
            self.state = HandState.BLACKJACK

    def total(self) -> int:
        """Best blackjack total (<= 21 if possible)."""
        values = [1 if c.rank is Rank.ACE else c.rank.blackjack_values[0] for c in self.cards]
        total = sum(values)
        # Promote one ace from 1 to 11 if it keeps us <= 21.
        if any(c.rank is Rank.ACE for c in self.cards) and total + 10 <= 21:
            total += 10
        return total

    def is_soft(self) -> bool:
        """True if the hand contains an ace counted as 11."""
        if not any(c.rank is Rank.ACE for c in self.cards):
            return False
        hard = sum(1 if c.rank is Rank.ACE else c.rank.blackjack_values[0] for c in self.cards)
        return hard + 10 <= 21

    def is_pair(self) -> bool:
        return len(self.cards) == 2 and self.cards[0].rank is self.cards[1].rank

    def is_ten_pair(self) -> bool:
        """Any two ten-valued cards (T, J, Q, K) count as a splittable "pair" in many rulesets."""
        return len(self.cards) == 2 and all(c.rank.is_ten_valued for c in self.cards)

    def can_double(self) -> bool:
        return self.state is HandState.ACTIVE and len(self.cards) == 2 and not self.doubled

    def can_split(self) -> bool:
        return self.state is HandState.ACTIVE and self.is_pair() and not self.is_split

    def can_surrender(self) -> bool:
        return self.state is HandState.ACTIVE and len(self.cards) == 2 and not self.is_split

    def is_finished(self) -> bool:
        return self.state is not HandState.ACTIVE

    def __str__(self) -> str:
        body = " ".join(str(c) for c in self.cards) or "(empty)"
        tot = self.total()
        soft = " soft" if self.is_soft() and tot <= 21 else ""
        return f"[{body}] = {tot}{soft} ({self.state.value})"


@dataclass
class Player:
    name: str
    hands: list[Hand] = field(default_factory=lambda: [Hand()])
    chips: float = 0.0
    active_hand_index: int = 0

    @property
    def active_hand(self) -> Hand:
        return self.hands[self.active_hand_index]

    def reset_for_round(self, bet: float = 0.0) -> None:
        self.hands = [Hand(bet=bet)]
        self.active_hand_index = 0

    def all_finished(self) -> bool:
        return all(h.is_finished() for h in self.hands)

    def advance_to_next_active_hand(self) -> bool:
        """Move to the next unfinished hand. Returns True if one was found."""
        for i in range(self.active_hand_index + 1, len(self.hands)):
            if not self.hands[i].is_finished():
                self.active_hand_index = i
                return True
        return False


class GamePhase(Enum):
    BETTING = "betting"
    DEALING = "dealing"
    PLAYER_ACTIONS = "player_actions"
    DEALER_PLAY = "dealer_play"
    SETTLEMENT = "settlement"
    COMPLETE = "complete"


@dataclass
class Round:
    players: list[Player]
    dealer: Hand = field(default_factory=Hand)
    phase: GamePhase = GamePhase.BETTING
    _deal_order: list[tuple[str, int] | tuple[str, None]] = field(default_factory=list)
    _deal_index: int = 0
    outcomes: dict[tuple[str, int], Outcome] = field(default_factory=dict)

    # ---- dealing ----------------------------------------------------------------

    def start_dealing(self) -> None:
        """Build the 4-or-more-card initial deal sequence.

        Standard casino order: each player one card, dealer upcard, each player
        second card, dealer hole card. We model the dealer as the virtual player
        named ``"dealer"`` with no explicit index.
        """
        if self.phase is not GamePhase.BETTING:
            raise RuntimeError(f"cannot start dealing in phase {self.phase.value}")
        order: list[tuple[str, int] | tuple[str, None]] = []
        for _pass in range(2):
            for p in self.players:
                order.append((p.name, 0))
            order.append(("dealer", None))
        self._deal_order = order
        self._deal_index = 0
        self.phase = GamePhase.DEALING

    @property
    def next_deal_target(self) -> tuple[str, int] | tuple[str, None] | None:
        if self._deal_index >= len(self._deal_order):
            return None
        return self._deal_order[self._deal_index]

    def deal_next(self, card: Card) -> tuple[str, int] | tuple[str, None]:
        """Assign a scanned card to the next target in the initial deal."""
        if self.phase is not GamePhase.DEALING:
            raise RuntimeError(f"deal_next called in phase {self.phase.value}")
        target = self._deal_order[self._deal_index]
        if target[0] == "dealer":
            self.dealer.add(card)
        else:
            player = self._player(target[0])
            player.hands[0].add(card)
        self._deal_index += 1
        if self._deal_index >= len(self._deal_order):
            self._finish_dealing()
        return target

    def _finish_dealing(self) -> None:
        # Check for dealer / player naturals.
        player_has_bj = any(
            p.hands[0].state is HandState.BLACKJACK for p in self.players
        )
        dealer_has_bj = self.dealer.total() == 21 and len(self.dealer.cards) == 2
        if dealer_has_bj:
            self.dealer.state = HandState.BLACKJACK

        if dealer_has_bj or all(p.hands[0].state is HandState.BLACKJACK for p in self.players):
            # Skip player actions, go straight to settlement.
            self.phase = GamePhase.SETTLEMENT
            return

        # If every player starts with a natural, still need settlement after dealer.
        if player_has_bj and all(p.hands[0].is_finished() for p in self.players):
            self.phase = GamePhase.DEALER_PLAY
        else:
            self.phase = GamePhase.PLAYER_ACTIONS

    # ---- player actions ---------------------------------------------------------

    def active_player(self) -> Player | None:
        for p in self.players:
            if not p.all_finished():
                return p
        return None

    def apply_action(self, player_name: str, action: Action, card: Card | None = None) -> None:
        """Apply an action to the given player's active hand.

        ``card`` is required for HIT and DOUBLE (because a physical card is scanned
        to fulfill the action) and for the first card of the new hand after SPLIT.
        """
        if self.phase is not GamePhase.PLAYER_ACTIONS:
            raise RuntimeError(f"apply_action called in phase {self.phase.value}")
        player = self._player(player_name)
        hand = player.active_hand
        if hand.is_finished():
            raise RuntimeError("active hand is already finished")

        if action is Action.HIT:
            if card is None:
                raise ValueError("HIT requires a scanned card")
            hand.add(card)
        elif action is Action.STAND:
            hand.state = HandState.STOOD
        elif action is Action.DOUBLE:
            if not hand.can_double():
                raise RuntimeError("cannot double this hand")
            if card is None:
                raise ValueError("DOUBLE requires a scanned card")
            hand.add(card)
            hand.bet *= 2
            hand.doubled = True
            if hand.state is HandState.ACTIVE:
                hand.state = HandState.DOUBLED
        elif action is Action.SPLIT:
            if not hand.can_split():
                raise RuntimeError("cannot split this hand")
            first, second = hand.cards
            original_bet = hand.bet
            new_hand_a = Hand(cards=[first], bet=original_bet, is_split=True)
            new_hand_b = Hand(cards=[second], bet=original_bet, is_split=True)
            # Replace current hand with two new ones; preserve order.
            player.hands[player.active_hand_index : player.active_hand_index + 1] = [
                new_hand_a,
                new_hand_b,
            ]
            # After split we immediately need a card for the first new hand — but
            # callers drive that through subsequent scans, so we do nothing else here.
        elif action is Action.SURRENDER:
            if not hand.can_surrender():
                raise RuntimeError("cannot surrender this hand")
            hand.state = HandState.SURRENDERED
        else:  # pragma: no cover - enum is exhaustive
            raise ValueError(f"unsupported action: {action}")

        # If this hand is now finished, try to move to the next hand for this player.
        if hand.is_finished():
            player.advance_to_next_active_hand()

        if all(p.all_finished() for p in self.players):
            self.phase = GamePhase.DEALER_PLAY

    # ---- dealer play ------------------------------------------------------------

    def dealer_should_hit(self, hits_soft_17: bool) -> bool:
        total = self.dealer.total()
        if total < 17:
            return True
        return total == 17 and hits_soft_17 and self.dealer.is_soft()

    def dealer_hit(self, card: Card) -> None:
        if self.phase is not GamePhase.DEALER_PLAY:
            raise RuntimeError(f"dealer_hit called in phase {self.phase.value}")
        self.dealer.add(card)

    def dealer_stand(self) -> None:
        if self.phase is not GamePhase.DEALER_PLAY:
            raise RuntimeError(f"dealer_stand called in phase {self.phase.value}")
        if self.dealer.state is HandState.ACTIVE:
            self.dealer.state = HandState.STOOD
        self.phase = GamePhase.SETTLEMENT

    # ---- settlement -------------------------------------------------------------

    def settle(self, blackjack_pays: float = 1.5) -> dict[tuple[str, int], Outcome]:
        """Resolve all hands. Updates player chip balances and returns a map of
        ``(player_name, hand_index) -> Outcome``."""
        if self.phase not in (GamePhase.SETTLEMENT, GamePhase.DEALER_PLAY):
            raise RuntimeError(f"settle called in phase {self.phase.value}")
        dealer_total = self.dealer.total()
        dealer_bj = self.dealer.state is HandState.BLACKJACK
        dealer_bust = self.dealer.state is HandState.BUST or dealer_total > 21

        outcomes: dict[tuple[str, int], Outcome] = {}
        for p in self.players:
            for idx, hand in enumerate(p.hands):
                outcome = self._resolve_hand(hand, dealer_total, dealer_bj, dealer_bust)
                outcomes[(p.name, idx)] = outcome
                p.chips += self._payout(hand, outcome, blackjack_pays)
        self.outcomes = outcomes
        self.phase = GamePhase.COMPLETE
        return outcomes

    @staticmethod
    def _resolve_hand(hand: Hand, dealer_total: int, dealer_bj: bool, dealer_bust: bool) -> Outcome:
        if hand.state is HandState.SURRENDERED:
            return Outcome.SURRENDER
        if hand.state is HandState.BLACKJACK and not dealer_bj:
            return Outcome.PLAYER_BLACKJACK
        if dealer_bj and hand.state is HandState.BLACKJACK:
            return Outcome.PUSH
        if dealer_bj:
            return Outcome.DEALER_WIN
        if hand.state is HandState.BUST:
            return Outcome.DEALER_WIN
        if dealer_bust:
            return Outcome.PLAYER_WIN
        player_total = hand.total()
        if player_total > dealer_total:
            return Outcome.PLAYER_WIN
        if player_total < dealer_total:
            return Outcome.DEALER_WIN
        return Outcome.PUSH

    @staticmethod
    def _payout(hand: Hand, outcome: Outcome, blackjack_pays: float) -> float:
        if outcome is Outcome.PLAYER_BLACKJACK:
            return hand.bet * blackjack_pays
        if outcome is Outcome.PLAYER_WIN:
            return hand.bet
        if outcome is Outcome.DEALER_WIN:
            return -hand.bet
        if outcome is Outcome.SURRENDER:
            return -hand.bet / 2.0
        return 0.0  # push

    # ---- helpers ----------------------------------------------------------------

    def _player(self, name: str) -> Player:
        for p in self.players:
            if p.name == name:
                return p
        raise KeyError(f"no such player: {name!r}")
