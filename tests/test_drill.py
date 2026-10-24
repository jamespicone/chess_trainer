import random
from datetime import datetime, timedelta

import chess

from trainer.drill import Drill, NodeKind, Outcome, Verdict
from trainer.progress import INTERVALS, Card, Progress
from trainer.repertoire import Repertoire, position_key

SAMPLE = """
1. e4 {Centre.} e5 {Black mirrors.}
2. Nf3 (2. Qh5?! {Too early.})
2... Nc6 (2... f6? {Weakens the king.} 3. Nxe5 fxe5 4. Qh5+) (2... d6 3. d4)
3. Bc4 *
"""


class Clock:
    def __init__(self) -> None:
        self.time = datetime(2026, 1, 1, 9, 0)

    def __call__(self) -> datetime:
        return self.time


def make_drill(side: chess.Color, pgn: str = SAMPLE, seed: int = 0, progress: Progress | None = None, **options) -> Drill:
    repertoire = Repertoire()
    repertoire.add_pgn(pgn, "test.pgn")
    return Drill(repertoire, side, progress=progress, rng=random.Random(seed), **options)


def uci(text: str) -> chess.Move:
    return chess.Move.from_uci(text)


def key_after(*sans: str) -> str:
    board = chess.Board()
    for san in sans:
        board.push_san(san)
    return position_key(board)


# Checking moves


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
    assert allowed == {"Nc6", "f6", "d6"}
    not_allowed = {
        play_to_move_two_for_black(make_drill(chess.WHITE, seed=seed, opponent_mistakes=False)) for seed in range(30)
    }
    assert not_allowed == {"Nc6", "d6"}


def test_line_finishes_when_the_repertoire_runs_out():
    drill = make_drill(chess.WHITE, pgn="1. e4 e5 2. Nf3 *")
    drill.try_move(uci("e2e4"))
    drill.play_opponent_move()
    assert not drill.line_finished
    drill.try_move(uci("g1f3"))
    assert drill.line_finished
    assert not drill.is_user_turn


def test_line_finishes_when_you_only_have_bad_moves():
    drill = make_drill(chess.BLACK, pgn="1. e4 f6? *")
    drill.play_opponent_move()
    assert drill.line_finished
    assert not drill.is_user_turn


# The move tree


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


def test_line_after_a_mistake_shows_once_you_find_the_right_move():
    drill = make_drill(chess.BLACK, opponent_mistakes=False, seed=1)
    drill.play_opponent_move()  # 1. e4
    drill.try_move(uci("e7e5"))
    drill.play_opponent_move()  # 2. Nf3
    attempt = drill.try_move(uci("f7f6"))
    assert attempt.verdict is Verdict.MISTAKE
    assert [node.san for node in attempt.children] == ["Nxe5"]
    nxe5 = attempt.children[0]
    assert nxe5.kind is NodeKind.REFUTATION
    assert [node.san for node in nxe5.children] == ["fxe5"]
    assert not drill.is_hidden(attempt)
    assert drill.is_hidden(nxe5)

    drill.try_move(uci("b8c6"))
    assert not drill.is_hidden(nxe5)
    assert not drill.is_hidden(nxe5.children[0])

    # Back at that position on a later line, the refutation is hidden again.
    drill.new_line()
    drill.play_opponent_move()
    drill.try_move(uci("e7e5"))
    drill.play_opponent_move()
    assert drill.current is attempt.parent
    assert not drill.is_hidden(attempt)
    assert drill.is_hidden(nxe5)


# Spaced repetition


def test_new_position_is_taught_then_learned():
    clock = Clock()
    progress = Progress(clock=clock)
    drill = make_drill(chess.WHITE, progress=progress)
    assert drill.teaching.san == "e4"
    # A wrong move while being taught doesn't count against you.
    drill.try_move(uci("d2d4"))
    assert progress.cards == {}
    drill.try_move(uci("e2e4"))
    assert drill.last_grade.outcome is Outcome.LEARNED
    assert progress.cards[key_after()].due == clock.time + INTERVALS[0]


