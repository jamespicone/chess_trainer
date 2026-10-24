"""The chessboard: draws a position and lets you move pieces by dragging or clicking."""

from __future__ import annotations

import chess
import chess.svg
from PySide6.QtCore import QAbstractAnimation, QByteArray, QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPalette, QPen, QPixmap, QPolygonF, QRadialGradient
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QMenu, QSizePolicy, QWidget

LIGHT_SQUARE = QColor("#f0d9b5")
DARK_SQUARE = QColor("#b58863")
LAST_MOVE = QColor(155, 199, 0, 105)
WRONG_MOVE = QColor(220, 50, 50, 140)
SELECTED = QColor(20, 85, 30, 110)
TARGET = QColor(20, 85, 30, 90)
CHECK = QColor(255, 0, 0, 200)
ARROW = QColor(21, 120, 27, 170)
HINT_SQUARE = QColor(30, 110, 220, 120)

ANIMATION_MS = 180


class BoardWidget(QWidget):
    """Shows a chess.Board. Emits move_made with a legal chess.Move when you move a piece."""

    move_made = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.board = chess.Board()
        self.orientation = chess.WHITE
        self.user_color: chess.Color | None = None  # whose pieces may be moved; None for nobody
        self.last_move: chess.Move | None = None
        self.last_move_wrong = False
        self.selected: chess.Square | None = None
        self.drag_pos: QPointF | None = None  # where a dragged piece is drawn
        self.arrows: list[chess.Move] = []  # moves to show you
        self.hint_square: chess.Square | None = None  # a square to point out

        # python-chess comes with SVG pieces, so there are no image files to ship.
        self._pieces = {
            symbol: QSvgRenderer(QByteArray(chess.svg.piece(chess.Piece.from_symbol(symbol)).encode()))
            for symbol in "PNBRQKpnbrqk"
        }

        self._animation = QVariantAnimation(self)
        self._animation.setDuration(ANIMATION_MS)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self.update)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(320, 320)

    def sizeHint(self) -> QSize:
        return QSize(640, 640)

    # Called by the main window

    def set_position(self, board: chess.Board, last_move: chess.Move | None = None, *, animate: bool = False, wrong: bool = False) -> None:
        """Show a position. animate slides last_move's piece into place; wrong colours it red."""
        self.board = board.copy(stack=False)
        self.last_move = last_move
        self.last_move_wrong = wrong
        self.selected = None
        self.drag_pos = None
        self._animation.stop()
        if animate and last_move is not None:
            self._animation.start()
        self.update()

    def set_orientation(self, color: chess.Color) -> None:
        self.orientation = color
        self.update()

    def set_guides(self, arrows: list[chess.Move] | None = None, square: chess.Square | None = None) -> None:
        """Draw an arrow for each of some moves and/or highlight a square, e.g. for a hint."""
        self.arrows = arrows or []
        self.hint_square = square
        self.update()

    def set_user_color(self, color: chess.Color | None) -> None:
        self.user_color = color
        if color is None:
            self.selected = None
            self.drag_pos = None
        self.update()

    # Geometry

    def _geometry(self) -> tuple[float, float, float, float]:
        """Square size, the board's left and top edges, and the margin for coordinates."""
        size = min(self.width(), self.height())
        margin = max(16.0, size * 0.04)
        square = (size - margin) / 8
        left = (self.width() - 8 * square - margin) / 2 + margin
        top = (self.height() - 8 * square - margin) / 2
        return square, left, top, margin

    def _column_row(self, square: chess.Square) -> tuple[int, int]:
        """Where a square appears on screen, counting from the top-left corner."""
        file, rank = chess.square_file(square), chess.square_rank(square)
        if self.orientation == chess.WHITE:
            return file, 7 - rank
        return 7 - file, rank

    def _square_rect(self, square: chess.Square) -> QRectF:
        size, left, top, _ = self._geometry()
        column, row = self._column_row(square)
        return QRectF(left + column * size, top + row * size, size, size)

    def _square_at(self, pos: QPointF) -> chess.Square | None:
        size, left, top, _ = self._geometry()
        column = int((pos.x() - left) // size)
        row = int((pos.y() - top) // size)
        if not (0 <= column < 8 and 0 <= row < 8):
            return None
        if self.orientation == chess.WHITE:
            return chess.square(column, 7 - row)
        return chess.square(7 - column, row)

    # Drawing

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size, left, top, margin = self._geometry()

        for square in chess.SQUARES:
            light = (chess.square_file(square) + chess.square_rank(square)) % 2 == 1
            painter.fillRect(self._square_rect(square), LIGHT_SQUARE if light else DARK_SQUARE)

        if self.last_move is not None:
            color = WRONG_MOVE if self.last_move_wrong else LAST_MOVE
            for square in (self.last_move.from_square, self.last_move.to_square):
                painter.fillRect(self._square_rect(square), color)

        if self.hint_square is not None:
            painter.fillRect(self._square_rect(self.hint_square), HINT_SQUARE)

        king = self.board.king(self.board.turn)
        if self.board.is_check() and king is not None:
            rect = self._square_rect(king)
            glow = QRadialGradient(rect.center(), rect.width() / 2)
            glow.setColorAt(0, CHECK)
            glow.setColorAt(1, QColor(255, 0, 0, 0))
            painter.fillRect(rect, glow)

        if self.selected is not None:
            self._draw_targets(painter, size)

        animating = self.last_move if self._animation.state() == QAbstractAnimation.State.Running else None
        for square, piece in self.board.piece_map().items():
            if square == self.selected and self.drag_pos is not None:
                continue  # drawn under the cursor below
            if animating is not None and square == animating.to_square:
                continue  # drawn mid-slide below
            self._draw_piece(painter, piece, self._square_rect(square))

        if animating is not None and (piece := self.board.piece_at(animating.to_square)):
            start = self._square_rect(animating.from_square)
            end = self._square_rect(animating.to_square)
            t = self._animation.currentValue()
            self._draw_piece(painter, piece, QRectF(start.topLeft() + (end.topLeft() - start.topLeft()) * t, start.size()))

        if self.selected is not None and self.drag_pos is not None and (piece := self.board.piece_at(self.selected)):
            rect = QRectF(0, 0, size, size)
            rect.moveCenter(self.drag_pos)
            self._draw_piece(painter, piece, rect)

        for arrow in self.arrows:
            self._draw_arrow(painter, arrow, size)

        self._draw_coordinates(painter, size, left, top, margin)

    def _draw_arrow(self, painter: QPainter, move: chess.Move, size: float) -> None:
        """A straight arrow from the center of one square to the center of another."""
        start = self._square_rect(move.from_square).center()
        end = self._square_rect(move.to_square).center()
        delta = end - start
        length = (delta.x() ** 2 + delta.y() ** 2) ** 0.5
        if length == 0:
            return
        along = delta / length  # unit vector along the arrow
        across = QPointF(-along.y(), along.x())  # unit vector at right angles to it
        shaft, head, head_length = size * 0.09, size * 0.24, size * 0.45
        neck = end - along * head_length
        points = [
            start + across * shaft,
            neck + across * shaft,
            neck + across * head,
            end,
            neck - across * head,
            neck - across * shaft,
            start - across * shaft,
        ]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ARROW)
        painter.drawPolygon(QPolygonF(points))

    def _draw_targets(self, painter: QPainter, size: float) -> None:
        """Highlight the selected piece and mark where it can go."""
        painter.fillRect(self._square_rect(self.selected), SELECTED)
        targets = {move.to_square for move in self.board.legal_moves if move.from_square == self.selected}
        for square in targets:
            rect = self._square_rect(square)
            if self.board.piece_at(square):  # a capture: ring the piece
                painter.setPen(QPen(TARGET, size * 0.08))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                inset = size * 0.06
                painter.drawEllipse(rect.adjusted(inset, inset, -inset, -inset))
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(TARGET)
                painter.drawEllipse(rect.center(), size * 0.15, size * 0.15)

    def _draw_piece(self, painter: QPainter, piece: chess.Piece, rect: QRectF) -> None:
        self._pieces[piece.symbol()].render(painter, rect)

    def _draw_coordinates(self, painter: QPainter, size: float, left: float, top: float, margin: float) -> None:
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        font = painter.font()
        font.setPixelSize(max(10, int(margin * 0.7)))
        painter.setFont(font)
        for index in range(8):
            file = index if self.orientation == chess.WHITE else 7 - index
            rank = 7 - index if self.orientation == chess.WHITE else index
            below = QRectF(left + index * size, top + 8 * size, size, margin)
            beside = QRectF(left - margin, top + index * size, margin, size)
            painter.drawText(below, Qt.AlignmentFlag.AlignCenter, chess.FILE_NAMES[file])
            painter.drawText(beside, Qt.AlignmentFlag.AlignCenter, chess.RANK_NAMES[rank])

    # Moving pieces: drag and drop, or click the piece then click the target

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        square = self._square_at(event.position())
        if self.selected is not None and square is not None and square != self.selected:
            if self._try_move(self.selected, square):
                return
        if square is not None and self._can_move_from(square):
            self.selected = square
            self.drag_pos = event.position()
        else:
            self.selected = None
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self.drag_pos is not None:
            self.drag_pos = event.position()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.drag_pos is None:
            return
        self.drag_pos = None
        square = self._square_at(event.position())
        # Dropped back where it started: stay selected so a click can finish the move.
        if square is not None and square != self.selected and not self._try_move(self.selected, square):
            self.selected = None
        self.update()

    def _can_move_from(self, square: chess.Square) -> bool:
        piece = self.board.piece_at(square)
        return (
            piece is not None
            and self.user_color is not None
            and piece.color == self.user_color
            and self.board.turn == self.user_color
        )

    def _try_move(self, from_square: chess.Square, to_square: chess.Square) -> bool:
        """Emit move_made if from -> to is legal, asking which piece to promote to if needed."""
        moves = [m for m in self.board.legal_moves if m.from_square == from_square and m.to_square == to_square]
        if not moves:
            return False
        self.selected = None
        self.drag_pos = None
        move = moves[0]
        if move.promotion:
            piece_type = self._ask_promotion()
            if piece_type is None:
                self.update()
                return True
            move = chess.Move(from_square, to_square, promotion=piece_type)
        self.update()
        self.move_made.emit(move)
        return True

    def _ask_promotion(self) -> chess.PieceType | None:
        menu = QMenu(self)
        for piece_type in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT):
            icon = self._piece_icon(chess.Piece(piece_type, self.board.turn))
            action = menu.addAction(icon, chess.piece_name(piece_type).capitalize())
            action.setData(piece_type)
        chosen = menu.exec(QCursor.pos())
        return chosen.data() if chosen else None

    def _piece_icon(self, piece: chess.Piece) -> QIcon:
        pixmap = QPixmap(48, 48)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self._pieces[piece.symbol()].render(painter)
        painter.end()
        return QIcon(pixmap)
