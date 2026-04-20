"""Terminal entry point.

Ties together: HID scanner input → card parsing → blackjack engine →
basic-strategy recommendations → AWS event sink.

The CLI is intentionally line-oriented so it works both with a real scanner
(typing a barcode + Enter) and with piped stdin for automation/tests.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from typing import IO

from . import events
from .aws_client import EventSink
from .card import Card, get_parser
from .config import Config
from .deck import Shoe
from .game import (
    Action,
    GamePhase,
    Hand,
    HandState,
    Outcome,
    Player,
    Round,
)
from .scanner import Scanner
from .sink_factory import build_sink
from .strategy import recommend

logger = logging.getLogger(__name__)


_ACTION_KEYWORDS: dict[str, Action] = {
    "hit": Action.HIT,
    "h": Action.HIT,
    "stand": Action.STAND,
    "s": Action.STAND,
    "stay": Action.STAND,
    "double": Action.DOUBLE,
    "d": Action.DOUBLE,
    "split": Action.SPLIT,
    "p": Action.SPLIT,
    "surrender": Action.SURRENDER,
    "r": Action.SURRENDER,
}


@dataclass
class CLIState:
    config: Config
    sink: EventSink
    scanner: Scanner
    shoe: Shoe
    session_id: str
    out: IO[str]
    in_: IO[str]

    def emit(self, type_: str, payload: dict[str, object]) -> None:
        self.sink.emit(events.event(type_, self.session_id, payload))


def _print(state: CLIState, msg: str = "") -> None:
    state.out.write(msg + "\n")
    state.out.flush()


def _prompt(state: CLIState, msg: str) -> str:
    state.out.write(msg)
    state.out.flush()
    line = state.in_.readline()
    if line == "":
        raise EOFError
    return line.rstrip("\r\n")


def _read_players(state: CLIState) -> list[Player]:
    raw = _prompt(state, "Number of players [1]: ").strip()
    n = int(raw) if raw else 1
    if n < 1:
        n = 1
    players: list[Player] = []
    for i in range(n):
        name = _prompt(state, f"Player {i + 1} name [P{i + 1}]: ").strip() or f"P{i + 1}"
        players.append(Player(name=name))
    return players


def _scan_card(state: CLIState, prompt: str) -> Card:
    """Block until a valid card is scanned. Invalid scans are logged and reported."""
    while True:
        state.out.write(prompt)
        state.out.flush()
        event = state.scanner.scan()
        if event is None:
            raise EOFError
        if event.card is None:
            state.emit(events.SCAN_ERROR, {"raw": event.raw, "error": event.error})
            _print(state, f"  ! bad scan: {event.error} (raw={event.raw!r})")
            continue
        state.shoe.record(event.card)
        state.emit(
            events.SCAN_OK,
            {"raw": event.raw, "card": event.card.short, "deck_id": event.card.deck_id},
        )
        return event.card


def _read_action(state: CLIState, hand: Hand, dealer_up: Card) -> Action:
    suggested = recommend(hand, dealer_up)
    state.emit(
        events.RECOMMENDATION,
        {
            "hand": [c.short for c in hand.cards],
            "dealer_up": dealer_up.short,
            "suggested": suggested.value,
        },
    )
    allowed = ["hit", "stand"]
    if hand.can_double():
        allowed.append("double")
    if hand.can_split():
        allowed.append("split")
    if hand.can_surrender():
        allowed.append("surrender")

    while True:
        text = _prompt(
            state,
            f"  action ({'/'.join(allowed)}) [suggested: {suggested.value}]: ",
        ).strip().lower()
        if text == "":
            return suggested
        if text in _ACTION_KEYWORDS:
            action = _ACTION_KEYWORDS[text]
            # Verify legality against the hand.
            if action is Action.DOUBLE and not hand.can_double():
                _print(state, "  cannot double this hand")
                continue
            if action is Action.SPLIT and not hand.can_split():
                _print(state, "  cannot split this hand")
                continue
            if action is Action.SURRENDER and not hand.can_surrender():
                _print(state, "  cannot surrender this hand")
                continue
            return action
        _print(state, f"  unknown action: {text!r}")


def _play_round(state: CLIState, players: list[Player]) -> None:
    for p in players:
        p.reset_for_round(bet=1.0)
    round_ = Round(players=players)
    state.emit(
        events.ROUND_START,
        {"players": [p.name for p in players], "decks": state.config.decks},
    )

    # -- initial deal --
    round_.start_dealing()
    while round_.phase is GamePhase.DEALING:
        target = round_.next_deal_target
        assert target is not None
        # target[1] is None for the dealer — distinguish on the index field,
        # not the name, in case a player is named "dealer".
        who = "dealer" if target[1] is None else target[0]
        card = _scan_card(state, f"Scan card for {who}: ")
        round_.deal_next(card)
        state.emit(
            events.HAND_DEALT,
            {"to": who, "card": card.short},
        )

    _show_table(state, round_)

    # -- player actions --
    if round_.phase is GamePhase.PLAYER_ACTIONS:
        dealer_up = round_.dealer.cards[0]
        while round_.phase is GamePhase.PLAYER_ACTIONS:
            player = round_.active_player()
            if player is None:
                break
            hand = player.active_hand
            _print(
                state,
                f"\n{player.name}'s turn — hand {player.active_hand_index + 1}: {hand}",
            )
            # After a split, the active hand may only have one card — need to
            # deal a second card before asking for an action.
            if len(hand.cards) < 2:
                card = _scan_card(state, f"Scan replacement card for {player.name} (after split): ")
                hand.add(card)
                state.emit(
                    events.HAND_DEALT,
                    {"to": player.name, "hand_index": player.active_hand_index, "card": card.short},
                )
                _print(state, f"  {hand}")
                if hand.is_finished():
                    player.advance_to_next_active_hand()
                    if all(p.all_finished() for p in round_.players):
                        round_.phase = GamePhase.DEALER_PLAY
                    continue

            action = _read_action(state, hand, dealer_up)
            action_card: Card | None = None
            if action in (Action.HIT, Action.DOUBLE):
                action_card = _scan_card(state, f"  scan card for {action.value}: ")
            # Capture the hand index before apply_action, because finishing the
            # current hand advances active_hand_index to the next split hand.
            acted_hand_index = player.active_hand_index
            round_.apply_action(player.name, action, card=action_card)
            state.emit(
                events.HAND_ACTION,
                {
                    "player": player.name,
                    "hand_index": acted_hand_index,
                    "action": action.value,
                    "card": action_card.short if action_card else None,
                    "total_after": hand.total(),
                    "state_after": hand.state.value,
                },
            )
            _print(state, f"  -> {hand}")

    # -- dealer play --
    if round_.phase is GamePhase.DEALER_PLAY:
        _print(state, f"\nDealer reveals: {round_.dealer}")
        while round_.dealer_should_hit(state.config.dealer_hits_soft_17):
            card = _scan_card(state, "Scan card for dealer: ")
            round_.dealer_hit(card)
            state.emit(
                events.DEALER_ACTION,
                {"action": "hit", "card": card.short, "total_after": round_.dealer.total()},
            )
            _print(state, f"  dealer: {round_.dealer}")
        round_.dealer_stand()
        state.emit(
            events.DEALER_ACTION,
            {"action": "stand", "total_after": round_.dealer.total()},
        )

    # -- settlement --
    outcomes = round_.settle()
    _print(state, "\n== Results ==")
    for (name, idx), outcome in outcomes.items():
        player = next(p for p in players if p.name == name)
        hand = player.hands[idx]
        _print(state, f"  {name} hand {idx + 1}: {hand}  -> {outcome.value} (chips: {player.chips:+.1f})")
        state.emit(
            events.HAND_RESULT,
            {
                "player": name,
                "hand_index": idx,
                "outcome": outcome.value,
                "total": hand.total(),
                "bet": hand.bet,
                "chips_delta": _payout_for_outcome(hand, outcome),
            },
        )
    state.emit(
        events.ROUND_END,
        {
            "running_count": state.shoe.running_count(),
            "true_count": state.shoe.true_count(),
            "dealt": state.shoe.dealt_count,
            "remaining": state.shoe.remaining,
        },
    )

    if state.shoe.penetration_reached:
        _print(state, "\n* Penetration reached — time to reshuffle the shoe.")
        state.shoe.reset()
        state.emit(events.SHOE_RESHUFFLE, {})


def _payout_for_outcome(hand: Hand, outcome: Outcome) -> float:
    # Mirrors Round._payout for the event payload.
    if outcome is Outcome.PLAYER_BLACKJACK:
        return hand.bet * 1.5
    if outcome is Outcome.PLAYER_WIN:
        return hand.bet
    if outcome is Outcome.DEALER_WIN:
        return -hand.bet
    if outcome is Outcome.SURRENDER:
        return -hand.bet / 2.0
    return 0.0


def _show_table(state: CLIState, round_: Round) -> None:
    _print(state, "")
    _print(state, f"Dealer: {_dealer_display(round_.dealer)}")
    for p in round_.players:
        for i, h in enumerate(p.hands):
            _print(state, f"{p.name} hand {i + 1}: {h}")


def _dealer_display(hand: Hand) -> str:
    if hand.state is HandState.BLACKJACK:
        return f"[{' '.join(str(c) for c in hand.cards)}] = 21 BLACKJACK"
    if len(hand.cards) >= 2:
        return f"[{hand.cards[0]} XX]  (upcard {hand.cards[0]})"
    return f"{hand}"


def _run_loop(state: CLIState) -> int:
    _print(state, "blackjack-scanner — scan barcoded cards to play.")
    _print(
        state,
        f"parser={state.config.parser_name}  decks={state.config.decks}  "
        f"H17={state.config.dealer_hits_soft_17}  aws={state.config.aws_mode}",
    )
    try:
        players = _read_players(state)
    except EOFError:
        _print(state, "(no input)")
        return 0

    try:
        while True:
            _play_round(state, players)
            ans = _prompt(state, "\nAnother round? [Y/n]: ").strip().lower()
            if ans in {"n", "no", "quit", "q", "exit"}:
                _print(state, "Goodbye.")
                return 0
    except EOFError:
        _print(state, "\n(input closed)")
        return 0
    except KeyboardInterrupt:
        _print(state, "\n(interrupted)")
        return 130


def build_state(
    config: Config,
    *,
    sink: EventSink | None = None,
    in_: IO[str] | None = None,
    out: IO[str] | None = None,
) -> CLIState:
    parser = get_parser(config.parser_name)
    actual_sink = sink if sink is not None else build_sink(config)
    actual_in: IO[str] = in_ if in_ is not None else sys.stdin
    actual_out: IO[str] = out if out is not None else sys.stdout
    return CLIState(
        config=config,
        sink=actual_sink,
        scanner=Scanner(parser, stream=actual_in),
        shoe=Shoe(decks=config.decks, penetration=config.penetration),
        session_id=events.make_session_id(),
        in_=actual_in,
        out=actual_out,
    )


def main(argv: list[str] | None = None) -> int:
    argparser = argparse.ArgumentParser(prog="blackjack-scanner")
    argparser.add_argument(
        "--no-tty",
        action="store_true",
        help="Read scans from stdin without any interactive prompts assuming a TTY.",
    )
    argparser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = argparser.parse_args(argv)
    logging.basicConfig(level=args.log_level)

    config = Config.from_env()
    state = build_state(config)
    try:
        return _run_loop(state)
    finally:
        state.sink.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
