# Chess Opening Trainer

Practice chess openings from your own PGN files. Pick a side and the trainer
plays the other side, choosing moves from your PGNs. On your turn you have to
find a move from the PGNs that isn't marked as bad. Comments only appear once
the move they belong to has been played, so they explain the move without
giving away the answer. Spaced repetition decides which lines you see, so
practice goes where it's needed.

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
out first, add the two files in `examples/`. Untick a file to leave it out.
To switch several at once, select them (Shift- or Ctrl-click, or Ctrl+A for
all) and click **Enable** or **Disable**. Each file is only parsed the first
time it's loaded and again after you edit it, so switching files on and off
is quick. The trainer keeps your files and
options in `%USERPROFILE%\.chess_trainer\settings.json`, and your review
schedule in `progress.json` in the same folder.

## How a drill works

- Choose **Play as White** or **Black**. The trainer makes the opponent's
  moves from your PGNs.
- On your turn:
  - **A move in the PGN with no bad mark** is accepted, and its comment is shown.
  - **A move marked `?!`, `?` or `??`** is rejected. You'll see its comment,
    which is usually the reason it's bad, and have another go.
  - **A move that isn't in the PGN** is rejected, and you have another go.
- Rejected moves stay in the move list, struck through: red for known
  mistakes, grey for moves that aren't in the PGN.
- **The line after a mistake:** once you've found the right move, the PGN's
  line after the mistake appears in grey under it, with its comments. It
  stays hidden until then, because book notes on it often name the move you
  should have played.
- By default, the comment on the opponent's move stays hidden until you've
  replied, because it often hints at the answer. You can turn this off on the
  Files tab.
- The opponent sometimes plays moves that are marked as mistakes, so you have
  to find the refutation. You can turn this off on the Files tab too.
- **Hints:** press **H** once to highlight the piece to move, and again to see
  the move. A hint counts as getting that position wrong.
- The line ends when the PGNs run out. Press **N** for the next line. The move
  list builds up over a session but never shows anything that would give an
  answer away.

## Spaced repetition

Each position where it's your move is reviewed on its own schedule. Because
any unmarked move is accepted, what's being tested is "find a good move here".
Progress is saved per position, so editing or reorganizing your files doesn't
lose it.

- **Choosing lines:** the opponent's moves steer towards positions that are
  due for review. If nothing is due, they steer towards positions you haven't
  met yet, up to **New positions per day** (Files tab, default 10). With
  neither left, lines are chosen at random as free practice. A branch with
  more lines comes up more often, but only by the square root: a main line
  with 100 lines comes up 10 times as often as a one-move sideline, not 100.
- **New positions:** the first time you meet a position, an arrow shows you
  the move along with its comment, and you play it. Untick **Show me the move
  at positions I haven't met before** if you'd rather be tested on new
  positions straight away.
- **The schedule:** a due position you get right first time moves up the
  ladder of gaps: 4 hours, 1 day, 3 days, 1 week, 2 weeks, 1 month,
  3 months, 6 months. A wrong attempt or a hint sends it back to the start,
  due again in 5 minutes.
- **Positions that aren't due:** you still play every move along a line. A
  position that isn't due keeps its schedule when you get it right, but a
  mistake there still counts.
- **Status bar:** shows how many of your positions are due, new and learned
  for the side you're playing, and when the next review is.

To start over, delete `progress.json`. The ladder is the `INTERVALS` list in
`trainer/progress.py`.

Keys:

| Key        | Action                                   |
|------------|------------------------------------------|
| N          | Next line                                |
| H          | Hint (press twice to see the move)       |
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
  progress.py         the spaced-repetition schedule, saved as JSON
  settings.py         settings saved as JSON
  gui/board.py        the chessboard widget (drawing, drag and drop, promotion)
  gui/move_tree.py    the move list, laid out like a PGN viewer
  gui/main_window.py  the window, wiring the pieces together
tests/                tests for repertoire.py and drill.py
```

`repertoire.py`, `drill.py` and `progress.py` contain no GUI code. Chess rules and PGN
parsing come from [python-chess](https://python-chess.readthedocs.io/), and
the window from PySide6 (Qt).

Run the tests with:

```
.venv\Scripts\python -m pytest
```
