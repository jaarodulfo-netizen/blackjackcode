from blackjack_scanner.card import Card, Rank, Suit
from blackjack_scanner.deck import Shoe


def test_shoe_penetration() -> None:
    shoe = Shoe(decks=1, penetration=0.5)
    assert shoe.total_cards == 52
    assert not shoe.penetration_reached
    for _ in range(25):
        shoe.record(Card(Rank.FIVE, Suit.SPADES))
    assert not shoe.penetration_reached
    shoe.record(Card(Rank.FIVE, Suit.SPADES))
    assert shoe.penetration_reached


def test_shoe_running_count() -> None:
    shoe = Shoe(decks=1)
    # 5 low cards (+1 each), 2 high cards (-1 each), 1 neutral (0).
    for r in [Rank.TWO, Rank.THREE, Rank.FOUR, Rank.FIVE, Rank.SIX]:
        shoe.record(Card(r, Suit.SPADES))
    for r in [Rank.TEN, Rank.ACE]:
        shoe.record(Card(r, Suit.HEARTS))
    shoe.record(Card(Rank.EIGHT, Suit.CLUBS))
    assert shoe.running_count() == 5 - 2


def test_shoe_reset() -> None:
    shoe = Shoe(decks=2)
    shoe.record(Card(Rank.ACE, Suit.SPADES))
    shoe.reset()
    assert shoe.dealt_count == 0
    assert shoe.running_count() == 0
