# Chess Opening Trainer

Practice chess openings from your own PGN files. Pick a side and the trainer
plays the other side, choosing moves from your PGNs. On your turn you have to
find a move from the PGNs that isn't marked as bad. Comments only appear once
the move they belong to has been played, so they explain the move without
giving away the answer.

## Setup

You need Python 3.10 or newer.

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## Running

```
.venv\Scripts\python -m trainer
```

Go to the **Files** tab and click **Add files…** to add your PGNs. To try it
out first, add the two files in `examples/`. The trainer remembers your files
and options in `%USERPROFILE%\.chess_trainer\settings.json`.

## How a drill works

- Choose **Play as White** or **Black**. The trainer picks a line at random,
  making the opponent's moves from your PGNs.
- On your turn:
  - **A move in the PGN with no bad mark** is accepted, and its comment is shown.
  - **A move marked `?!`, `?` or `??`** is rejected. You'll see its comment,
    which is usually the reason it's bad, and have another go.
  - **A move that isn't in the PGN** is rejected, and you have another go.
- Rejected moves stay in the move list, struck through: red for known
  mistakes, grey for moves that aren't in the PGN.
- By default, the comment on the opponent's move stays hidden until you've
  replied, because it often hints at the answer. You can turn this off on the
  Files tab.
- The opponent sometimes plays moves that are marked as mistakes, so you have
  to find the refutation. You can turn this off on the Files tab too.
- The line ends when the PGNs run out. Press **N** for the next line. The move
  list builds up over a session but never shows moves beyond the current
  position.

Keys:

| Key        | Action                                   |
|------------|------------------------------------------|
| N          | Next line                                |
| Left/Right | Step back/forward through earlier moves  |
| End or Esc | Return to the live position              |
| F5         | Reload the files (after you've edited them) |

You can also click any move in the list to look back at it.

## Writing PGNs for the trainer

All of your files are merged into one repertoire, matched by position, so
transpositions between files and lines work automatically.

- **Mark bad moves with a glyph:** `?!`, `?` or `??` (or `$6`, `$2`, `$4`).
  The trainer only reads these glyphs, so writing "this is a mistake" in a
  comment won't stop the move being accepted.
- **Any move without a bad glyph counts as correct,** including every move in
  your own games. Mark your own slips, or limit how far the game is used (see
  below).
- **Put a comment straight after the move it explains:** `5. d4 {Striking in
  the centre.}`. A comment at the start of a variation belongs to that
  variation's first move: `( {The quiet line.} 5. d3 )`.
- **Variations can be nested** as deeply as you like.
- **If two files disagree** about a move (one marks it `?` and the other
  doesn't), the bad mark wins and both comments are shown.
- **To start a game from a position other than the initial one,** use the
  standard `[SetUp "1"]` and `[FEN "..."]` headers.
- **Games that run past the opening:** the **Stop each game after** option on
  the Files tab applies to every file. To limit a single game instead, give it
  a header such as `[TrainerMaxMoves "12"]`, which uses only the first 12 moves
  of that game. `examples/club_game.pgn` shows this.

If a file contains a typo, such as an illegal or ambiguous move, the Files tab
shows which file, game and move number it's in. Everything before the typo is
still loaded. Fix the file and press F5.

## Code layout

```
trainer/
  repertoire.py       load PGNs and merge them into one table keyed by position
  drill.py            a session: check your moves, choose the opponent's, keep the move tree
  settings.py         settings saved as JSON
  gui/board.py        the chessboard widget (drawing, drag and drop, promotion)
  gui/move_tree.py    the move list, laid out like a PGN viewer
  gui/main_window.py  the window, wiring the pieces together
tests/                tests for repertoire.py and drill.py
```

`repertoire.py` and `drill.py` contain no GUI code. Chess rules and PGN
parsing come from [python-chess](https://python-chess.readthedocs.io/), and
the window from PySide6 (Qt).

Run the tests with:

```
.venv\Scripts\python -m pytest
```
