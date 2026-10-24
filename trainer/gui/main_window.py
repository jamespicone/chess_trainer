"""The main window: the board on the left, Training and Files tabs on the right."""

from __future__ import annotations

import html
from pathlib import Path

import chess
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..drill import Counts, Drill, Grade, NodeKind, Outcome, TreeNode, Verdict, format_move
from ..progress import Progress, describe_wait
from ..repertoire import Repertoire, RepertoireCache
from ..settings import PgnFile, Settings
from .board import BoardWidget
from .move_tree import MoveTreeView

OPPONENT_DELAY_MS = 350  # pause before the opponent replies, so you see it happen
WRONG_MOVE_MS = 700  # how long a rejected move stays on the board
GREEN = "#2e7d32"
RED = "#c62828"
BLUE = "#1e6edc"


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, progress: Progress) -> None:
        super().__init__()
        self.settings = settings
        self.progress = progress
        self.repertoire = Repertoire()
        self.repertoire_cache = RepertoireCache()
        self.drill = Drill(self.repertoire, chess.WHITE, progress=Progress())
        self.review_node: TreeNode | None = None  # set while looking back at an earlier move
        self.last_attempt: TreeNode | None = None  # your latest rejected move, until you get it right
        self.showing_rejected = False  # a rejected move is on the board, about to be taken back
        self.hint_level = 0  # 1: the piece to move is highlighted, 2: the move is shown
        self.hint_move: chess.Move | None = None
        self.line_id = 0  # bumped for every new line, so timers left over from the last one do nothing

        self.setWindowTitle("Chess Opening Trainer")
        self.resize(1200, 760)

        self.board_view = BoardWidget()
        self.board_view.move_made.connect(self._on_user_move)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_training_tab(), "Training")
        self.tabs.addTab(self._build_files_tab(), "Files")

        splitter = QSplitter()
        splitter.addWidget(self.board_view)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)

        shortcuts = [
            ("N", self._next_line),
            ("H", self._hint),
            ("Left", self._review_back),
            ("Right", self._review_forward),
            ("End", self._resume),
            ("Escape", self._resume),
            ("F5", self._reload),
        ]
        for key, slot in shortcuts:
            QShortcut(QKeySequence(key), self).activated.connect(slot)

        # Changing the move limit reloads the files, but wait until the spin box settles.
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(400)
        self._reload_timer.timeout.connect(self._reload)

        self._populate_file_list()
        self._reload()
        if not self.settings.files:
            self.tabs.setCurrentIndex(1)

    # Layout

    def _build_training_tab(self) -> QWidget:
        self.side_combo = QComboBox()
        self.side_combo.addItems(["White", "Black"])
        self.side_combo.setCurrentIndex(0 if self.settings.side == "white" else 1)
        self.side_combo.currentIndexChanged.connect(self._on_side_changed)

        self.hint_button = QPushButton("Hint (H)")
        self.hint_button.clicked.connect(self._hint)
        self.resume_button = QPushButton("Resume (End)")
        self.resume_button.clicked.connect(self._resume)
        next_button = QPushButton("Next line (N)")
        next_button.clicked.connect(self._next_line)

        top = QHBoxLayout()
        top.addWidget(QLabel("Play as"))
        top.addWidget(self.side_combo)
        top.addStretch()
        top.addWidget(self.hint_button)
        top.addWidget(self.resume_button)
        top.addWidget(next_button)

        self.feedback = QTextBrowser()
        font = QFont(self.feedback.font())
        font.setPointSize(11)
        self.feedback.setFont(font)
        self.feedback.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.tree_view = MoveTreeView()
        self.tree_view.node_clicked.connect(self._review)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addLayout(top)
        layout.addWidget(self.feedback, 2)
        layout.addWidget(QLabel("Moves (click one to look back at it)"))
        layout.addWidget(self.tree_view, 3)
        return tab

    def _build_files_tab(self) -> QWidget:
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_list.itemChanged.connect(self._on_file_toggled)
        self.file_list.itemSelectionChanged.connect(self._on_file_selection_changed)

        add_button = QPushButton("Add files…")
        add_button.clicked.connect(self._add_files)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._remove_files)
        self.enable_button = QPushButton("Enable")
        self.enable_button.clicked.connect(lambda: self._set_selected_enabled(True))
        self.disable_button = QPushButton("Disable")
        self.disable_button.clicked.connect(lambda: self._set_selected_enabled(False))
        reload_button = QPushButton("Reload (F5)")
        reload_button.clicked.connect(self._reload)
        buttons = QHBoxLayout()
        buttons.addWidget(add_button)
        buttons.addWidget(self.remove_button)
        buttons.addSpacing(12)
        buttons.addWidget(self.enable_button)
        buttons.addWidget(self.disable_button)
        buttons.addStretch()
        buttons.addWidget(reload_button)

        self.max_moves_box = QSpinBox()
        self.max_moves_box.setRange(0, 200)
        self.max_moves_box.setSpecialValueText("No limit")
        self.max_moves_box.setValue(self.settings.max_moves)
        self.max_moves_box.valueChanged.connect(self._on_max_moves_changed)

        self.new_per_day_box = QSpinBox()
        self.new_per_day_box.setRange(0, 1000)
        self.new_per_day_box.setValue(self.settings.new_per_day)
        self.new_per_day_box.valueChanged.connect(self._on_new_per_day_changed)

        self.learn_box = QCheckBox("Show me the move at positions I haven't met before")
        self.learn_box.setChecked(self.settings.learn_new)
        self.learn_box.toggled.connect(self._on_learn_toggled)

        self.opponent_mistakes_box = QCheckBox("Opponent sometimes plays the moves marked as mistakes")
        self.opponent_mistakes_box.setChecked(self.settings.opponent_mistakes)
        self.opponent_mistakes_box.toggled.connect(self._on_opponent_mistakes_toggled)

        self.hide_comments_box = QCheckBox("Hide comments on the opponent's move until I've replied")
        self.hide_comments_box.setChecked(self.settings.hide_opponent_comments)
        self.hide_comments_box.toggled.connect(self._on_hide_comments_toggled)

        options = QGroupBox("Options")
        form = QFormLayout(options)
        form.addRow("Stop each game after (moves)", self.max_moves_box)
        form.addRow("New positions per day", self.new_per_day_box)
        form.addRow(self.learn_box)
        form.addRow(self.opponent_mistakes_box)
        form.addRow(self.hide_comments_box)

        self.errors_box = QPlainTextEdit()
        self.errors_box.setReadOnly(True)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        files_label = QLabel(
            "PGN files. Untick one to leave it out, or select several (Shift- or Ctrl-click) "
            "and click Enable or Disable."
        )
        files_label.setWordWrap(True)
        layout.addWidget(files_label)
        layout.addWidget(self.file_list, 2)
        layout.addLayout(buttons)
        layout.addWidget(options)
        layout.addWidget(QLabel("Problems found in the files"))
        layout.addWidget(self.errors_box, 1)
        return tab

    # Files and options

    def _populate_file_list(self) -> None:
        self.file_list.blockSignals(True)
        self.file_list.clear()
        for pgn in self.settings.files:
            item = QListWidgetItem(Path(pgn.path).name)
            item.setToolTip(pgn.path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if pgn.enabled else Qt.CheckState.Unchecked)
            self.file_list.addItem(item)
        self.file_list.blockSignals(False)
        self._on_file_selection_changed()

    def _on_file_selection_changed(self) -> None:
        selected = bool(self.file_list.selectedItems())
        for button in (self.remove_button, self.enable_button, self.disable_button):
            button.setEnabled(selected)

    def _add_files(self) -> None:
        start = str(Path(self.settings.files[-1].path).parent) if self.settings.files else str(Path.home())
        paths, _ = QFileDialog.getOpenFileNames(self, "Add PGN files", start, "PGN files (*.pgn);;All files (*)")
        known = {pgn.path for pgn in self.settings.files}
        added = [path for path in paths if path not in known]
        if not added:
            return
        self.settings.files.extend(PgnFile(path) for path in added)
        self.settings.save()
        self._populate_file_list()
        self._reload()

    def _remove_files(self) -> None:
        rows = sorted({self.file_list.row(item) for item in self.file_list.selectedItems()}, reverse=True)
        if not rows:
            return
        for row in rows:
            del self.settings.files[row]
        self.settings.save()
        self._populate_file_list()
        self._reload()

    def _on_file_toggled(self, item: QListWidgetItem) -> None:
        self.settings.files[self.file_list.row(item)].enabled = item.checkState() == Qt.CheckState.Checked
        self.settings.save()
        self._reload()

    def _set_selected_enabled(self, enabled: bool) -> None:
        """Tick or untick every selected file, then reload once."""
        rows = [self.file_list.row(item) for item in self.file_list.selectedItems()]
        changed = [row for row in rows if self.settings.files[row].enabled != enabled]
        if not changed:
            return
        state = Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked
        self.file_list.blockSignals(True)  # so _on_file_toggled doesn't reload after each one
        for row in changed:
            self.settings.files[row].enabled = enabled
            self.file_list.item(row).setCheckState(state)
        self.file_list.blockSignals(False)
        self.settings.save()
        self._reload()

    def _on_max_moves_changed(self, value: int) -> None:
        self.settings.max_moves = value
        self.settings.save()
        self._reload_timer.start()

    def _on_new_per_day_changed(self, value: int) -> None:
        self.settings.new_per_day = value
        self.settings.save()
        self.drill.new_per_day = value
        self._refresh()

    def _on_learn_toggled(self, checked: bool) -> None:
        self.settings.learn_new = checked
        self.settings.save()
        self.drill.learn_new = checked
        self._refresh()

    def _on_opponent_mistakes_toggled(self, checked: bool) -> None:
        self.settings.opponent_mistakes = checked
        self.settings.save()
        self.drill.opponent_mistakes = checked
        self._refresh()

    def _on_hide_comments_toggled(self, checked: bool) -> None:
        self.settings.hide_opponent_comments = checked
        self.settings.save()
        self.drill.hide_opponent_comments = checked
        if not checked:
            self.drill.current.revealed = True
        self._refresh()

    def _on_side_changed(self, index: int) -> None:
        self.settings.side = "white" if index == 0 else "black"
        self.settings.save()
        self._new_session()

    def _reload(self) -> None:
        """Load the ticked files, parsing any that are new or have changed, and start a fresh session."""
        self._reload_timer.stop()
        paths = [pgn.path for pgn in self.settings.files if pgn.enabled]
        self.repertoire = self.repertoire_cache.load(paths, self.settings.max_moves)
        errors = self.repertoire.errors
        self.errors_box.setPlainText("\n\n".join(errors) if errors else "No problems found.")
        self.tabs.setTabText(1, f"Files ({len(errors)} problem{'s' if len(errors) != 1 else ''})" if errors else "Files")
        self._new_session()

    # Training

    def _new_session(self) -> None:
        side = chess.WHITE if self.side_combo.currentIndex() == 0 else chess.BLACK
        self.drill = Drill(
            self.repertoire,
            side,
            progress=self.progress,
            learn_new=self.settings.learn_new,
            new_per_day=self.settings.new_per_day,
            opponent_mistakes=self.settings.opponent_mistakes,
            hide_opponent_comments=self.settings.hide_opponent_comments,
        )
        self.board_view.set_orientation(side)
        self._start_line()

    def _next_line(self) -> None:
        self.drill.new_line()
        self._start_line()

    def _start_line(self) -> None:
        self.line_id += 1
        self.review_node = None
        self.last_attempt = None
        self.showing_rejected = False
        self.hint_level = 0
        self._show_live()
        self._refresh()
        self._opponent_turn_if_needed()

    def _can_move(self) -> bool:
        return self.drill.is_user_turn and not self.showing_rejected and self.review_node is None

    def _opponent_turn_if_needed(self) -> None:
        if self.drill.line_finished or self.drill.board.turn == self.drill.side:
            return
        line_id = self.line_id
        QTimer.singleShot(OPPONENT_DELAY_MS, lambda: self._play_opponent(line_id))

    def _play_opponent(self, line_id: int) -> None:
        if line_id != self.line_id or self.drill.board.turn == self.drill.side:
            return
        if self.drill.play_opponent_move() is not None:
            self._show_live(animate=True)
            self._refresh()

    def _on_user_move(self, move: chess.Move) -> None:
        node = self.drill.try_move(move)
        if node.played:
            self.last_attempt = None
            self.hint_level = 0
            self._show_live()
            self._refresh()
            self._opponent_turn_if_needed()
            return

        # Show the rejected move for a moment, then take it back.
        self.last_attempt = node
        self.showing_rejected = True
        shown = self.drill.board.copy(stack=False)
        shown.push(move)
        self.board_view.set_position(shown, move, wrong=True)
        self._refresh()
        line_id = self.line_id
        QTimer.singleShot(WRONG_MOVE_MS, lambda: self._take_back(line_id))

    def _take_back(self, line_id: int) -> None:
        if line_id != self.line_id:
            return
        self.showing_rejected = False
        self._show_live()
        self._refresh()

    def _hint(self) -> None:
        """First press: highlight the piece to move. Second press: show the move."""
        if not self._can_move() or self.drill.teaching is not None:
            return
        self.hint_move = self.drill.hint()
        self.hint_level = min(self.hint_level + 1, 2)
        self._refresh()

    def _show_live(self, animate: bool = False) -> None:
        """Put the live position on the board, unless you're looking back at an earlier move."""
        if self.review_node is None:
            self.board_view.set_position(self.drill.board, self.drill.current.move, animate=animate)

    # Looking back at earlier moves

    def _review(self, node: TreeNode) -> None:
        if node is self.drill.current:
            self._resume()
            return
        self.review_node = node
        self.board_view.set_position(chess.Board(node.fen), node.move, wrong=node.kind is NodeKind.REJECTED)
        self._refresh()

    def _resume(self) -> None:
        if self.review_node is None:
            return
        self.review_node = None
        self._show_live()
        self._refresh()

    def _review_back(self) -> None:
        node = self.review_node or self.drill.current
        if node.parent is not None:
            self._review(node.parent)

    def _review_forward(self) -> None:
        node = self.review_node
        if node is None:
            return
        path = [self.drill.root] + self.drill.path()
        if node in path:  # on the live line: step towards the live position
            following = path[path.index(node) + 1]
        else:  # on another line, or the line after a mistake
            following = next(
                (child for child in node.children if child.kind is not NodeKind.REJECTED and not self.drill.is_hidden(child)),
                None,
            )
        if following is not None:
            self._review(following)

    # Display

    def _refresh(self) -> None:
        drill = self.drill
        can_move = self._can_move()
        self.board_view.set_user_color(drill.side if can_move else None)

        arrow = square = None
        teaching = drill.teaching if can_move else None
        if teaching is not None:
            arrow = teaching.move
        elif can_move and self.hint_level == 2:
            arrow = self.hint_move
        elif can_move and self.hint_level == 1:
            square = self.hint_move.from_square
        self.board_view.set_guides(arrow, square)

        counts = drill.counts()
        self.feedback.setHtml(self._feedback_html(counts))
        self.tree_view.show_tree(drill, self.review_node or drill.current)
        self.resume_button.setEnabled(self.review_node is not None)
        self.hint_button.setEnabled(can_move and teaching is None)

        repertoire = self.repertoire
        files = sum(pgn.enabled for pgn in self.settings.files)
        status = (
            f"{files} file{'s' if files != 1 else ''}, {repertoire.game_count} games, "
            f"{repertoire.position_count} positions    |    "
            f"Due: {counts.due}    New: {counts.new}    Learned: {counts.learned}"
        )
        if counts.due == 0 and counts.next_due is not None:
            status += f"    |    Next review in {describe_wait(counts.next_due - self.progress.now())}"
        if self._free_practice(counts):
            status += "    |    Free practice"
        self.statusBar().showMessage(status)

    def _free_practice(self, counts: Counts) -> bool:
        """Nothing is due and there are no new positions left for today."""
        return counts.due == 0 and not (counts.new and self.drill.new_allowed)

    def _feedback_html(self, counts: Counts) -> str:
        drill = self.drill
        if not self.repertoire.positions:
            return "<p>No repertoire loaded yet. Add some PGN files on the <b>Files</b> tab.</p>"

        if self.review_node is not None:
            node = self.review_node
            what = "the starting position" if node.move is None else f"<b>{html.escape(node.label)}</b>"
            return f"<p>Looking back at {what}. Press End or click Resume to carry on.</p>" + _notes([node])

        path = drill.path()
        lines = []
        if self.last_attempt is not None:
            attempt = self.last_attempt
            why = "is marked as a mistake" if attempt.verdict is Verdict.MISTAKE else "isn't in your repertoire"
            lines.append(_colored(RED, f"✗ <b>{html.escape(attempt.label)}</b> {why}. Try again."))
        else:
            # Your most recent correct move: the last move, or the one before the opponent's reply.
            yours = next((node for node in reversed(path[-2:]) if node.verdict is Verdict.CORRECT), None)
            if yours is not None:
                schedule = _schedule_text(drill.last_grade, self.progress)
                lines.append(_colored(GREEN, f"✓ <b>{html.escape(yours.label)}</b> is right.") + schedule)

        extra_notes = ""
        if drill.line_finished:
            side = "White" if drill.side == chess.WHITE else "Black"
            if not path:
                lines.append(f"There's nothing to practice as {side} from here. Check the files and side you've chosen.")
            else:
                if drill.line_mistakes == 0:
                    done = _colored(GREEN, "Line complete with no mistakes.")
                else:
                    missed = f"{drill.line_mistakes} position{'s' if drill.line_mistakes != 1 else ''}"
                    done = f"Line complete, with {missed} missed."
                if self._free_practice(counts):
                    done += " Nothing else is due, so further lines are free practice."
                lines.append(done + " Press N for the next line.")
        elif drill.is_user_turn:
            last = drill.current
            played = "" if last.move is None else f"Opponent played <b>{html.escape(last.label)}</b>. "
            teaching = drill.teaching
            if teaching is not None:
                label = html.escape(format_move(drill.board.fullmove_number, drill.board.turn, teaching.san))
                lines.append(played + _colored(BLUE, f"New position: play <b>{label}</b>, shown by the arrow."))
                if teaching.comments:
                    extra_notes = f"<p><b>{label}</b> {html.escape(' '.join(teaching.comments))}</p>"
            elif self.hint_level == 1:
                lines.append(played + _colored(BLUE, "Hint: move the highlighted piece."))
            elif self.hint_level == 2:
                lines.append(played + _colored(BLUE, f"Hint: play <b>{html.escape(drill.board.san(self.hint_move))}</b>."))
            elif self.last_attempt is None:
                lines.append(played + "Your move.")

        notes = path[-2:] + ([self.last_attempt] if self.last_attempt else [])
        return "".join(f"<p>{line}</p>" for line in lines) + _notes(notes) + extra_notes

    def closeEvent(self, event) -> None:
        self.settings.save()
        super().closeEvent(event)


def _colored(color: str, text: str) -> str:
    return f'<span style="color:{color}">{text}</span>'


def _schedule_text(grade: Grade | None, progress: Progress) -> str:
    """What your latest correct move did to that position's review schedule."""
    if grade is None or grade.outcome is Outcome.NOT_DUE:
        return ""
    if grade.outcome is Outcome.FAILED:
        return " You'll see this position again soon."
    wait = describe_wait(grade.due - progress.now())
    if grade.outcome is Outcome.LEARNED:
        return f" First review in {wait}."
    return f" Next review in {wait}."


def _notes(nodes: list[TreeNode]) -> str:
    """The revealed comments on these moves, one paragraph each."""
    return "".join(
        f"<p><b>{html.escape(node.label)}</b> {html.escape(' '.join(node.comments))}</p>"
        for node in nodes
        if node.comments
    )
