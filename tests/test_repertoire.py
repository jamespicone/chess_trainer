import chess

from trainer.repertoire import Repertoire


def load(text: str, max_moves: int = 0) -> Repertoire:
    repertoire = Repertoire()
    repertoire.add_pgn(text, "test.pgn", max_moves)
    return repertoire


def board_after(*sans: str) -> chess.Board:
    board = chess.Board()
    for san in sans:
        board.push_san(san)
    return board


def sans(repertoire: Repertoire, board: chess.Board) -> list[str]:
    return [move.san for move in repertoire.moves(board)]


def test_variations_are_merged_into_the_tree():
    repertoire = load("1. e4 e5 (1... c5 2. Nf3) 2. Nf3 *")
    assert sans(repertoire, board_after("e4")) == ["e5", "c5"]
    assert sans(repertoire, board_after("e4", "c5")) == ["Nf3"]


def test_transpositions_share_a_position():
    repertoire = load("1. e4 e5 2. Nf3 Nc6 3. Bc4 *\n\n1. Nf3 Nc6 2. e4 e5 *")
    assert sans(repertoire, board_after("Nf3", "Nc6", "e4", "e5")) == ["Bc4"]
    assert repertoire.game_count == 2


def test_bad_moves_are_flagged():
    repertoire = load("1. e4 e5 2. Nf3 (2. Qh5?!) (2. Bc4!) (2. Ke2?) (2. f3 $4) *")
    moves = {move.san: move for move in repertoire.moves(board_after("e4", "e5"))}
    assert not moves["Nf3"].is_bad
    assert not moves["Bc4"].is_bad and moves["Bc4"].glyph == "!"
    assert moves["Qh5"].is_bad and moves["Qh5"].glyph == "?!"
    assert moves["Ke2"].is_bad and moves["Ke2"].glyph == "?"
    assert moves["f3"].is_bad and moves["f3"].glyph == "??"


def test_bad_mark_wins_a_conflict_and_both_comments_are_kept():
    repertoire = load("1. e4! {Best by test.} *\n\n1. e4? {I always lose with this.} *")
    (move,) = repertoire.moves(chess.Board())
    assert move.is_bad and move.glyph == "?"
    assert move.comments == ["Best by test.", "I always lose with this."]


def test_comments_before_a_move_belong_to_that_move():
    repertoire = load("{Intro.} 1. e4 {Centre. [%cal Ge2e4]} ({The queen's pawn.} 1. d4 {Also\ngood.}) *")
    moves = {move.san: move for move in repertoire.moves(chess.Board())}
    assert moves["e4"].comments == ["Intro.", "Centre."]
    assert moves["d4"].comments == ["The queen's pawn.", "Also good."]


def test_max_moves_setting_and_header():
    text = '1. e4 e5 2. Nf3 Nc6 3. Bc4 *\n\n[TrainerMaxMoves "1"]\n\n1. d4 d5 2. c4 *'
    repertoire = load(text, max_moves=2)
    assert sans(repertoire, board_after("e4", "e5", "Nf3")) == ["Nc6"]
    assert sans(repertoire, board_after("e4", "e5", "Nf3", "Nc6")) == []
    assert sans(repertoire, board_after("d4")) == ["d5"]
    assert sans(repertoire, board_after("d4", "d5")) == []


def test_errors_say_where_the_problem_is():
    repertoire = load('[Event "Typo"]\n\n1. e4 e5 2. Nf3 Nc6 3. Nf6 Nf6 4. Bc4 *')
    (error,) = repertoire.errors
    assert error.startswith("test.pgn, game 1 (Typo): move 3, White to play: 'Nf6' is not a legal move")
    # Everything before the bad move is still loaded.
    assert sans(repertoire, board_after("e4", "e5", "Nf3")) == ["Nc6"]


def test_games_can_start_from_a_fen():
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"
    repertoire = load(f'[SetUp "1"]\n[FEN "{fen}"]\n\n3... Bc5 *')
    assert repertoire.start_fens == [fen]
    assert sans(repertoire, chess.Board(fen)) == ["Bc5"]
