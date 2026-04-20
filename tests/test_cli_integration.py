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
