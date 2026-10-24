"""A training session: checking your moves, choosing the opponent's, and the move tree.

There is no GUI code here, so the rules can be read and tested on their own.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TypeVar

import chess

from .progress import Card, Progress
from .repertoire import Repertoire, RepertoireMove, position_key, side_to_move

# How much of the PGN's line after a mistake gets attached to it.
REFUTATION_MAX_PLIES = 20
REFUTATION_MAX_MOVES = 60

T = TypeVar("T")


class Verdict(Enum):
    """What the repertoire says about one of your moves."""

    CORRECT = "correct"  # in the repertoire and not marked bad
    MISTAKE = "mistake"  # in the repertoire but marked ?!, ? or ??
    NOT_IN_REPERTOIRE = "not in repertoire"


class NodeKind(Enum):
    PLAYED = "played"  # made on the board this session
    REJECTED = "rejected"  # one of your moves that was turned down
    REFUTATION = "refutation"  # the PGN's line after a rejected mistake, for reference


class Outcome(Enum):
    """What a correct move did to that position's review schedule."""

    LEARNED = "learned"  # the first time you've met the position
    PASSED = "passed"  # it was due and you got it right first time
    FAILED = "failed"  # you needed another go or a hint, so it's back at the bottom
    NOT_DUE = "not due"  # right, but it wasn't due, so its schedule hasn't changed


@dataclass
class Grade:
    outcome: Outcome
    due: datetime  # when the position is next due


@dataclass
class Counts:
    """Your positions in the loaded repertoire, by review status."""

    due: int
    new: int
    learned: int
    next_due: datetime | None  # the soonest review that isn't due yet


def format_move(number: int, color: chess.Color, san: str) -> str:
    """A move as PGN writes it, e.g. '3. Bb5' or '3... a6'."""
    return f"{number}{'.' if color == chess.WHITE else '...'} {san}"


@dataclass(eq=False)
class TreeNode:
    """A move in the session's move tree."""

    move: chess.Move | None  # None for the root (the starting position)
    san: str
    move_number: int
    color: chess.Color  # the side that made the move
    fen: str  # the position after the move
    kind: NodeKind = NodeKind.PLAYED
    verdict: Verdict | None = None  # set for your moves, None for the opponent's
    repertoire_move: RepertoireMove | None = None  # None if it's not in the repertoire
    revealed: bool = False  # whether its comments and glyph may be shown yet
    parent: TreeNode | None = None
    children: list[TreeNode] = field(default_factory=list)

    @property
    def played(self) -> bool:
        return self.kind is NodeKind.PLAYED

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
        """The move as PGN writes it, plus its glyph once revealed."""
        return format_move(self.move_number, self.color, self.san + self.glyph)


