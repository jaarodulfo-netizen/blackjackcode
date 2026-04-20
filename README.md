# blackjackcode

Python 3.10+ blackjack app that reads barcoded cards from an HID scanner
(keyboard-wedge mode), runs a full multi-player blackjack engine with
basic-strategy recommendations, and emits structured events to a pluggable
AWS event sink (stubbed JSONL by default, API Gateway + Lambda or DynamoDB
when configured).

## Install

```bash
pip install -e ".[dev]"          # engine + CLI + tests
pip install -e ".[ui]"           # add the Streamlit dealer UI
pip install -e ".[aws]"          # add DynamoDB (boto3) support
```

## CLI (scanner)

```bash
blackjack-scanner
```

Scan or type one barcode per line (e.g. `AS`, `10H`, `KC`). Environment
variables configure decks, dealer rule, parser, and AWS sink — see
`src/blackjack_scanner/config.py`.

## Streamlit dealer UI

A big-screen dealer interface wired to the same engine:

```bash
pip install -e ".[ui]"
streamlit run app.py
# opens http://localhost:8501
```

Or via the installed console script:

```bash
blackjack-scanner-ui
```

Features:

- Betting phase with 1–4 players and configurable bets.
- Live card rendering with suit glyphs and totals (soft/hard).
- Per-hand action buttons: **Hit**, **Stand**, **Double**, **Split**,
  **Surrender** (disabled when not legal).
- Basic-strategy recommendation tag on the active hand.
- Dealer panel with hidden hole card until dealer's turn.
- Auto-settlement with **WIN / LOSE / PUSH / BLACKJACK / SURRENDER** badges
  and per-hand chip deltas.
- Shoe tracker (Hi-Lo running / true count) and reshuffle control in the
  sidebar.
- Every scan emits the same JSON events the CLI produces, so the UI is a
  drop-in for a real HID keyboard-wedge scanner — just focus the scan field
  and the scanner's Enter-terminated output will be submitted like any
  typed input.

Card input format is identical to the CLI: `AS`, `TH` (or `10H`), `KC`,
etc. Manual-entry buttons are also provided for development.
