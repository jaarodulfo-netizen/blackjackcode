from blackjack_scanner.card import Card, Rank, Suit
from blackjack_scanner.game import Action, Hand
from blackjack_scanner.strategy import recommend


def c(rank: Rank, suit: Suit = Suit.SPADES) -> Card:
    return Card(rank, suit)


def test_hard_16_vs_10_surrenders() -> None:
    h = Hand(cards=[c(Rank.TEN), c(Rank.SIX)])
    assert recommend(h, c(Rank.TEN)) is Action.SURRENDER


def test_hard_16_vs_6_stands() -> None:
    h = Hand(cards=[c(Rank.TEN), c(Rank.SIX)])
    assert recommend(h, c(Rank.SIX)) is Action.STAND


def test_hard_11_doubles_vs_anything() -> None:
    h = Hand(cards=[c(Rank.SIX), c(Rank.FIVE)])
    for up in [Rank.TWO, Rank.SIX, Rank.TEN, Rank.ACE]:
        assert recommend(h, c(up)) is Action.DOUBLE


def test_pair_of_8s_always_splits() -> None:
    h = Hand(cards=[c(Rank.EIGHT), c(Rank.EIGHT)])
    for up in [Rank.TWO, Rank.SEVEN, Rank.TEN, Rank.ACE]:
        assert recommend(h, c(up)) is Action.SPLIT


def test_pair_of_10s_never_splits() -> None:
    h = Hand(cards=[c(Rank.TEN), c(Rank.KING)])  # ten-pair
    for up in [Rank.TWO, Rank.SEVEN, Rank.TEN, Rank.ACE]:
        assert recommend(h, c(up)) is Action.STAND


def test_pair_of_aces_splits() -> None:
    h = Hand(cards=[c(Rank.ACE), c(Rank.ACE)])
    assert recommend(h, c(Rank.SIX)) is Action.SPLIT


def test_soft_18_vs_9_hits() -> None:
    h = Hand(cards=[c(Rank.ACE), c(Rank.SEVEN)])
    assert recommend(h, c(Rank.NINE)) is Action.HIT


def test_soft_18_vs_6_doubles() -> None:
    h = Hand(cards=[c(Rank.ACE), c(Rank.SEVEN)])
    assert recommend(h, c(Rank.SIX)) is Action.DOUBLE


def test_soft_18_vs_8_stands() -> None:
    h = Hand(cards=[c(Rank.ACE), c(Rank.SEVEN)])
    assert recommend(h, c(Rank.EIGHT)) is Action.STAND


def test_falls_back_to_hit_when_cannot_double() -> None:
    # 3 cards -> can't double any more; "D" code should become HIT.
    h = Hand(cards=[c(Rank.FOUR), c(Rank.FOUR), c(Rank.THREE)])  # hard 11
    assert recommend(h, c(Rank.SIX)) is Action.HIT


def test_hard_17_vs_ace_surrenders_if_allowed_else_stands() -> None:
    h = Hand(cards=[c(Rank.TEN), c(Rank.SEVEN)])
    assert recommend(h, c(Rank.ACE)) is Action.SURRENDER
    # Once the hand has taken another card, surrender is no longer allowed.
    h2 = Hand(cards=[c(Rank.FOUR), c(Rank.FOUR), c(Rank.NINE)])  # hard 17
    assert recommend(h2, c(Rank.ACE)) is Action.STAND
