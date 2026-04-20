import pytest

from blackjack_scanner.card import (
    BarcodeError,
    Card,
    HumanBarcodeParser,
    NumericBarcodeParser,
    Rank,
    Suit,
    get_parser,
)


class TestHumanParser:
    def setup_method(self) -> None:
        self.p = HumanBarcodeParser()

    def test_basic_ranks(self) -> None:
        assert self.p.parse("AS") == Card(Rank.ACE, Suit.SPADES, raw_barcode="AS")
        assert self.p.parse("2H") == Card(Rank.TWO, Suit.HEARTS, raw_barcode="2H")
        assert self.p.parse("9D") == Card(Rank.NINE, Suit.DIAMONDS, raw_barcode="9D")
        assert self.p.parse("KC") == Card(Rank.KING, Suit.CLUBS, raw_barcode="KC")

    def test_ten_aliases(self) -> None:
        assert self.p.parse("TH").rank is Rank.TEN
        assert self.p.parse("10H").rank is Rank.TEN
        assert self.p.parse("10h").rank is Rank.TEN

    def test_lowercase_and_whitespace(self) -> None:
        assert self.p.parse("  ac \n").rank is Rank.ACE
        assert self.p.parse("qd").short == "QD"

    def test_strips_nonalnum_suffix(self) -> None:
        assert self.p.parse("AS\r\n").rank is Rank.ACE
        assert self.p.parse("AS\t").rank is Rank.ACE

    @pytest.mark.parametrize("bad", ["", "   ", "XZ", "1Z", "15H", "TT"])
    def test_bad_inputs_raise(self, bad: str) -> None:
        with pytest.raises(BarcodeError):
            self.p.parse(bad)


class TestNumericParser:
    def setup_method(self) -> None:
        self.p = NumericBarcodeParser()

    def test_basic(self) -> None:
        c = self.p.parse("0111")
        assert c.rank is Rank.ACE
        assert c.suit is Suit.SPADES
        assert c.deck_id == 1

    def test_without_deck_id(self) -> None:
        c = self.p.parse("011")
        assert c.rank is Rank.ACE
        assert c.suit is Suit.SPADES
        assert c.deck_id is None

    def test_all_suits(self) -> None:
        assert self.p.parse("0111").suit is Suit.SPADES
        assert self.p.parse("0121").suit is Suit.HEARTS
        assert self.p.parse("0131").suit is Suit.DIAMONDS
        assert self.p.parse("0141").suit is Suit.CLUBS

    def test_all_ranks(self) -> None:
        ranks = [
            Rank.ACE, Rank.TWO, Rank.THREE, Rank.FOUR, Rank.FIVE, Rank.SIX,
            Rank.SEVEN, Rank.EIGHT, Rank.NINE, Rank.TEN, Rank.JACK, Rank.QUEEN, Rank.KING,
        ]
        for i, r in enumerate(ranks, start=1):
            code = f"{i:02d}11"
            assert self.p.parse(code).rank is r

    def test_ignores_extra_digits(self) -> None:
        # Trailing checksum digits should not break parsing.
        assert self.p.parse("011199").rank is Rank.ACE

    def test_ignores_non_digits(self) -> None:
        assert self.p.parse("01-1-1").rank is Rank.ACE

    @pytest.mark.parametrize("bad", ["", "00", "0010", "1451", "0150", "abcd"])
    def test_bad_inputs_raise(self, bad: str) -> None:
        with pytest.raises(BarcodeError):
            self.p.parse(bad)


def test_get_parser_lookup() -> None:
    assert isinstance(get_parser("human"), HumanBarcodeParser)
    assert isinstance(get_parser("numeric"), NumericBarcodeParser)
    with pytest.raises(KeyError):
        get_parser("nope")
