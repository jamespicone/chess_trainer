"""A training session: checking your moves, choosing the opponent's, and the move tree.

There is no GUI code here, so the rules can be read and tested on their own.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

import chess

from .repertoire import Repertoire, RepertoireMove


class Verdict(Enum):
    """What the repertoire says about one of your moves."""

    CORRECT = "correct"  # in the repertoire and not marked bad
    MISTAKE = "mistake"  # in the repertoire but marked ?!, ? or ??
    NOT_IN_REPERTOIRE = "not in repertoire"


@dataclass(eq=False)
class TreeNode:
    """A move in the session's move tree: a played move or a rejected attempt."""

    move: chess.Move | None  # None for the root (the starting position)
    san: str
    move_number: int
    color: chess.Color  # the side that made the move
    fen: str  # the position after the move
    played: bool = True  # False for a rejected attempt
    verdict: Verdict | None = None  # set for your moves, None for the opponent's
    repertoire_move: RepertoireMove | None = None  # None if it's not in the repertoire
    revealed: bool = False  # whether its comments and glyph may be shown yet
    parent: TreeNode | None = None
    children: list[TreeNode] = field(default_factory=list)

    @property
    def comments(self) -> list[str]:
        if self.repertoire_move is None or not self.revealed:
            return []
        return self.repertoire_move.comments

    @property
    def glyph(self) -> str:
        if self.repertoire_move is None or not self.revealed:
            return ""
        return self.repertoire_move.glyph

    @property
    def label(self) -> str:
        """The move as PGN writes it, e.g. '3. Bb5' or '3... a6', plus its glyph once revealed."""
        dots = "." if self.color == chess.WHITE else "..."
        return f"{self.move_number}{dots} {self.san}{self.glyph}"


class Drill:
    """Practice one side of a repertoire, one line at a time.

    The move tree carries over from line to line, so it builds up a picture of
    everything you've covered this session.
    """

    def __init__(
        self,
        repertoire: Repertoire,
        side: chess.Color,
        *,
        opponent_mistakes: bool = True,
        hide_opponent_comments: bool = True,
        rng: random.Random | None = None,
    ) -> None:
        self.repertoire = repertoire
        self.side = side
        self.opponent_mistakes = opponent_mistakes  # may the opponent play moves marked bad?
        self.hide_opponent_comments = hide_opponent_comments  # until you've replied
        self.rng = rng or random.Random()

        self.trees: dict[str, TreeNode] = {}  # one tree per starting position
        self.lines_completed = 0
        self.lines_clean = 0  # completed without a single rejected attempt
        self.new_line()

    def new_line(self) -> None:
        """Go back to a starting position and begin another line."""
        start_fens = self.repertoire.start_fens or [chess.STARTING_FEN]
        fen = self.rng.choice(start_fens)
        self.board = chess.Board(fen)
        root = self.trees.get(fen)
        if root is None:
            root = TreeNode(None, "", self.board.fullmove_number, not self.board.turn, fen, revealed=True)
            self.trees[fen] = root
        self.root = root
        self.current = root  # the live position's node
        self.line_mistakes = 0

    @property
    def is_user_turn(self) -> bool:
        return self.board.turn == self.side and not self.line_finished

    @property
    def line_finished(self) -> bool:
        """True once the side to move has nothing left to play from the repertoire."""
        if self.board.turn == self.side:
            return not self.repertoire.good_moves(self.board)
        return not self._opponent_choices()

    def path(self) -> list[TreeNode]:
        """The moves played so far on this line, oldest first."""
        nodes = []
        node = self.current
        while node.parent is not None:
            nodes.append(node)
            node = node.parent
        return nodes[::-1]

    def is_hidden(self, node: TreeNode) -> bool:
        """True for moves after the live position: showing them would give away the answer."""
        while node.parent is not None:
            if node.parent is self.current:
                return node.played
            node = node.parent
        return False

    def try_move(self, move: chess.Move) -> TreeNode:
        """Check one of your moves.

        A correct move is played. Anything else is recorded in the tree as a
        rejected attempt and the board stays as it was, so you can try again.
        """
        assert self.board.turn == self.side, "it's not your move"
        repertoire_move = self.repertoire.lookup(self.board, move)
        if repertoire_move is None:
            verdict = Verdict.NOT_IN_REPERTOIRE
        elif repertoire_move.is_bad:
            verdict = Verdict.MISTAKE
        else:
            verdict = Verdict.CORRECT

        node = self._child(move, repertoire_move, played=verdict is Verdict.CORRECT, verdict=verdict)
        node.revealed = True  # for a mistake, its comment is the lesson
        if verdict is Verdict.CORRECT:
            self.current.revealed = True  # the opponent's move you just answered
            self._advance(node)
        else:
            self.line_mistakes += 1
        return node

    def play_opponent_move(self) -> TreeNode | None:
        """Play one of the repertoire's moves for the opponent, chosen at random.

        Returns None if the opponent has nothing to play.
        """
        assert self.board.turn != self.side, "it's your move"
        choices = self._opponent_choices()
        if not choices:
            return None
        repertoire_move = self.rng.choice(choices)
        node = self._child(repertoire_move.move, repertoire_move, played=True, verdict=None)
        # Hidden again even if you saw it on an earlier line.
        node.revealed = not self.hide_opponent_comments
        self._advance(node)
        return node

    def _opponent_choices(self) -> list[RepertoireMove]:
        moves = self.repertoire.moves(self.board)
        if not self.opponent_mistakes:
            moves = [move for move in moves if not move.is_bad]
        return moves

    def _child(self, move: chess.Move, repertoire_move: RepertoireMove | None, played: bool, verdict: Verdict | None) -> TreeNode:
        """Find the current node's child for this move, adding it if it's new."""
        for child in self.current.children:
            if child.move == move:
                return child
        after = self.board.copy(stack=False)
        after.push(move)
        node = TreeNode(
            move,
            self.board.san(move),
            self.board.fullmove_number,
            self.board.turn,
            after.fen(),
            played=played,
            verdict=verdict,
            repertoire_move=repertoire_move,
            parent=self.current,
        )
        self.current.children.append(node)
        return node

    def _advance(self, node: TreeNode) -> None:
        self.board.push(node.move)
        self.current = node
        if self.line_finished:
            # Nothing left to give away, so show every comment on the line.
            for played in self.path():
                played.revealed = True
            self.lines_completed += 1
            if self.line_mistakes == 0:
                self.lines_clean += 1
