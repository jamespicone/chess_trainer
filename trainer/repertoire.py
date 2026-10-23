"""Load PGN files into a single repertoire, keyed by position.

Every game and every variation in every file is merged into one lookup table:
position -> the moves the PGNs give from that position. Keying by position
rather than by move order means transpositions are handled automatically.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import chess
import chess.pgn

# python-chess logs every parse error; we collect and report them ourselves.
logging.getLogger("chess.pgn").setLevel(logging.CRITICAL)

# Annotations that mark a move as bad: ?! (dubious), ? (mistake), ?? (blunder).
BAD_NAGS = {chess.pgn.NAG_DUBIOUS_MOVE, chess.pgn.NAG_MISTAKE, chess.pgn.NAG_BLUNDER}

# The glyph to show for a move, worst first, so a move marked both "!" and "?"
# by different files shows "?".
GLYPHS = [
    (chess.pgn.NAG_BLUNDER, "??"),
    (chess.pgn.NAG_MISTAKE, "?"),
    (chess.pgn.NAG_DUBIOUS_MOVE, "?!"),
    (chess.pgn.NAG_BRILLIANT_MOVE, "!!"),
    (chess.pgn.NAG_GOOD_MOVE, "!"),
    (chess.pgn.NAG_SPECULATIVE_MOVE, "!?"),
]

# A per-game PGN header that overrides the global "stop after N moves" setting.
MAX_MOVES_HEADER = "TrainerMaxMoves"

# Embedded commands such as [%cal Ge2e4] or [%clk 0:05:00] inside comments.
_COMMAND = re.compile(r"\[%[^\]]*\]")

# python-chess's messages for unreadable moves, e.g.
# "illegal san: 'Nf6' in r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
_SAN_ERROR = re.compile(r"^(illegal|ambiguous|invalid) san: '(.*?)'(?: in \S+ ([wb]) \S+ \S+ \S+ (\d+))?")


def position_key(board: chess.Board) -> str:
    """Identify a position by its pieces, side to move, castling rights and en passant square.

    Move counters are left out so that the same position reached by different
    move orders gets the same key.
    """
    return board.epd()


def side_to_move(key: str) -> chess.Color:
    """The side to move in a position key (its second field is 'w' or 'b')."""
    return key.split(" ")[1] == "w"


def clean_comment(text: str) -> str:
    """Remove embedded [%...] commands and tidy up whitespace."""
    return " ".join(_COMMAND.sub(" ", text).split())


@dataclass
class RepertoireMove:
    """One move from one position, merged from every PGN that contains it."""

    move: chess.Move
    san: str
    next_key: str  # the position after the move, for following lines without a board
    nags: set[int] = field(default_factory=set)
    comments: list[str] = field(default_factory=list)

    @property
    def is_bad(self) -> bool:
        """True if any file marks this move ?!, ? or ??."""
        return bool(self.nags & BAD_NAGS)

    @property
    def glyph(self) -> str:
        for nag, glyph in GLYPHS:
            if nag in self.nags:
                return glyph
        return ""


class Repertoire:
    """All the moves from a set of PGN files, looked up by position."""

    def __init__(self) -> None:
        self.positions: dict[str, dict[chess.Move, RepertoireMove]] = {}
        # The starting FEN of every game, one entry per game, so that picking
        # one at random favours the positions most games start from.
        self.start_fens: list[str] = []
        self.errors: list[str] = []
        self.game_count = 0

    @classmethod
    def from_files(cls, paths: list[str], max_moves: int = 0) -> Repertoire:
        repertoire = cls()
        for path in paths:
            repertoire.add_file(path, max_moves)
        return repertoire

    def add_file(self, path: str | Path, max_moves: int = 0) -> None:
        path = Path(path)
        try:
            text = _read_text(path)
        except OSError as error:
            self.errors.append(f"{path.name}: could not read the file ({error.strerror}).")
            return
        self.add_pgn(text, path.name, max_moves)

    def add_pgn(self, text: str, source: str = "PGN", max_moves: int = 0) -> None:
        """Add every game in a PGN string. max_moves > 0 stops each game after that many moves."""
        stream = io.StringIO(text)
        number = 0
        while (game := chess.pgn.read_game(stream)) is not None:
            number += 1
            label = f"{source}, game {number}"
            event = game.headers.get("Event", "?")
            if event not in ("", "?"):
                label += f" ({event})"
            self._add_game(game, label, max_moves)

    def moves(self, board: chess.Board) -> list[RepertoireMove]:
        """Every move the PGNs give from this position, good and bad."""
        return list(self.positions.get(position_key(board), {}).values())

    def good_moves(self, board: chess.Board) -> list[RepertoireMove]:
        return [move for move in self.moves(board) if not move.is_bad]

    def lookup(self, board: chess.Board, move: chess.Move) -> RepertoireMove | None:
        return self.positions.get(position_key(board), {}).get(move)

    @property
    def position_count(self) -> int:
        return len(self.positions)

    def _add_game(self, game: chess.pgn.Game, label: str, max_moves: int) -> None:
        for error in game.errors:
            self.errors.append(f"{label}: {_describe_error(error)}")
        if not game.variations:
            return  # headers only, or the very first move was unreadable
        try:
            board = game.board()
        except ValueError as error:
            self.errors.append(f"{label}: the FEN header is not valid ({error}).")
            return

        self.game_count += 1
        self.start_fens.append(board.fen())
        header = game.headers.get(MAX_MOVES_HEADER, "").strip()
        if header.isdigit():
            max_moves = int(header)
        # The comment before the first move belongs to that move, like a
        # comment at the start of a variation does.
        self._add_moves(game, board, ply=0, max_ply=max_moves * 2, intro=game.comment)

    def _add_moves(self, node: chess.pgn.GameNode, board: chess.Board, ply: int, max_ply: int, intro: str = "") -> None:
        """Add node's continuations (main line and variations), then recurse into each."""
        if max_ply and ply >= max_ply:
            return
        entry = self.positions.setdefault(position_key(board), {})
        for index, child in enumerate(node.variations):
            if not child.move:
                continue  # a null move ("--") has no place in a repertoire
            san = board.san(child.move)
            board.push(child.move)
            repertoire_move = entry.get(child.move)
            if repertoire_move is None:
                repertoire_move = entry[child.move] = RepertoireMove(child.move, san, position_key(board))
            repertoire_move.nags |= child.nags
            before = intro if index == 0 else ""
            for text in (before, child.starting_comment, child.comment):
                text = clean_comment(text)
                if text and text not in repertoire_move.comments:
                    repertoire_move.comments.append(text)

            self._add_moves(child, board, ply + 1, max_ply)
            board.pop()


def _read_text(path: Path) -> str:
    """Read a PGN file. Hand-written files on Windows are often not UTF-8."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _describe_error(error: Exception) -> str:
    """Turn a python-chess parse error into something that points at the problem."""
    match = _SAN_ERROR.match(str(error))
    if match is None:
        return str(error)
    kind, san, turn, number = match.groups()
    problem = {
        "illegal": "is not a legal move here",
        "ambiguous": "is ambiguous (more than one piece can make it)",
        "invalid": "is not a readable move",
    }[kind]
    where = ""
    if number:
        where = f"move {number}, {'White' if turn == 'w' else 'Black'} to play: "
    return f"{where}'{san}' {problem}. The rest of that line was skipped."
