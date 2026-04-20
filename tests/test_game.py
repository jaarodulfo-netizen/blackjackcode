from blackjack_scanner.card import Card, Rank, Suit
from blackjack_scanner.game import (
    Action,
    GamePhase,
    Hand,
    HandState,
    Outcome,
    Player,
    Round,
)


def c(rank: Rank, suit: Suit = Suit.SPADES) -> Card:
    return Card(rank, suit)


class TestHand:
    def test_empty_hand_total_zero(self) -> None:
        assert Hand().total() == 0

    def test_simple_total(self) -> None:
        h = Hand(cards=[c(Rank.FIVE), c(Rank.SEVEN)])
        assert h.total() == 12
        assert not h.is_soft()

    def test_face_cards_are_ten(self) -> None:
        h = Hand(cards=[c(Rank.KING), c(Rank.QUEEN)])
        assert h.total() == 20

    def test_soft_ace(self) -> None:
        h = Hand(cards=[c(Rank.ACE), c(Rank.SIX)])
        assert h.total() == 17
        assert h.is_soft()

    def test_soft_to_hard_after_bust_risk(self) -> None:
        h = Hand(cards=[c(Rank.ACE), c(Rank.SIX), c(Rank.TEN)])
        assert h.total() == 17
        assert not h.is_soft()

    def test_multiple_aces(self) -> None:
        h = Hand(cards=[c(Rank.ACE), c(Rank.ACE)])
        assert h.total() == 12
        h.add(c(Rank.NINE))
        assert h.total() == 21

    def test_blackjack_detection(self) -> None:
        h = Hand()
        h.add(c(Rank.ACE))
        h.add(c(Rank.KING))
        assert h.state is HandState.BLACKJACK
        assert h.total() == 21

    def test_bust_detection(self) -> None:
        h = Hand()
        h.add(c(Rank.TEN))
        h.add(c(Rank.NINE))
        h.add(c(Rank.FIVE))
        assert h.state is HandState.BUST
        assert h.total() == 24

    def test_pair_detection(self) -> None:
        assert Hand(cards=[c(Rank.EIGHT), c(Rank.EIGHT)]).is_pair()
        assert not Hand(cards=[c(Rank.EIGHT), c(Rank.NINE)]).is_pair()

    def test_ten_pair_detection(self) -> None:
        assert Hand(cards=[c(Rank.KING), c(Rank.JACK)]).is_ten_pair()
        assert Hand(cards=[c(Rank.KING), c(Rank.TEN)]).is_ten_pair()
        assert not Hand(cards=[c(Rank.NINE), c(Rank.TEN)]).is_ten_pair()