def test_without_teaching_a_new_position_can_be_failed():
    progress = Progress()
    drill = make_drill(chess.WHITE, progress=progress, learn_new=False)
    assert drill.teaching is None
    drill.try_move(uci("d2d4"))
    assert progress.cards[key_after()].step == -1
    drill.try_move(uci("e2e4"))
    assert drill.last_grade.outcome is Outcome.FAILED


def test_due_position_passes_and_moves_up_the_ladder():
    clock = Clock()
    progress = Progress(clock=clock)
    progress.learned(key_after())
    clock.time += INTERVALS[0]
    drill = make_drill(chess.WHITE, progress=progress)
    drill.try_move(uci("e2e4"))
    assert drill.last_grade.outcome is Outcome.PASSED
    assert progress.cards[key_after()].step == 1


def test_position_not_yet_due_keeps_its_schedule_when_right_but_fails_when_wrong():
    progress = Progress()
    card = progress.learned(key_after())
    due = card.due
    drill = make_drill(chess.WHITE, progress=progress)
    drill.try_move(uci("e2e4"))
    assert drill.last_grade.outcome is Outcome.NOT_DUE
    assert card.due == due

    drill.new_line()
    drill.try_move(uci("d2d4"))
    drill.try_move(uci("c2c4"))  # a second wrong attempt only counts once
    assert card.step == -1 and card.lapses == 1


def test_hint_counts_as_a_mistake():
    progress = Progress()
    progress.learned(key_after())
    drill = make_drill(chess.WHITE, progress=progress)
    assert drill.hint() == uci("e2e4")
    assert progress.cards[key_after()].step == -1
    drill.try_move(uci("e2e4"))
    assert drill.last_grade.outcome is Outcome.FAILED


def test_opponent_steers_towards_due_positions():
    clock = Clock()
    progress = Progress(clock=clock)
    later = clock.time + timedelta(days=1)
    for key in (key_after(), key_after("e4", "e5"), key_after("e4", "e5", "Nf3", "Nc6"), key_after("e4", "e5", "Nf3", "d6")):
        progress.cards[key] = Card(step=1, due=later, added=clock.time)
    progress.cards[key_after("e4", "e5", "Nf3", "f6")] = Card(step=1, due=clock.time, added=clock.time)

    replies = {play_to_move_two_for_black(make_drill(chess.WHITE, seed=seed, progress=progress)) for seed in range(20)}
    assert replies == {"f6"}


def test_free_practice_when_nothing_is_due_or_new():
    progress = Progress()
    drill = make_drill(chess.WHITE, progress=progress, new_per_day=0)
    counts = drill.counts()
    assert counts.due == 0 and counts.learned == 0
    assert counts.new == 6  # 1. e4, 2. Nf3, then 3. Bc4 / 3. Nxe5 / 3. d4 after Black's replies, and 4. Qh5+
    assert not drill.new_allowed
    replies = {play_to_move_two_for_black(make_drill(chess.WHITE, seed=seed, progress=Progress(), new_per_day=0)) for seed in range(30)}
    assert replies == {"Nc6", "f6", "d6"}


def test_free_practice_favours_branches_with_more_lines_by_the_square_root():
    # 1... e5 leads to four lines and 1... c5 to one, so c5 should come up a third of
    # the time: less than the half it would get at random, more than a fifth by line.
    pgn = "1. e4 e5 (1... c5 2. Nf3) 2. Nf3 Nc6 (2... d6 3. d4) (2... f6 3. Nxe5) (2... Nf6 3. Nxe5) 3. Bc4 *"
    replies = []
    for seed in range(300):
        drill = make_drill(chess.WHITE, pgn, seed=seed, new_per_day=0)
        drill.try_move(uci("e2e4"))
        replies.append(drill.play_opponent_move().san)
    assert 0.27 < replies.count("c5") / len(replies) < 0.40
