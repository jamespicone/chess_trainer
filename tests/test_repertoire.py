import os

import chess

from trainer.repertoire import Repertoire, RepertoireCache


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


def test_merging_matches_loading_the_files_together(tmp_path):
    first = tmp_path / "first.pgn"
    second = tmp_path / "second.pgn"
    first.write_text("1. e4! {Best by test.} e5 2. Nf3 *", encoding="utf-8")
    second.write_text("1. e4? {I always lose with this.} c5 *", encoding="utf-8")
    together = Repertoire.from_files([str(first), str(second)])

    merged = Repertoire.from_files([str(first)])
    merged.merge(Repertoire.from_files([str(second)]))
    (move,) = merged.moves(chess.Board())
    assert move.is_bad and move.comments == ["Best by test.", "I always lose with this."]
    assert merged.positions == together.positions
    assert merged.start_fens == together.start_fens
    assert merged.game_count == together.game_count == 2


def test_cache_only_parses_files_that_are_new_or_changed(tmp_path, monkeypatch):
    first = tmp_path / "first.pgn"
    second = tmp_path / "second.pgn"
    first.write_text("1. e4! {Best by test.} *", encoding="utf-8")
    second.write_text("1. e4? {I always lose with this.} *", encoding="utf-8")
    paths = [str(first), str(second)]

    parsed = []
    add_file = Repertoire.add_file

    def counting_add_file(self, path, max_moves=0):
        parsed.append(os.path.basename(path))
        add_file(self, path, max_moves)

    monkeypatch.setattr(Repertoire, "add_file", counting_add_file)
    cache = RepertoireCache()
    assert cache.load(paths).moves(chess.Board())[0].is_bad
    assert parsed == ["first.pgn", "second.pgn"]

    # Turning a file off and on again doesn't parse anything, and merging
    # didn't change the first file's cached moves.
    (move,) = cache.load([str(first)]).moves(chess.Board())
    assert not move.is_bad and move.comments == ["Best by test."]
    cache.load(paths)
    assert parsed == ["first.pgn", "second.pgn"]

    # An edited file is parsed again, and so is everything when the move limit changes.
    first.write_text("1. d4 *", encoding="utf-8")
    stat = first.stat()
    os.utime(first, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert sans(cache.load(paths), chess.Board()) == ["d4", "e4"]
    assert parsed == ["first.pgn", "second.pgn", "first.pgn"]
    cache.load(paths, max_moves=5)
    assert parsed[3:] == ["first.pgn", "second.pgn"]


def test_cache_reports_missing_files(tmp_path):
    repertoire = RepertoireCache().load([str(tmp_path / "gone.pgn")])
    (error,) = repertoire.errors
    assert error.startswith("gone.pgn: could not read the file")