class TestRoundDealing:
    def _mk(self) -> Round:
        return Round(players=[Player("A"), Player("B")])

    def test_deal_order(self) -> None:
        r = self._mk()
        r.start_dealing()
        # player A, B, dealer, player A, B, dealer
        assert r.next_deal_target == ("A", 0)
        r.deal_next(c(Rank.FIVE))
        assert r.next_deal_target == ("B", 0)
        r.deal_next(c(Rank.SIX))
        assert r.next_deal_target == ("dealer", None)
        r.deal_next(c(Rank.SEVEN))
        assert r.next_deal_target == ("A", 0)
        r.deal_next(c(Rank.EIGHT))
        assert r.next_deal_target == ("B", 0)
        r.deal_next(c(Rank.NINE))
        assert r.next_deal_target == ("dealer", None)
        r.deal_next(c(Rank.TEN))
        # All dealt: transition to PLAYER_ACTIONS.
        assert r.phase is GamePhase.PLAYER_ACTIONS
        assert r.players[0].hands[0].total() == 13  # 5 + 8
        assert r.players[1].hands[0].total() == 15  # 6 + 9
        assert r.dealer.total() == 17  # 7 + 10

    def test_dealer_blackjack_skips_player_actions(self) -> None:
        r = Round(players=[Player("A")])
        r.start_dealing()
        # A: 5, 8 ; dealer: A, K
        r.deal_next(c(Rank.FIVE))      # A card 1
        r.deal_next(c(Rank.ACE))       # dealer upcard
        r.deal_next(c(Rank.EIGHT))     # A card 2
        r.deal_next(c(Rank.KING))      # dealer hole -> blackjack
        assert r.phase is GamePhase.SETTLEMENT
        assert r.dealer.state is HandState.BLACKJACK

    def test_sole_player_blackjack_goes_to_settlement(self) -> None:
        # When every player has a natural and dealer does not, there is no play
        # left to resolve -> go straight to settlement.
        r = Round(players=[Player("A")])
        r.start_dealing()
        r.deal_next(c(Rank.ACE))       # A card 1
        r.deal_next(c(Rank.SEVEN))     # dealer upcard
        r.deal_next(c(Rank.KING))      # A card 2 -> blackjack
        r.deal_next(c(Rank.NINE))      # dealer hole
        assert r.phase is GamePhase.SETTLEMENT
        assert r.players[0].hands[0].state is HandState.BLACKJACK

    def test_one_of_two_players_blackjack_still_allows_actions(self) -> None:
        # Two players, one gets BJ, one doesn't -> other player still plays.
        r = Round(players=[Player("A"), Player("B")])
        r.start_dealing()
        r.deal_next(c(Rank.ACE))       # A card 1
        r.deal_next(c(Rank.FIVE))      # B card 1
        r.deal_next(c(Rank.SEVEN))     # dealer up
        r.deal_next(c(Rank.KING))      # A card 2 -> BJ
        r.deal_next(c(Rank.SIX))       # B card 2 -> 11
        r.deal_next(c(Rank.NINE))      # dealer hole
        assert r.phase is GamePhase.PLAYER_ACTIONS
        assert r.active_player() is not None and r.active_player().name == "B"


class TestRoundActions:
    def _begin(self, player_cards: list[Card], dealer_cards: list[Card]) -> Round:
        r = Round(players=[Player("A")])
        r.start_dealing()
        r.deal_next(player_cards[0])
        r.deal_next(dealer_cards[0])
        r.deal_next(player_cards[1])
        r.deal_next(dealer_cards[1])
        return r

    def test_hit_and_stand(self) -> None:
        r = self._begin([c(Rank.FIVE), c(Rank.SEVEN)], [c(Rank.TEN), c(Rank.SEVEN)])
        r.apply_action("A", Action.HIT, card=c(Rank.SIX))  # 5+7+6 = 18
        r.apply_action("A", Action.STAND)
        assert r.phase is GamePhase.DEALER_PLAY
        assert r.players[0].hands[0].state is HandState.STOOD
        assert r.players[0].hands[0].total() == 18

    def test_double(self) -> None:
        r = self._begin([c(Rank.FIVE), c(Rank.SIX)], [c(Rank.SIX), c(Rank.TEN)])
        p = r.players[0]
        p.hands[0].bet = 10.0
        r.apply_action("A", Action.DOUBLE, card=c(Rank.TEN))  # 5+6+10 = 21
        assert p.hands[0].doubled
        assert p.hands[0].bet == 20.0
        assert p.hands[0].is_finished()
        assert r.phase is GamePhase.DEALER_PLAY

    def test_split(self) -> None:
        r = self._begin([c(Rank.EIGHT), c(Rank.EIGHT)], [c(Rank.SIX), c(Rank.TEN)])
        p = r.players[0]
        p.hands[0].bet = 10.0
        r.apply_action("A", Action.SPLIT)
        assert len(p.hands) == 2
        assert all(h.is_split for h in p.hands)
        assert all(len(h.cards) == 1 for h in p.hands)
        # Deal a card to first split hand and stand.
        p.hands[0].add(c(Rank.TEN))
        r.apply_action("A", Action.STAND)
        assert p.active_hand_index == 1
        p.hands[1].add(c(Rank.NINE))
        r.apply_action("A", Action.STAND)
        assert r.phase is GamePhase.DEALER_PLAY

    def test_surrender(self) -> None:
        r = self._begin([c(Rank.TEN), c(Rank.SIX)], [c(Rank.TEN), c(Rank.SEVEN)])
        r.apply_action("A", Action.SURRENDER)
        assert r.players[0].hands[0].state is HandState.SURRENDERED
        assert r.phase is GamePhase.DEALER_PLAY