class Drill:
    """Practice one side of a repertoire, one line at a time.

    The opponent's moves steer towards positions that are due for review, then
    towards new positions while today's allowance lasts. The move tree carries
    over from line to line, building up a picture of what you've covered.
    """

    def __init__(
        self,
        repertoire: Repertoire,
        side: chess.Color,
        *,
        progress: Progress | None = None,
        learn_new: bool = True,
        new_per_day: int = 10,
        opponent_mistakes: bool = True,
        hide_opponent_comments: bool = True,
        rng: random.Random | None = None,
    ) -> None:
        self.repertoire = repertoire
        self.side = side
        self.progress = progress or Progress()
        self.learn_new = learn_new  # show you the good moves you haven't played yet
        self.new_per_day = new_per_day
        self.opponent_mistakes = opponent_mistakes  # may the opponent play moves marked bad?
        self.hide_opponent_comments = hide_opponent_comments  # until you've replied
        self.rng = rng or random.Random()

        self.trees: dict[str, TreeNode] = {}  # one tree per starting position
        self.new_line()

    def new_line(self) -> None:
        """Go back to a starting position and begin another line."""
        start_fens = self.repertoire.start_fens or [chess.STARTING_FEN]
        fen = self._pick([(fen, position_key(chess.Board(fen))) for fen in start_fens])
        self.board = chess.Board(fen)
        root = self.trees.get(fen)
        if root is None:
            root = TreeNode(None, "", self.board.fullmove_number, not self.board.turn, fen, revealed=True)
            self.trees[fen] = root
        self.root = root
        self.current = root  # the live position's node
        self.line_mistakes = 0  # positions on this line you didn't get right first time
        self.last_grade: Grade | None = None  # how your latest correct move was scheduled
        self._failed_here = False  # already got the live position wrong on this line?
        self._unplayed = self._unplayed_moves()

    # The state of play

    @property
    def is_user_turn(self) -> bool:
        return self.board.turn == self.side and not self.line_finished

    @property
    def line_finished(self) -> bool:
        """True once the side to move has nothing left to play from the repertoire."""
        if self.board.turn == self.side:
            return not self.repertoire.good_moves(self.board)
        return not self._opponent_choices()

    @property
    def teaching(self) -> list[RepertoireMove]:
        """In learn mode, the good moves to show you with arrows: all of them at a position
        you haven't met before, and at one that isn't due, those you haven't played there."""
        if not self.learn_new or not self.is_user_turn:
            return []
        return self._unplayed

    @property
    def at_new_position(self) -> bool:
        """True if you haven't met the live position before."""
        return position_key(self.board) not in self.progress.cards

    @property
    def new_allowed(self) -> bool:
        """Whether there's room left in today's allowance of new positions."""
        return self.progress.added_today() < self.new_per_day

    def counts(self) -> Counts:
        cards: set[str] = set()
        for fen in set(self.repertoire.start_fens):
            cards |= self._cards_from(position_key(chess.Board(fen)))
        now = self.progress.now()
        due = new = learned = 0
        next_due = None
        for key in cards:
            card = self.progress.cards.get(key)
            if card is None:
                new += 1
            elif card.due <= now:
                due += 1
            else:
                learned += 1
                next_due = card.due if next_due is None else min(next_due, card.due)
        return Counts(due, new, learned, next_due)

    def path(self) -> list[TreeNode]:
        """The moves played so far on this line, oldest first."""
        nodes = []
        node = self.current
        while node.parent is not None:
            nodes.append(node)
            node = node.parent
        return nodes[::-1]

    def is_hidden(self, node: TreeNode) -> bool:
        """True for moves the tree mustn't show yet, because they'd give away an answer:
        anything after the live position, and the line after a mistake until you've
        found the right move there (books' notes on it often name that move)."""
        while node.parent is not None:
            parent = node.parent
            if parent is self.current:
                return node.kind is not NodeKind.REJECTED
            if parent.kind is NodeKind.REJECTED and not self._refutation_visible(parent):
                return True
            node = parent
        return False

    # Moves

    def try_move(self, move: chess.Move) -> TreeNode:
        """Check one of your moves.

        A correct move is played. Anything else is recorded in the tree as a
        rejected attempt and the board stays as it was, so you can try again.
        """
        assert self.board.turn == self.side, "it's not your move"
        key = position_key(self.board)
        repertoire_move = self.repertoire.lookup(self.board, move)
        if repertoire_move is None:
            verdict = Verdict.NOT_IN_REPERTOIRE
        elif repertoire_move.is_bad:
            verdict = Verdict.MISTAKE
        else:
            verdict = Verdict.CORRECT

        kind = NodeKind.PLAYED if verdict is Verdict.CORRECT else NodeKind.REJECTED
        node = self._child(move, repertoire_move, kind, verdict)
        node.revealed = True  # for a mistake, its comment is the lesson
        if verdict is Verdict.CORRECT:
            self.last_grade = self._record_success(key)
            self.progress.played(key, move.uci())
            self.current.revealed = True  # the opponent's move you just answered
            self._advance(node)
        else:
            self._record_failure(key)
            if verdict is Verdict.MISTAKE and not node.children:
                self._add_refutation(node)
        return node

    def hint(self) -> chess.Move:
        """Suggest a move. Asking counts as getting the position wrong."""
        assert self.is_user_turn, "it's not your move"
        self._record_failure(position_key(self.board))
        return self.repertoire.good_moves(self.board)[0].move

    def play_opponent_move(self) -> TreeNode | None:
        """Play one of the repertoire's moves for the opponent.

        Returns None if the opponent has nothing to play.
        """
        assert self.board.turn != self.side, "it's your move"
        choices = self._opponent_choices()
        if not choices:
            return None
        repertoire_move = self._pick([(move, move.next_key) for move in choices])
        node = self._child(repertoire_move.move, repertoire_move, NodeKind.PLAYED, None)
        # Hidden again even if you saw it on an earlier line.
        node.revealed = not self.hide_opponent_comments
        self._advance(node)
        return node

    def _opponent_choices(self) -> list[RepertoireMove]:
        moves = self.repertoire.moves(self.board)
        if not self.opponent_mistakes:
            moves = [move for move in moves if not move.is_bad]
        return moves

    def _advance(self, node: TreeNode) -> None:
        self.board.push(node.move)
        self.current = node
        self._unplayed = self._unplayed_moves()
        if self.line_finished:
            # Nothing left to give away, so show every comment on the line.
            for played in self.path():
                played.revealed = True

    # Spaced repetition

    def _unplayed_moves(self) -> list[RepertoireMove]:
        """The good moves you haven't played at the live position, if it's your move and isn't due.

        Worked out when the position comes up, so a wrong answer at a due position
        (which makes it due again in a few minutes) doesn't then show you the moves.
        """
        if self.board.turn != self.side:
            return []
        key = position_key(self.board)
        good = self.repertoire.good_moves(self.board)
        card = self.progress.cards.get(key)
        if card is None:
            return good
        if card.due <= self.progress.now():
            return []  # a review: an arrow would give the answer away
        played = self._played_moves(key, card)
        return [move for move in good if move.move.uci() not in played]

    def _played_moves(self, key: str, card: Card) -> set[str]:
        """The moves you've played at a position you've met, in UCI notation.

        Progress saved before moves were recorded doesn't list them, so a move also
        counts if you've met a position after the opponent's reply to it.
        """
        played = set(card.moves)
        for move in self.repertoire.positions.get(key, {}).values():
            replies = self.repertoire.positions.get(move.next_key, {}).values()
            if any(reply.next_key in self.progress.cards for reply in replies):
                played.add(move.move.uci())
        return played

    def _record_success(self, key: str) -> Grade:
        failed, self._failed_here = self._failed_here, False
        card = self.progress.cards.get(key)
        if card is None:
            return Grade(Outcome.LEARNED, self.progress.learned(key).due)
        if failed and not self.teaching:  # a wrong attempt while you're being shown moves doesn't count
            return Grade(Outcome.FAILED, card.due)
        if card.due <= self.progress.now():
            return Grade(Outcome.PASSED, self.progress.passed(key).due)
        return Grade(Outcome.NOT_DUE, card.due)

    def _record_failure(self, key: str) -> None:
        """A wrong attempt or a hint. Only the first one at a position counts."""
        if self._failed_here:
            return
        self._failed_here = True
        self.line_mistakes += 1
        if not self.teaching:  # while you're being shown moves, there's nothing to fail
            self.progress.failed(key)

    def _pick(self, options: list[tuple[T, str]]) -> T:
        """Choose from (option, position it leads to) pairs, at random but weighted towards
        positions due for review, then towards new ones while today's allowance lasts, then
        towards branches with more lines."""
        new_allowed = self.new_allowed
        due_by_key, new_by_key = {}, {}
        for key in {key for _, key in options}:  # most games share a starting position, so count each once
            cards = self._cards_from(key)
            due_by_key[key] = sum(1 for card in cards if self.progress.is_due(card))
            new_by_key[key] = sum(1 for card in cards if card not in self.progress.cards) if new_allowed else 0
        choices = [option for option, _ in options]
        for by_key in (due_by_key, new_by_key):
            weights = [by_key[key] for _, key in options]
            if any(weights):
                return self.rng.choices(choices, weights)[0]
        # Nothing due or new: free practice. A branch with more lines comes up more often, but
        # only by the square root, so a one-move sideline isn't drowned out by the main line.
        size_by_key = {key: math.sqrt(self._line_count(key)) for key in due_by_key}
        return self.rng.choices(choices, [size_by_key[key] for _, key in options])[0]

    def _cards_from(self, start: str) -> set[str]:
        """Your positions reachable from this one: wherever it's your move and the repertoire has a good move."""
        return {key for key in self._reachable(start) if side_to_move(key) == self.side and self._next_moves(key)}

    def _line_count(self, start: str) -> int:
        """How many lines go on from this position, counting each position where a line ends once."""
        ends = sum(1 for key in self._reachable(start) if not self._next_moves(key))
        return max(ends, 1)  # lines that only go round in a circle never end

    def _reachable(self, start: str) -> set[str]:
        """Every position a line can reach from this one, including itself."""
        seen = {start}
        waiting = [start]
        while waiting:
            for move in self._next_moves(waiting.pop()):
                if move.next_key not in seen:
                    seen.add(move.next_key)
                    waiting.append(move.next_key)
        return seen

    def _next_moves(self, key: str) -> list[RepertoireMove]:
        """The moves a line can go on with: your good moves, or the opponent's moves (bad ones only if allowed)."""
        moves = list(self.repertoire.positions.get(key, {}).values())
        if side_to_move(key) == self.side or not self.opponent_mistakes:
            moves = [move for move in moves if not move.is_bad]
        return moves

    # The move tree

    def _child(self, move: chess.Move, repertoire_move: RepertoireMove | None, kind: NodeKind, verdict: Verdict | None) -> TreeNode:
        """Find the current node's child for this move, adding it if it's new."""
        for child in self.current.children:
            if child.move == move:
                return child
        node = _new_node(self.current, self.board, move, kind, repertoire_move)
        node.verdict = verdict
        return node

    def _refutation_visible(self, attempt: TreeNode) -> bool:
        """Show the line after a mistake once you've found the right move there."""
        parent = attempt.parent
        return parent is not self.current and any(child.played for child in parent.children)

    def _add_refutation(self, attempt: TreeNode) -> None:
        """Attach the PGN's moves after a mistake, to show once you've found the right move."""
        board = chess.Board(attempt.fen)
        self._refutation_budget = REFUTATION_MAX_MOVES
        self._add_refutation_moves(attempt, board, REFUTATION_MAX_PLIES, {position_key(board)})

    def _add_refutation_moves(self, parent: TreeNode, board: chess.Board, plies_left: int, seen: set[str]) -> None:
        for repertoire_move in self.repertoire.moves(board):
            if self._refutation_budget == 0:
                return
            if repertoire_move.next_key in seen:
                continue  # the line goes round in a circle
            self._refutation_budget -= 1
            node = _new_node(parent, board, repertoire_move.move, NodeKind.REFUTATION, repertoire_move)
            node.revealed = True
            if plies_left > 1:
                board.push(repertoire_move.move)
                self._add_refutation_moves(node, board, plies_left - 1, seen | {repertoire_move.next_key})
                board.pop()


def _new_node(parent: TreeNode, board: chess.Board, move: chess.Move, kind: NodeKind, repertoire_move: RepertoireMove | None) -> TreeNode:
    """Add a child to parent for a move made from board's position."""
    after = board.copy(stack=False)
    after.push(move)
    node = TreeNode(
        move,
        board.san(move),
        board.fullmove_number,
        board.turn,
        after.fen(),
        kind=kind,
        repertoire_move=repertoire_move,
        parent=parent,
    )
    parent.children.append(node)
    return node
