# Testing the blackjack-scanner CLI

Shell-only tool — no GUI, no recording needed. Test by piping scripted scans into stdin with `--no-tty` and asserting on stdout + the JSONL event stream.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The `blackjack-scanner` entry point is installed into the venv's `bin/`.

## Run commands

- Lint: `ruff check . && mypy src`
- Tests: `pytest`
- Smoke (one round, player wins): `printf '1\nJuan\nTS\nTH\n9C\n8D\nstand\nn\n' | blackjack-scanner --no-tty`
- Events go to `./events.jsonl` by default. Override with `BJS_EVENT_LOG=/tmp/bjs/events.jsonl`.

## CLI stdin protocol

Order of prompts (so scripted input must match exactly):

1. `Number of players [1]:` — integer or blank
2. `Player N name [PN]:` — name or blank (one per player)
3. Dealing loop — 4 scans in order: **player1, dealer up, player1, dealer hole** (extend for multi-player)
4. Per active hand: `action (hit/stand/double/surrender) [suggested: X]:` — action keyword; blank accepts the suggestion
5. If action is `hit` or `double`: an extra `scan card for hit:` prompt
6. Dealer play: `Scan card for dealer:` until dealer stands
7. `Another round? [Y/n]:` — `n` to exit

Barcodes use the `human` parser by default: `AS`, `TH`, `9C`, `KD`, etc. Aliases: `10H` == `TH`. Switch with `BJS_PARSER=numeric` for `RRSD` format (e.g. `0111` = A♠ deck 1).

## Adversarial testing patterns

The scanner engine is deterministic — every card is provided via stdin — so testing is about proving the engine reacts correctly to edge cases.

- **Strategy override** — feed a hand where basic strategy says stand (e.g. hard 17), then `hit` anyway, and assert the `recommendation` event's `suggested` field equals `stand` AND the `hand.action` event records `hit`. This proves the strategy engine ran AND the action override path is honored.
- **Bust** — same as above, but keep hitting until `state_after: bust` appears. Verify `hand.result.outcome: dealer_win` regardless of dealer total (busted player always loses).
- **Blackjack 3:2** — deal A + ten-valued to player, anything else to dealer. Verify `hand.result.outcome: player_blackjack` and `chips_delta: 1.5`.
- **Split** — deal a pair, then `split`, then provide two replacement cards (one per new hand) before the per-hand action prompt. The CLI prompts `Scan replacement card for <name> (after split):` before asking for action on each split hand.
- **Dealer S17 vs H17** — default is S17 (`BJS_DEALER_HITS_SOFT_17=false`). Flip to `true` and re-test a soft-17 dealer hand (e.g. A+6) to verify dealer hits it.

## Event schema assertions

Every event is `{type, ts, session_id, payload}`. Well-known types: `round.start`, `scan.ok`, `scan.error`, `hand.dealt`, `recommendation`, `hand.action`, `dealer.action`, `hand.result`, `round.end`, `shoe.reshuffle`.

Useful one-liner to summarize an event stream:

```bash
python -c "import json; from collections import Counter; events=[json.loads(l) for l in open('events.jsonl')]; print(Counter(e['type'] for e in events)); [print(e['type'].upper(), e['payload']) for e in events if e['type'] in {'recommendation','hand.action','hand.result','dealer.action'}]"
```

## AWS sinks

- `BJS_AWS_MODE=stub` (default) — writes JSONL to `BJS_EVENT_LOG` (default `./events.jsonl`). **Always test against stub first.**
- `BJS_AWS_MODE=apigateway` + `BJS_AWS_ENDPOINT=https://...` — POSTs each event via stdlib `urllib`.
- `BJS_AWS_MODE=dynamodb` + `BJS_AWS_TABLE=...` + `BJS_AWS_REGION=...` — writes via `boto3` (requires `pip install -e ".[aws]"`).

Live AWS modes might be broken and the stub sink is the safest testing surface — prefer testing AWS-bound events by parsing `events.jsonl` rather than hitting a real endpoint.

## Devin Secrets Needed

None for local testing. Real AWS sinks would need AWS credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) + `BJS_AWS_ENDPOINT` or `BJS_AWS_TABLE` — request these only when the user asks to verify against a real AWS environment.
