import io

from blackjack_scanner.card import HumanBarcodeParser, Rank
from blackjack_scanner.scanner import Scanner, iter_lines, parse_line


def test_parse_line_ok() -> None:
    ev = parse_line("AS", HumanBarcodeParser())
    assert ev.ok
    assert ev.card is not None and ev.card.rank is Rank.ACE


def test_parse_line_empty() -> None:
    ev = parse_line("   ", HumanBarcodeParser())
    assert not ev.ok
    assert ev.error == "empty scan"


def test_parse_line_bad() -> None:
    ev = parse_line("XX", HumanBarcodeParser())
    assert not ev.ok
    assert ev.error


def test_scanner_reads_from_stream() -> None:
    stream = io.StringIO("AS\n2H\n\nKD\n")
    s = Scanner(HumanBarcodeParser(), stream=stream)
    events = list(s)
    assert len(events) == 4
    assert [e.ok for e in events] == [True, True, False, True]
    assert events[0].card is not None and events[0].card.short == "AS"
    assert events[1].card is not None and events[1].card.short == "2H"
    assert events[3].card is not None and events[3].card.short == "KD"


def test_scanner_eof() -> None:
    s = Scanner(HumanBarcodeParser(), stream=io.StringIO(""))
    assert s.scan() is None


def test_iter_lines_helper() -> None:
    parser = HumanBarcodeParser()
    evs = list(iter_lines(["AS", "KD"], parser))
    assert all(e.ok for e in evs)
    assert evs[0].card is not None and evs[0].card.short == "AS"