class TestDealerPlay:
    def test_dealer_stands_on_hard_17(self) -> None:
        r = Round(players=[Player("A")])
        r.dealer = Hand(cards=[c(Rank.TEN), c(Rank.SEVEN)])
        assert not r.dealer_should_hit(hits_soft_17=False)

    def test_dealer_hits_16(self) -> None:
        r = Round(players=[Player("A")])
        r.dealer = Hand(cards=[c(Rank.TEN), c(Rank.SIX)])
        assert r.dealer_should_hit(hits_soft_17=False)

    def test_dealer_soft_17_s17_vs_h17(self) -> None:
        r = Round(players=[Player("A")])
        r.dealer = Hand(cards=[c(Rank.ACE), c(Rank.SIX)])
        assert not r.dealer_should_hit(hits_soft_17=False)
        assert r.dealer_should_hit(hits_soft_17=True)


class TestSettlement:
    def _force_phase(self, r: Round, phase: GamePhase) -> None:
        r.phase = phase

    def test_player_win_dealer_bust(self) -> None:
        r = Round(players=[Player("A")])
        r.players[0].hands[0].cards = [c(Rank.TEN), c(Rank.EIGHT)]
        r.players[0].hands[0].bet = 10
        r.players[0].hands[0].state = HandState.STOOD
        r.dealer.cards = [c(Rank.TEN), c(Rank.SEVEN), c(Rank.SEVEN)]
        r.dealer.state = HandState.BUST
        self._force_phase(r, GamePhase.SETTLEMENT)
        outcomes = r.settle()
        assert outcomes[("A", 0)] is Outcome.PLAYER_WIN
        assert r.players[0].chips == 10

    def test_player_blackjack_pays_3_to_2(self) -> None:
        r = Round(players=[Player("A")])
        r.players[0].hands[0].cards = [c(Rank.ACE), c(Rank.KING)]
        r.players[0].hands[0].bet = 10
        r.players[0].hands[0].state = HandState.BLACKJACK
        r.dealer.cards = [c(Rank.TEN), c(Rank.EIGHT)]
        r.dealer.state = HandState.STOOD
        self._force_phase(r, GamePhase.SETTLEMENT)
        outcomes = r.settle()
        assert outcomes[("A", 0)] is Outcome.PLAYER_BLACKJACK
        assert r.players[0].chips == 15

    def test_push(self) -> None:
        r = Round(players=[Player("A")])
        r.players[0].hands[0].cards = [c(Rank.TEN), c(Rank.NINE)]
        r.players[0].hands[0].bet = 10
        r.players[0].hands[0].state = HandState.STOOD
        r.dealer.cards = [c(Rank.TEN), c(Rank.NINE)]
        r.dealer.state = HandState.STOOD
        self._force_phase(r, GamePhase.SETTLEMENT)
        outcomes = r.settle()
        assert outcomes[("A", 0)] is Outcome.PUSH
        assert r.players[0].chips == 0

    def test_bust_loses_even_if_dealer_busts(self) -> None:
        r = Round(players=[Player("A")])
        r.players[0].hands[0].cards = [c(Rank.TEN), c(Rank.SEVEN), c(Rank.SEVEN)]
        r.players[0].hands[0].bet = 10
        r.players[0].hands[0].state = HandState.BUST
        r.dealer.cards = [c(Rank.TEN), c(Rank.SEVEN), c(Rank.SEVEN)]
        r.dealer.state = HandState.BUST
        self._force_phase(r, GamePhase.SETTLEMENT)
        outcomes = r.settle()
        assert outcomes[("A", 0)] is Outcome.DEALER_WIN
        assert r.players[0].chips == -10

    def test_surrender_loses_half(self) -> None:
        r = Round(players=[Player("A")])
        r.players[0].hands[0].cards = [c(Rank.TEN), c(Rank.SIX)]
        r.players[0].hands[0].bet = 10
        r.players[0].hands[0].state = HandState.SURRENDERED
        r.dealer.cards = [c(Rank.TEN), c(Rank.SEVEN)]
        r.dealer.state = HandState.STOOD
        self._force_phase(r, GamePhase.SETTLEMENT)
        outcomes = r.settle()
        assert outcomes[("A", 0)] is Outcome.SURRENDER
        assert r.players[0].chips == -5
