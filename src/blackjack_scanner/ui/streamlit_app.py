"""Streamlit dealer UI for the blackjack engine.

Wires the :mod:`blackjack_scanner.game` engine to a big-screen-style dealer
interface: betting phase, initial deal, per-player actions
(hit / stand / double / split / surrender), dealer play, and auto-settlement.

Card input is the same normalized barcode string the HID scanner emits
(e.g. ``AS``, ``TH``, ``KC``), so a real keyboard-wedge scanner can be used
to drive the UI once the "Scan card" input is focused. For development /
quickplay, every rank/suit also has a clickable button that submits the
matching barcode.

Run with::

    streamlit run app.py
    # or, once installed with the [ui] extra:
    blackjack-scanner-ui
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import streamlit as st

from blackjack_scanner import events
from blackjack_scanner.aws_client import EventSink
from blackjack_scanner.card import BarcodeError, Card, Rank, Suit, get_parser
from blackjack_scanner.config import Config
from blackjack_scanner.deck import Shoe
from blackjack_scanner.game import (
    Action,
    GamePhase,
    Hand,
    Outcome,
    Player,
    Round,
)
from blackjack_scanner.sink_factory import build_sink
from blackjack_scanner.strategy import recommend

# --------------------------------------------------------------------------- #
# Session state bootstrap                                                     #
# --------------------------------------------------------------------------- #

_OUTCOME_LABEL: dict[Outcome, str] = {
    Outcome.PLAYER_WIN: "WIN",
    Outcome.PLAYER_BLACKJACK: "BLACKJACK",
    Outcome.DEALER_WIN: "LOSE",
    Outcome.PUSH: "PUSH",
    Outcome.SURRENDER: "SURRENDER",
}

_OUTCOME_COLOR: dict[Outcome, str] = {
    Outcome.PLAYER_WIN: "#1fb45f",
    Outcome.PLAYER_BLACKJACK: "#ffd93d",
    Outcome.DEALER_WIN: "#d94343",
    Outcome.PUSH: "#888888",
    Outcome.SURRENDER: "#b06a00",
}

_SUIT_COLOR: dict[Suit, str] = {
    Suit.SPADES: "#111111",
    Suit.CLUBS: "#111111",
    Suit.HEARTS: "#c62828",
    Suit.DIAMONDS: "#c62828",
}


def _get_state() -> dict[str, Any]:
    """Return the mutable session-scoped state dict."""
    return cast(dict[str, Any], st.session_state.setdefault("_bjs", {}))


def _init_state(s: dict[str, Any]) -> None:
    """Populate the session state on first load."""
    cfg = Config.from_env()
    s.setdefault("cfg", cfg)
    s.setdefault("session_id", uuid4().hex)
    s.setdefault("players", [])
    s.setdefault("bets", {})
    s.setdefault("round", None)
    s.setdefault("results", None)
    s.setdefault("result_meta", {})
    s.setdefault("toasts", [])
    s.setdefault("default_bet", 10.0)
    s.setdefault("num_players", 1)
    s.setdefault("player_names", ["P1"])
    s.setdefault("round_number", 0)
    s.setdefault("shoe", _new_shoe(cfg))
    s.setdefault("sink", _new_sink(cfg))


def _new_shoe(cfg: Config) -> Shoe:
    shoe = Shoe(decks=cfg.decks, penetration=cfg.penetration)
    shoe.reset()
    return shoe


def _new_sink(cfg: Config) -> EventSink:
    return build_sink(cfg)


def _parse_card(raw: str, cfg: Config) -> Card | None:
    parser = get_parser(cfg.parser_name)
    try:
        return parser.parse(raw)
    except BarcodeError:
        return None


def _emit(s: dict[str, Any], type_: str, payload: dict[str, object]) -> None:
    sink: EventSink = s["sink"]
    sink.emit(events.event(type_, s["session_id"], payload))


def _toast(s: dict[str, Any], level: str, msg: str) -> None:
    s["toasts"].append((level, msg))


# --------------------------------------------------------------------------- #
# Game actions (bridge UI events -> engine)                                   #
# --------------------------------------------------------------------------- #


def _start_round(s: dict[str, Any]) -> None:
    """Begin a new round with the configured players and bets."""
    cfg: Config = s["cfg"]
    names: list[str] = list(s["player_names"])
    for n in names:
        if n.strip().lower() == "dealer":
            _toast(s, "error", f"'{n}' is a reserved name. Please rename.")
            return

    # Reuse existing Player objects (to preserve chip counts) if names match.
    existing: dict[str, Player] = {p.name: p for p in s["players"]}
    players: list[Player] = []
    for name in names:
        p = existing.get(name) or Player(name=name)
        p.reset_for_round(bet=float(s["bets"].get(name, s["default_bet"])))
        players.append(p)
    s["players"] = players
    s["round"] = Round(players=players)
    s["results"] = None
    s["result_meta"] = {}
    s["round_number"] += 1
    round_: Round = s["round"]
    round_.start_dealing()

    _emit(
        s,
        events.ROUND_START,
        {
            "players": [p.name for p in players],
            "bets": {p.name: p.hands[0].bet for p in players},
            "dealer_hits_soft_17": cfg.dealer_hits_soft_17,
        },
    )


def _scan_into_round(s: dict[str, Any], raw: str) -> None:
    """Interpret a raw barcode and route it to whatever the round needs next."""
    cfg: Config = s["cfg"]
    raw = raw.strip()
    if not raw:
        return
    card = _parse_card(raw, cfg)
    if card is None:
        _emit(s, events.SCAN_ERROR, {"raw": raw})
        _toast(s, "error", f"Could not parse barcode: {raw!r}")
        return

    round_: Round | None = s["round"]
    if round_ is None:
        _toast(s, "error", "No active round. Click 'Deal' first.")
        return

    shoe: Shoe = s["shoe"]
    shoe.record(card)
    _emit(
        s,
        events.SCAN_OK,
        {"raw": raw, "card": card.short, "deck_id": card.deck_id},
    )

    if round_.phase is GamePhase.DEALING:
        target = round_.deal_next(card)
        name = "dealer" if target[1] is None else target[0]
        idx = -1 if target[1] is None else target[1]
        _emit(
            s,
            events.HAND_DEALT,
            {"to": name, "hand_index": idx, "card": card.short},
        )
        # deal_next may flip the phase to SETTLEMENT (natural blackjack on
        # either side); short-circuit directly into settlement in that case.
        if round_.phase.value == GamePhase.SETTLEMENT.value:
            _run_dealer_and_settle(s)
        return

    if round_.phase is GamePhase.PLAYER_ACTIONS:
        pending = s.pop("pending_action_card", None)
        if pending is None:
            _toast(
                s,
                "warn",
                "Unexpected card during player actions. Pick an action first.",
            )
            return
        player_name: str = pending["player"]
        action: Action = pending["action"]
        _apply_player_action(s, player_name, action, card)
        return

    if round_.phase is GamePhase.DEALER_PLAY:
        _dealer_hit_with(s, card)
        return

    _toast(s, "warn", f"No input expected in phase {round_.phase.value}.")


def _pick_player_action(s: dict[str, Any], player: Player, action: Action) -> None:
    """Handle a click on a player action button."""
    round_: Round = s["round"]
    hand = player.active_hand

    if action in (Action.HIT, Action.DOUBLE):
        # Stash the pending action; the next scanned card completes it.
        s["pending_action_card"] = {"player": player.name, "action": action}
        _toast(s, "info", f"{player.name}: {action.value} — scan next card")
        return

    if action is Action.SPLIT:
        # Split does not consume a card; engine creates two hands with one card each.
        # After split, the UI will prompt for a card for each new hand on entry.
        round_.apply_action(player.name, action, card=None)
        # apply_action replaces the original hand in player.hands with two new
        # single-card hands; the pre-split `hand` variable is now orphaned, so
        # read the fresh active hand for the event payload.
        new_active = player.active_hand
        _emit(
            s,
            events.HAND_ACTION,
            {
                "player": player.name,
                "hand_index": player.active_hand_index,
                "action": action.value,
                "card": None,
                "total_after": new_active.total(),
                "state_after": new_active.state.value,
            },
        )
        _toast(s, "info", f"{player.name}: split — scan card for hand 1")
        s["pending_split_deal"] = {"player": player.name}
        return

    # Stand / Surrender: apply immediately, no card required.
    acted_index = player.active_hand_index
    round_.apply_action(player.name, action, card=None)
    _emit(
        s,
        events.HAND_ACTION,
        {
            "player": player.name,
            "hand_index": acted_index,
            "action": action.value,
            "card": None,
            "total_after": hand.total(),
            "state_after": hand.state.value,
        },
    )
    _maybe_start_dealer_play(s)


def _apply_player_action(
    s: dict[str, Any], player_name: str, action: Action, card: Card
) -> None:
    round_: Round = s["round"]
    player = next(p for p in round_.players if p.name == player_name)
    hand = player.active_hand
    acted_index = player.active_hand_index
    round_.apply_action(player_name, action, card=card)
    _emit(
        s,
        events.HAND_ACTION,
        {
            "player": player_name,
            "hand_index": acted_index,
            "action": action.value,
            "card": card.short,
            "total_after": hand.total(),
            "state_after": hand.state.value,
        },
    )
    _maybe_start_dealer_play(s)


def _handle_pending_split_card(s: dict[str, Any], raw: str) -> None:
    """Feed a replacement card into a just-split hand."""
    cfg: Config = s["cfg"]
    raw = raw.strip()
    if not raw:
        return
    card = _parse_card(raw, cfg)
    if card is None:
        _toast(s, "error", f"Could not parse barcode: {raw!r}")
        _emit(s, events.SCAN_ERROR, {"raw": raw})
        return
    round_: Round = s["round"]
    shoe: Shoe = s["shoe"]
    shoe.record(card)
    _emit(s, events.SCAN_OK, {"raw": raw, "card": card.short, "deck_id": card.deck_id})

    pending = s["pending_split_deal"]
    player = next(p for p in round_.players if p.name == pending["player"])
    # Feed the replacement card to the first split hand still holding a single
    # card, not necessarily the currently-active one. After splitting a pair
    # the engine leaves both new hands with one card; when the first hand gets
    # replaced and played out, the active cursor advances to the second hand
    # which also still needs a card.
    target_idx: int | None = next(
        (i for i, h in enumerate(player.hands) if len(h.cards) < 2 and not h.is_finished()),
        None,
    )
    if target_idx is None:
        _toast(s, "warn", "No split hand is waiting for a card.")
        s.pop("pending_split_deal", None)
        return
    hand = player.hands[target_idx]
    hand.add(card)
    _emit(
        s,
        events.HAND_DEALT,
        {"to": player.name, "hand_index": target_idx, "card": card.short},
    )
    if hand.is_finished() and target_idx == player.active_hand_index:
        player.advance_to_next_active_hand()
        if all(p.all_finished() for p in round_.players):
            round_.phase = GamePhase.DEALER_PLAY

    # Keep the pending-split prompt up until every split hand has its second
    # card (or is otherwise finished).
    if all(len(h.cards) >= 2 or h.is_finished() for h in player.hands):
        s.pop("pending_split_deal", None)

    _maybe_start_dealer_play(s)


def _maybe_start_dealer_play(s: dict[str, Any]) -> None:
    round_: Round = s["round"]
    if round_.phase is GamePhase.DEALER_PLAY:
        # Don't auto-drive dealer scans; the UI asks for each card.
        return
    if round_.phase is GamePhase.SETTLEMENT:
        _run_dealer_and_settle(s)


def _dealer_hit_with(s: dict[str, Any], card: Card) -> None:
    round_: Round = s["round"]
    round_.dealer_hit(card)
    _emit(
        s,
        events.DEALER_ACTION,
        {
            "action": "hit",
            "card": card.short,
            "total_after": round_.dealer.total(),
            "state_after": round_.dealer.state.value,
        },
    )
    cfg: Config = s["cfg"]
    if not round_.dealer_should_hit(cfg.dealer_hits_soft_17):
        round_.dealer_stand()
        _emit(
            s,
            events.DEALER_ACTION,
            {
                "action": "stand",
                "total_after": round_.dealer.total(),
                "state_after": round_.dealer.state.value,
            },
        )
        _run_dealer_and_settle(s)


def _run_dealer_and_settle(s: dict[str, Any]) -> None:
    round_: Round = s["round"]
    cfg: Config = s["cfg"]
    # If we're still in DEALER_PLAY waiting on scans, bail — the UI will call
    # back once the dealer finishes hitting.
    if round_.phase is GamePhase.DEALER_PLAY and round_.dealer_should_hit(
        cfg.dealer_hits_soft_17
    ):
        return
    if round_.phase is GamePhase.DEALER_PLAY:
        round_.dealer_stand()

    if round_.phase is not GamePhase.SETTLEMENT:
        return

    outcomes = round_.settle()
    meta: dict[tuple[str, int], dict[str, float | int | str]] = {}
    for (name, idx), outcome in outcomes.items():
        player = next(p for p in round_.players if p.name == name)
        hand = player.hands[idx]
        chips_delta = _chips_delta(hand, outcome)
        meta[(name, idx)] = {
            "total": hand.total(),
            "bet": hand.bet,
            "chips_delta": chips_delta,
            "state": hand.state.value,
        }
        _emit(
            s,
            events.HAND_RESULT,
            {
                "player": name,
                "hand_index": idx,
                "outcome": outcome.value,
                "total": hand.total(),
                "bet": hand.bet,
                "chips_delta": chips_delta,
                "state": hand.state.value,
            },
        )
    round_.phase = GamePhase.COMPLETE
    s["results"] = outcomes
    s["result_meta"] = meta
    _emit(
        s,
        events.ROUND_END,
        {
            "dealer_total": round_.dealer.total(),
            "dealer_state": round_.dealer.state.value,
        },
    )


def _chips_delta(hand: Hand, outcome: Outcome) -> float:
    """Mirrors :meth:`Round._payout` for event / display purposes.

    Note ``hand.bet`` already reflects the doubled amount after a DOUBLE
    action (engine multiplies in-place), so no extra multiplier is needed.
    """
    if outcome is Outcome.PLAYER_BLACKJACK:
        return hand.bet * 1.5
    if outcome is Outcome.PLAYER_WIN:
        return hand.bet
    if outcome is Outcome.DEALER_WIN:
        return -hand.bet
    if outcome is Outcome.SURRENDER:
        return -hand.bet / 2.0
    return 0.0


def _reset_game(s: dict[str, Any]) -> None:
    """Drop everything except setup (names, bets, config)."""
    s["round"] = None
    s["results"] = None
    s["result_meta"] = {}
    s["pending_action_card"] = None
    s["pending_split_deal"] = None
    s.pop("last_recommendation_key", None)


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #


def _card_html(card: Card) -> str:
    color = _SUIT_COLOR[card.suit]
    rank = card.rank.value if card.rank.value != "T" else "10"
    return (
        "<div style='"
        "display:inline-block;min-width:54px;min-height:76px;"
        "margin:4px;padding:8px 6px;border:1px solid #ddd;border-radius:8px;"
        f"background:#fff;color:{color};font-weight:700;text-align:center;"
        "box-shadow:0 1px 3px rgba(0,0,0,0.12);font-family:monospace;'>"
        f"<div style='font-size:20px;line-height:1'>{rank}</div>"
        f"<div style='font-size:24px;line-height:1'>{card.suit.glyph}</div>"
        "</div>"
    )


def _hand_html(hand: Hand, hide_hole: bool = False) -> str:
    if hide_hole and len(hand.cards) >= 2:
        visible = [_card_html(hand.cards[0])] + [
            "<div style='display:inline-block;min-width:54px;min-height:76px;"
            "margin:4px;padding:8px 6px;border-radius:8px;background:#1f3a5f;"
            "color:#fff;text-align:center;vertical-align:top;"
            "box-shadow:0 1px 3px rgba(0,0,0,0.12);'>"
            "<div style='font-size:26px;margin-top:18px'>🂠</div></div>"
            for _ in hand.cards[1:]
        ]
        return "".join(visible)
    return "".join(_card_html(c) for c in hand.cards)


def _render_toasts(s: dict[str, Any]) -> None:
    toasts: list[tuple[str, str]] = s.pop("toasts", [])
    s["toasts"] = []
    for level, msg in toasts:
        if level == "error":
            st.error(msg)
        elif level == "warn":
            st.warning(msg)
        else:
            st.info(msg)


def _render_sidebar(s: dict[str, Any]) -> None:
    cfg: Config = s["cfg"]
    st.sidebar.header("Table setup")

    num = st.sidebar.number_input(
        "Players (1-4)",
        min_value=1,
        max_value=4,
        value=int(s["num_players"]),
        step=1,
    )
    s["num_players"] = int(num)
    names: list[str] = list(s.get("player_names", []))
    while len(names) < s["num_players"]:
        names.append(f"P{len(names) + 1}")
    names = names[: s["num_players"]]

    for i in range(s["num_players"]):
        names[i] = st.sidebar.text_input(
            f"Player {i + 1} name",
            value=names[i],
            key=f"player_name_{i}",
        )
    s["player_names"] = names

    default_bet = st.sidebar.number_input(
        "Default bet",
        min_value=1.0,
        max_value=10000.0,
        value=float(s["default_bet"]),
        step=1.0,
    )
    s["default_bet"] = float(default_bet)

    st.sidebar.divider()
    st.sidebar.subheader("Rules")
    decks = st.sidebar.selectbox(
        "Decks in shoe",
        options=[1, 2, 4, 6, 8],
        index=[1, 2, 4, 6, 8].index(cfg.decks) if cfg.decks in (1, 2, 4, 6, 8) else 3,
    )
    h17 = st.sidebar.checkbox(
        "Dealer hits soft 17 (H17)",
        value=bool(cfg.dealer_hits_soft_17),
    )
    if decks != cfg.decks or h17 != cfg.dealer_hits_soft_17:
        s["cfg"] = replace(cfg, decks=int(decks), dealer_hits_soft_17=bool(h17))
        s["shoe"] = _new_shoe(s["cfg"])

    st.sidebar.divider()
    st.sidebar.subheader("Shoe")
    shoe: Shoe = s["shoe"]
    st.sidebar.caption(
        f"{shoe.remaining}/{shoe.total_cards} remaining · "
        f"RC {shoe.running_count():+d} · TC {shoe.true_count():+.1f}"
    )
    if st.sidebar.button("Reshuffle shoe"):
        s["shoe"] = _new_shoe(s["cfg"])
        _emit(s, events.SHOE_RESHUFFLE, {"decks": s["cfg"].decks})
        _toast(s, "info", "Shoe reshuffled.")

    st.sidebar.divider()
    st.sidebar.caption(f"Session: {s['session_id'][:8]}… · Events: {cfg.event_log}")


def _render_dealer_panel(s: dict[str, Any]) -> None:
    round_: Round | None = s["round"]
    hide_hole = (
        round_ is not None
        and round_.phase in (GamePhase.DEALING, GamePhase.PLAYER_ACTIONS)
    )
    with st.container(border=True):
        st.markdown("### Dealer")
        if round_ is None or not round_.dealer.cards:
            st.caption("Waiting for deal…")
            return
        st.markdown(_hand_html(round_.dealer, hide_hole=hide_hole), unsafe_allow_html=True)
        if not hide_hole:
            dealer_total = round_.dealer.total()
            soft = " soft" if round_.dealer.is_soft() and dealer_total <= 21 else ""
            st.markdown(f"**Total:** {dealer_total}{soft} · *{round_.dealer.state.value}*")
        else:
            st.caption("Hole card hidden until dealer's turn.")


def _player_card_class(hand: Hand, is_active: bool, outcome: Outcome | None) -> str:
    border = "#1fb45f" if is_active else "#dddddd"
    if outcome is not None:
        border = _OUTCOME_COLOR[outcome]
    return (
        f"border:2px solid {border};border-radius:12px;padding:12px 14px 4px;"
        "background:#fafafa;margin-bottom:8px;"
    )


def _render_player_panel(s: dict[str, Any], player: Player, active_player: Player | None) -> None:
    round_: Round | None = s["round"]
    results = s.get("results")
    result_meta = s.get("result_meta", {})
    is_active_player = active_player is not None and active_player.name == player.name

    with st.container(border=False):
        header_bits = [f"**{player.name}**"]
        if s["bets"].get(player.name):
            header_bits.append(f"· bet {s['bets'][player.name]:g}")
        header_bits.append(f"· chips {player.chips:+g}")
        st.markdown(" ".join(header_bits))

        for idx, hand in enumerate(player.hands):
            outcome = results.get((player.name, idx)) if results else None
            active_hand = (
                is_active_player
                and round_ is not None
                and round_.phase is GamePhase.PLAYER_ACTIONS
                and idx == player.active_hand_index
            )
            css = _player_card_class(hand, active_hand, outcome)
            st.markdown(f"<div style='{css}'>", unsafe_allow_html=True)
            label = f"Hand {idx + 1}" if len(player.hands) > 1 else "Hand"
            st.markdown(f"**{label}**", help="Click action buttons below")
            if hand.cards:
                st.markdown(_hand_html(hand), unsafe_allow_html=True)
                total = hand.total()
                soft = " soft" if hand.is_soft() and total <= 21 else ""
                st.markdown(
                    f"Total: **{total}**{soft} · *{hand.state.value}*"
                )
            else:
                st.caption("Waiting for deal…")

            if outcome is not None:
                meta = result_meta.get((player.name, idx), {})
                delta = meta.get("chips_delta", 0)
                color = _OUTCOME_COLOR[outcome]
                label_txt = _OUTCOME_LABEL[outcome]
                st.markdown(
                    f"<div style='margin:6px 0;padding:6px 10px;border-radius:6px;"
                    f"background:{color};color:#fff;font-weight:700;display:inline-block;'>"
                    f"{label_txt} · {delta:+g} chips"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            st.markdown("</div>", unsafe_allow_html=True)

        if active_hand_actions_enabled(round_, player):
            _render_action_buttons(s, player)


def active_hand_actions_enabled(round_: Round | None, player: Player) -> bool:
    if round_ is None:
        return False
    if round_.phase is not GamePhase.PLAYER_ACTIONS:
        return False
    active = round_.active_player()
    if active is None or active.name != player.name:
        return False
    # If the active hand is still waiting on a replacement card (post-split),
    # no actions are available yet.
    return len(player.active_hand.cards) >= 2


def _render_action_buttons(s: dict[str, Any], player: Player) -> None:
    round_: Round = s["round"]
    hand = player.active_hand
    dealer_up = round_.dealer.cards[0] if round_.dealer.cards else None
    suggestion: Action | None = None
    if dealer_up is not None:
        suggestion = recommend(hand, dealer_up)
        # Streamlit re-runs the full script on every interaction, so guard the
        # event emit against re-firing when nothing about the decision changed.
        rec_key = (
            player.name,
            player.active_hand_index,
            tuple(c.short for c in hand.cards),
            dealer_up.short,
            suggestion.value,
        )
        if s.get("last_recommendation_key") != rec_key:
            s["last_recommendation_key"] = rec_key
            _emit(
                s,
                events.RECOMMENDATION,
                {
                    "player": player.name,
                    "hand": [c.short for c in hand.cards],
                    "dealer_up": dealer_up.short,
                    "suggested": suggestion.value,
                },
            )
        st.caption(f"Suggested: **{suggestion.value.upper()}**")

    cols = st.columns(5)

    def _label(action: Action) -> str:
        base = action.value.title()
        return f"✅ {base}" if suggestion is action else base

    with cols[0]:
        if st.button(_label(Action.HIT), key=f"hit_{player.name}", use_container_width=True):
            _pick_player_action(s, player, Action.HIT)
            st.rerun()
    with cols[1]:
        if st.button(_label(Action.STAND), key=f"stand_{player.name}", use_container_width=True):
            _pick_player_action(s, player, Action.STAND)
            st.rerun()
    with cols[2]:
        if st.button(
            _label(Action.DOUBLE),
            key=f"double_{player.name}",
            use_container_width=True,
            disabled=not hand.can_double(),
        ):
            _pick_player_action(s, player, Action.DOUBLE)
            st.rerun()
    with cols[3]:
        # The engine only allows splitting identical-rank pairs
        # (``hand.is_pair()``), so trust ``can_split`` directly — enabling the
        # button on ten-value non-pairs like K+Q would crash the engine.
        can_split = hand.can_split()
        if st.button(
            _label(Action.SPLIT),
            key=f"split_{player.name}",
            use_container_width=True,
            disabled=not can_split,
        ):
            _pick_player_action(s, player, Action.SPLIT)
            st.rerun()
    with cols[4]:
        if st.button(
            _label(Action.SURRENDER),
            key=f"surrender_{player.name}",
            use_container_width=True,
            disabled=not hand.can_surrender(),
        ):
            _pick_player_action(s, player, Action.SURRENDER)
            st.rerun()


def _render_scan_bar(s: dict[str, Any]) -> None:
    round_: Round | None = s["round"]
    if round_ is None:
        return

    prompt: str | None = None
    scan_handler = _scan_into_round
    if round_.phase is GamePhase.DEALING:
        target = round_.next_deal_target
        if target is not None:
            name = "dealer" if target[1] is None else target[0]
            prompt = f"Scan card for **{name}** (initial deal)"
    elif s.get("pending_split_deal"):
        prompt = (
            f"Scan replacement card for **{s['pending_split_deal']['player']}** "
            "(after split)"
        )
        scan_handler = _handle_pending_split_card
    elif round_.phase is GamePhase.PLAYER_ACTIONS and s.get("pending_action_card"):
        pa = s["pending_action_card"]
        prompt = f"Scan card for **{pa['player']}** — {pa['action'].value}"
    elif round_.phase is GamePhase.DEALER_PLAY:
        cfg: Config = s["cfg"]
        if round_.dealer_should_hit(cfg.dealer_hits_soft_17):
            prompt = "Scan card for **dealer**"
        else:
            # Dealer stands; settle now.
            _run_dealer_and_settle(s)
            return

    if prompt is None:
        return

    with st.container(border=True):
        st.markdown(f"#### {prompt}")
        with st.form(key="scan_form", clear_on_submit=True):
            raw = st.text_input(
                "Barcode",
                placeholder="e.g. AS, 10H, KC",
                label_visibility="collapsed",
            )
            submit = st.form_submit_button("Scan", use_container_width=True)
            if submit and raw:
                scan_handler(s, raw)
                st.rerun()

        with st.expander("Manual entry (no scanner)"):
            _render_manual_entry(s, scan_handler)


def _render_manual_entry(
    s: dict[str, Any],
    scan_handler: Any,
) -> None:
    ranks = list(Rank)
    suits = list(Suit)
    cols = st.columns(len(suits))
    for ci, suit in enumerate(suits):
        with cols[ci]:
            st.markdown(f"**{suit.glyph}**")
            for r in ranks:
                label = f"{r.value}{suit.glyph}"
                if st.button(
                    label,
                    key=f"btn_{r.value}{suit.value}_{id(scan_handler)}",
                    use_container_width=True,
                ):
                    scan_handler(s, f"{r.value}{suit.value}")
                    st.rerun()


def _render_betting_panel(s: dict[str, Any]) -> None:
    """Pre-round controls: per-player bets + Deal button."""
    st.markdown("### Betting phase")
    cols = st.columns(max(1, s["num_players"]))
    for i, name in enumerate(s["player_names"]):
        with cols[i]:
            default = float(s["bets"].get(name, s["default_bet"]))
            bet = st.number_input(
                f"{name} bet",
                min_value=0.0,
                max_value=100000.0,
                value=default,
                step=1.0,
                key=f"bet_{i}",
            )
            s["bets"][name] = float(bet)

    left, right = st.columns([1, 1])
    with left:
        if st.button("🎴 Deal round", type="primary", use_container_width=True):
            _start_round(s)
            st.rerun()
    with right:
        if st.button("Reset table (keep setup)", use_container_width=True):
            _reset_game(s)
            st.rerun()


def _render_round_panel(s: dict[str, Any]) -> None:
    round_: Round = s["round"]
    active_player = round_.active_player()

    phase_label = {
        GamePhase.DEALING: "Initial deal",
        GamePhase.PLAYER_ACTIONS: f"Acting: **{active_player.name}**" if active_player else "Player actions",
        GamePhase.DEALER_PLAY: "Dealer plays",
        GamePhase.SETTLEMENT: "Settling…",
        GamePhase.COMPLETE: "Round complete",
    }.get(round_.phase, round_.phase.value)
    st.markdown(f"**Round {s['round_number']}** · {phase_label}")

    _render_dealer_panel(s)

    cols = st.columns(max(1, len(round_.players)))
    for i, player in enumerate(round_.players):
        with cols[i]:
            _render_player_panel(s, player, active_player)

    _render_scan_bar(s)

    if round_.phase is GamePhase.COMPLETE and st.button(
        "🔁 New round", type="primary"
    ):
        _reset_game(s)
        st.rerun()


def _render_header(s: dict[str, Any]) -> None:
    cfg: Config = s["cfg"]
    dealer_rule = "H17" if cfg.dealer_hits_soft_17 else "S17"
    st.markdown(
        "<div style='display:flex;justify-content:space-between;align-items:center;"
        "padding:8px 16px;background:linear-gradient(90deg,#0b5f2e,#14854b);"
        "color:#fff;border-radius:10px;margin-bottom:12px;'>"
        f"<div style='font-size:22px;font-weight:700;'>🃏 Blackjack Dealer</div>"
        f"<div style='opacity:0.9'>Shoe {cfg.decks}D · {dealer_rule} · AWS: "
        f"{cfg.aws_mode}</div></div>",
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #


def run() -> None:
    st.set_page_config(page_title="Blackjack Dealer", layout="wide")
    s = _get_state()
    _init_state(s)
    _render_header(s)
    _render_sidebar(s)
    _render_toasts(s)

    round_: Round | None = s["round"]
    if round_ is None or round_.phase is GamePhase.BETTING:
        _render_betting_panel(s)
    else:
        _render_round_panel(s)

    # Exist purely to silence linter for unused import; keeps Path around for
    # anyone extending this module with file-based persistence.
    _ = Path


if __name__ == "__main__":
    run()
