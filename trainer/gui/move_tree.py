"""The move list: the moves you've played, your rejected attempts, and any revealed comments.

It's laid out like a PGN viewer. The line you're on runs along as a paragraph,
rejected attempts sit inline in brackets, and other lines you've played this
session branch off as indented paragraphs, as does the PGN's line after a
mistake once you've found the right move. Anything that would show you an
answer is left out (see Drill.is_hidden).
"""

from __future__ import annotations

import html
from typing import NamedTuple

import chess
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import QTextBrowser, QWidget

from ..drill import Drill, NodeKind, TreeNode, Verdict

MISTAKE_COLOR = "#c62828"
NOT_IN_REPERTOIRE_COLOR = "#8a8a8a"
REFUTATION_COLOR = "#7a7a7a"
COMMENT_COLOR = "#5a7d9a"
INDENT_PX = 18


class TreeColors(NamedTuple):
    text: str
    highlight: str
    highlight_text: str


class _Writer:
    """Builds the tree as a list of indented paragraphs."""

    def __init__(self, drill: Drill, highlighted: TreeNode | None, colors: TreeColors) -> None:
        self.drill = drill
        self.highlighted = highlighted
        self.colors = colors
        self.paragraphs: list[tuple[int, list[str]]] = [(0, [])]
        self.links: dict[str, TreeNode] = {}

    def new_paragraph(self, depth: int) -> None:
        if self.paragraphs[-1][1]:
            self.paragraphs.append((depth, []))
        else:
            self.paragraphs[-1] = (depth, [])

    def move(self, node: TreeNode, numbered: bool, brackets: bool = False) -> bool:
        """Write a move and its comments. Returns True if a comment was written,
        since the move after a comment needs its move number repeating."""
        link = f"n{len(self.links)}"
        self.links[link] = node

        # White's moves always carry their number; Black's only when needed.
        text = node.label if numbered or node.color == chess.WHITE else node.san + node.glyph
        if node.verdict is Verdict.MISTAKE:
            styles = [f"color:{MISTAKE_COLOR}", "text-decoration:line-through"]
        elif node.verdict is Verdict.NOT_IN_REPERTOIRE:
            styles = [f"color:{NOT_IN_REPERTOIRE_COLOR}", "text-decoration:line-through"]
        elif node.kind is NodeKind.REFUTATION:
            styles = [f"color:{REFUTATION_COLOR}"]
        else:
            styles = [f"color:{self.colors.text}"]
        anchor = ""
        if node is self.highlighted:
            styles += [f"background-color:{self.colors.highlight}", f"color:{self.colors.highlight_text}"]
            anchor = '<a name="here"></a>'

        piece = f'{anchor}<a href="{link}"><span style="{";".join(styles)}">{html.escape(text)}</span></a>'
        comment = ""
        if node.comments:
            joined = html.escape(" • ".join(node.comments))
            comment = f' <span style="color:{COMMENT_COLOR}; font-style:italic">{joined}</span>'
        piece += comment
        if brackets:
            piece = f"({piece})"
        self.paragraphs[-1][1].append(piece)
        return bool(comment)

    def html(self) -> str:
        return "".join(
            f'<p style="margin-top:3px; margin-bottom:3px; margin-left:{depth * INDENT_PX}px">{" ".join(items)}</p>'
            for depth, items in self.paragraphs
            if items
        )


def render_tree(drill: Drill, highlighted: TreeNode | None, colors: TreeColors) -> tuple[str, dict[str, TreeNode]]:
    """Return the tree as HTML, plus a map from each move's link to its node."""
    writer = _Writer(drill, highlighted, colors)
    _write_line(writer, drill.root, depth=0, numbered=True)
    if not writer.links:
        return '<p style="color:gray">Your moves will appear here.</p>', {}
    return writer.html(), writer.links


def _write_line(writer: _Writer, node: TreeNode, depth: int, numbered: bool) -> None:
    """Write the line that continues from node, branching off any other lines on the way."""
    while True:
        visible = [child for child in node.children if not writer.drill.is_hidden(child)]
        lines = [child for child in visible if child.kind is not NodeKind.REJECTED]
        rejected = [child for child in visible if child.kind is NodeKind.REJECTED]
        if not visible:
            return

        main = lines[0] if lines else None
        if main is not None:
            numbered = writer.move(main, numbered)
        # A rejected attempt sits inline, unless the line after it is showing.
        with_line = [attempt for attempt in rejected if any(not writer.drill.is_hidden(c) for c in attempt.children)]
        for attempt in rejected:
            if attempt not in with_line:
                writer.move(attempt, numbered=True, brackets=True)
                numbered = True
        for branch in with_line + lines[1:]:
            writer.new_paragraph(depth + 1)
            _write_line(writer, branch, depth + 1, writer.move(branch, numbered=True))
            numbered = True
        if with_line or len(lines) > 1:
            writer.new_paragraph(depth)  # carry on with the main line
        if main is None:
            return
        node = main


class MoveTreeView(QTextBrowser):
    """Shows the move tree. Emits node_clicked when you click a move."""

    node_clicked = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # leave the arrow keys for stepping through moves
        font = QFont(self.font())
        font.setPointSize(11)
        self.setFont(font)
        self.document().setDefaultStyleSheet("a { text-decoration: none; }")
        self.anchorClicked.connect(self._on_anchor_clicked)
        self._links: dict[str, TreeNode] = {}

    def show_tree(self, drill: Drill, highlighted: TreeNode | None) -> None:
        palette = self.palette()
        colors = TreeColors(
            text=palette.color(QPalette.ColorRole.Text).name(),
            highlight=palette.color(QPalette.ColorRole.Highlight).name(),
            highlight_text=palette.color(QPalette.ColorRole.HighlightedText).name(),
        )
        text, self._links = render_tree(drill, highlighted, colors)
        self.setHtml(text)
        self.scrollToAnchor("here")

    def _on_anchor_clicked(self, url: QUrl) -> None:
        node = self._links.get(url.toString())
        if node is not None:
            self.node_clicked.emit(node)
