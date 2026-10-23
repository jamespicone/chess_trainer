import random

import chess

from trainer.drill import Drill, Verdict
from trainer.repertoire import Repertoire

SAMPLE = """
1. e4 {Centre.} e5 {Black mirrors.}
2. Nf3 (2. Qh5?! {Too early.})
2... Nc6 (2... f6? {Weakens the king.} 3. Nxe5)
3. Bc4 *
"""


def make_drill(side: chess.Color, pgn: str = SAMPLE, seed: int = 0, **options) -> Drill:
    repertoire = Repertoire()
    repertoire.add_pgn(pgn, "test.pgn")
    return Drill(repertoire, side, rng=random.Random(seed), **options)


def uci(text: str) -> chess.Move:
    return chess.Move.from_uci(text)


def test_correct_move_is_played_and_its_comment_shown():
    drill = make_drill(chess.WHITE)
    assert drill.is_user_turn
    node = drill.try_move(uci("e2e4"))
    assert node.verdict is Verdict.CORRECT
    assert drill.current is node
    assert node.comments == ["Centre."]


def test_known_mistake_is_rejected_with_its_comment():
    drill = make_drill(chess.WHITE)
    drill.try_move(uci("e2e4"))
    drill.play_opponent_move()  # e5 is the only choice
    node = drill.try_move(uci("d1h5"))
    assert node.verdict is Verdict.MISTAKE
    assert not node.played
    assert drill.current.san == "e5"
    assert node.label == "2. Qh5?!"
    assert node.comments == ["Too early."]
    assert drill.line_mistakes == 1


def test_move_not_in_repertoire_is_rejected():
    drill = make_drill(chess.WHITE)
    node = drill.try_move(uci("d2d4"))
    assert node.verdict is Verdict.NOT_IN_REPERTOIRE
    assert node.comments == []
    assert drill.board.fen() == chess.STARTING_FEN
    # Trying the same move again reuses the node rather than adding another.
    assert drill.try_move(uci("d2d4")) is node
    assert len(drill.root.children) == 1


def test_opponent_comment_is_hidden_until_you_reply():
    drill = make_drill(chess.BLACK)
    assert not drill.is_user_turn
    opponent = drill.play_opponent_move()
    assert opponent.san == "e4"
    assert opponent.comments == []
    drill.try_move(uci("e7e5"))
    assert opponent.comments == ["Centre."]


def test_opponent_comment_can_be_shown_straight_away():
    drill = make_drill(chess.BLACK, hide_opponent_comments=False)
    assert drill.play_opponent_move().comments == ["Centre."]


def play_to_move_two_for_black(drill: Drill) -> str:
    drill.try_move(uci("e2e4"))
    drill.play_opponent_move()
    drill.try_move(uci("g1f3"))
    return drill.play_opponent_move().san


def test_opponent_plays_known_mistakes_only_if_allowed():
    allowed = {play_to_move_two_for_black(make_drill(chess.WHITE, seed=seed)) for seed in range(30)}
    assert allowed == {"Nc6", "f6"}
    not_allowed = {
        play_to_move_two_for_black(make_drill(chess.WHITE, seed=seed, opponent_mistakes=False)) for seed in range(30)
    }
    assert not_allowed == {"Nc6"}


def test_line_finishes_when_the_repertoire_runs_out():
    drill = make_drill(chess.WHITE, opponent_mistakes=False)
    play_to_move_two_for_black(drill)
    assert not drill.line_finished
    drill.try_move(uci("f1c4"))
    assert drill.line_finished
    assert not drill.is_user_turn
    assert drill.lines_completed == 1 and drill.lines_clean == 1


def test_line_finishes_when_you_only_have_bad_moves():
    drill = make_drill(chess.BLACK, pgn="1. e4 f6? *")
    drill.play_opponent_move()
    assert drill.line_finished
    assert not drill.is_user_turn
    assert drill.lines_completed == 1


def test_tree_carries_over_but_hides_moves_after_the_live_position():
    drill = make_drill(chess.WHITE)
    d4 = drill.try_move(uci("d2d4"))
    e4 = drill.try_move(uci("e2e4"))
    e5 = drill.play_opponent_move()
    drill.new_line()
    assert drill.current is drill.root
    assert drill.root.children == [d4, e4]
    # Played moves ahead of the live position would give the answer away...
    assert drill.is_hidden(e4) and drill.is_hidden(e5)
    # ...but a rejected attempt doesn't, so it stays visible.
    assert not drill.is_hidden(d4)
    drill.try_move(uci("e2e4"))
    assert not drill.is_hidden(e4) and drill.is_hidden(e5)
