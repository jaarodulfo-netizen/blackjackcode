"""End-to-end smoke test: pipe a full round through the CLI and assert the
expected events are emitted."""

from __future__ import annotations

import io
from pathlib import Path

from blackjack_scanner import events as evt_mod
from blackjack_scanner.aws_client import StubEventSink
from blackjack_scanner.cli import _run_loop, build_state
from blackjack_scanner.config import Config


def _run(tmp_path: Path, scripted_input: str) -> tuple[str, list[dict[str, object]]]:
    log_path = tmp_path / "events.jsonl"
    sink = StubEventSink(log_path)
    cfg = Config(event_log=str(log_path))
    in_ = io.StringIO(scripted_input)
    out = io.StringIO()
    state = build_state(cfg, sink=sink, in_=in_, out=out)
    code = _run_loop(state)
    sink.close()
    assert code == 0
    events: list[dict[str, object]] = []
    if log_path.exists():
        for line in log_path.read_text().splitlines():
            if line.strip():
                import json
                events.append(json.loads(line))
    return out.getvalue(), events


def test_full_round_player_stands_dealer_stands(tmp_path: Path) -> None:
    """
    Player A: 10, 9  -> stands on 19.
    Dealer:   10, 8  -> stands on 18.
    Result: player wins.
    """
    script = "\n".join([
        "1",          # number of players
        "A",          # player name
        "TS",         # A card 1
        "TH",         # dealer upcard
        "9D",         # A card 2
        "8C",         # dealer hole
        "stand",      # A action
        "n",          # no more rounds
        "",
    ])
    output, events = _run(tmp_path, script)
    assert "Results" in output
    # Find the hand result event.
    results = [e for e in events if e["type"] == evt_mod.HAND_RESULT]
    assert len(results) == 1
    payload = results[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["outcome"] == "player_win"
    assert payload["total"] == 19


def test_full_round_player_blackjack(tmp_path: Path) -> None:
    """Player dealt blackjack, dealer dealt 20 -> player wins 3:2."""
    script = "\n".join([
        "1",
        "A",
        "AS",         # A card 1
        "TH",         # dealer upcard
        "KD",         # A card 2 -> blackjack
        "9C",         # dealer hole -> 19
        # No player action needed (blackjack), no dealer hit needed (>=17).
        "n",
        "",
    ])
    _output, events = _run(tmp_path, script)
    results = [e for e in events if e["type"] == evt_mod.HAND_RESULT]
    assert len(results) == 1
    payload = results[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["outcome"] == "player_blackjack"


def test_full_round_player_busts(tmp_path: Path) -> None:
    """Player hits into a bust."""
    script = "\n".join([
        "1",
        "A",
        "TS",        # A card 1
        "6H",        # dealer upcard
        "6D",        # A card 2 -> 16
        "TC",        # dealer hole -> 16
        "hit",       # A action
        "QS",        # hit card -> 26 bust
        # Dealer has 16 and must hit; scan one card to take to >=17.
        "7H",        # dealer hit -> 23 bust (but player already bust so loses)
        "n",
        "",
    ])
    _output, events = _run(tmp_path, script)
    results = [e for e in events if e["type"] == evt_mod.HAND_RESULT]
    assert len(results) == 1
    payload = results[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["outcome"] == "dealer_win"


def test_split_hand_action_events_report_correct_hand_index(tmp_path: Path) -> None:
    """After splitting 8s, each hand.action event must carry the hand_index of
    the hand the action was applied to — not the next hand that becomes active
    when apply_action advances the cursor."""
    script = "\n".join([
        "1",
        "A",
        "8S",         # A card 1
        "TH",         # dealer upcard
        "8D",         # A card 2 -> pair of 8s
        "9C",         # dealer hole -> 19
        "split",      # split the pair
        "5C",         # replacement card for split hand 1 -> 8 + 5 = 13
        "stand",      # stand on hand 1 (13)
        "5D",         # replacement card for split hand 2 -> 8 + 5 = 13
        "stand",      # stand on hand 2 (13)
        "n",
        "",
    ])
    _output, events = _run(tmp_path, script)
    actions = [e for e in events if e["type"] == evt_mod.HAND_ACTION]
    # Expect: split on hand 0, stand on hand 0, stand on hand 1.
    assert len(actions) == 3
    split_payload = actions[0]["payload"]
    stand_a_payload = actions[1]["payload"]
    stand_b_payload = actions[2]["payload"]
    assert isinstance(split_payload, dict)
    assert isinstance(stand_a_payload, dict)
    assert isinstance(stand_b_payload, dict)
    assert split_payload["action"] == "split"
    assert split_payload["hand_index"] == 0
    assert stand_a_payload["action"] == "stand"
    assert stand_a_payload["hand_index"] == 0, (
        "stand on first split hand must report hand_index=0, not the "
        "next active hand's index"
    )
    assert stand_b_payload["action"] == "stand"
    assert stand_b_payload["hand_index"] == 1


def test_recommendation_emitted(tmp_path: Path) -> None:
    """Strategy recommendation is logged as an event."""
    script = "\n".join([
        "1",
        "A",
        "TS", "6H", "6D", "TC",
        "stand",
        "7H",          # dealer hit
        "n",
        "",
    ])
    _output, events = _run(tmp_path, script)
    recs = [e for e in events if e["type"] == evt_mod.RECOMMENDATION]
    assert len(recs) >= 1
    payload = recs[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["dealer_up"] == "6H"
    # 16 vs 6 -> STAND per basic strategy.
    assert payload["suggested"] == "stand"
