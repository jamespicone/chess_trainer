"""Spaced repetition: when each of your positions is next due for review.

A card is a position where it's your move and the repertoire has at least one
good move: the test is "find a good move here". Cards are stored by position
key, so editing or reorganizing PGN files doesn't lose your progress.

Scheduling uses a fixed ladder of gaps. Getting a due position right first time
moves it up a step; any wrong attempt (or a hint) sends it back to the bottom.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

PROGRESS_PATH = Path.home() / ".chess_trainer" / "progress.json"

# The gap before the next review, for each step up the ladder.
INTERVALS = [
    timedelta(hours=4),
    timedelta(days=1),
    timedelta(days=3),
    timedelta(weeks=1),
    timedelta(weeks=2),
    timedelta(days=30),
    timedelta(days=90),
    timedelta(days=180),
]

# A position you got wrong comes back this soon, so you see it again this session.
RETRY_AFTER = timedelta(minutes=5)


@dataclass
class Card:
    step: int  # index into INTERVALS of the current gap; -1 after a wrong answer
    due: datetime
    added: datetime  # when you first met this position
    reviews: int = 0
    lapses: int = 0  # times you got it wrong


class Progress:
    """Every card you've met so far, saved as JSON after each change."""

    def __init__(self, path: Path | None = None, clock: Callable[[], datetime] = datetime.now) -> None:
        self.path = path  # None means don't save (used by tests and scripts)
        self.clock = clock
        self.cards: dict[str, Card] = {}

    @classmethod
    def load(cls, path: Path = PROGRESS_PATH) -> Progress:
        progress = cls(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, card in data["cards"].items():
                progress.cards[key] = Card(
                    step=card["step"],
                    due=datetime.fromisoformat(card["due"]),
                    added=datetime.fromisoformat(card["added"]),
                    reviews=card.get("reviews", 0),
                    lapses=card.get("lapses", 0),
                )
        except FileNotFoundError:
            pass
        except (ValueError, KeyError, TypeError, AttributeError):
            # Keep a damaged file rather than overwriting it, and start afresh.
            path.replace(path.with_name(path.stem + ".damaged.json"))
            progress.cards.clear()
        return progress

    def save(self) -> None:
        if self.path is None:
            return
        cards = {
            key: {
                "step": card.step,
                "due": card.due.isoformat(timespec="seconds"),
                "added": card.added.isoformat(timespec="seconds"),
                "reviews": card.reviews,
                "lapses": card.lapses,
            }
            for key, card in self.cards.items()
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temporary file first so a crash can't leave a half-written file.
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "cards": cards}, indent=1), encoding="utf-8")
        temporary.replace(self.path)

    def now(self) -> datetime:
        return self.clock()

    def is_due(self, key: str) -> bool:
        card = self.cards.get(key)
        return card is not None and card.due <= self.now()

    def added_today(self) -> int:
        """How many new positions you've met today, for the daily limit."""
        today = self.now().date()
        return sum(1 for card in self.cards.values() if card.added.date() == today)

    def learned(self, key: str) -> Card:
        """A new position, played correctly for the first time: start at the bottom of the ladder."""
        now = self.now()
        card = self.cards[key] = Card(step=0, due=now + INTERVALS[0], added=now)
        self.save()
        return card

    def passed(self, key: str) -> Card:
        """A due position, right first time: move up a step."""
        card = self.cards[key]
        card.step = min(card.step + 1, len(INTERVALS) - 1)
        card.due = self.now() + INTERVALS[card.step]
        card.reviews += 1
        self.save()
        return card

    def failed(self, key: str) -> Card:
        """A wrong attempt or a hint: back to the bottom, and due again shortly."""
        now = self.now()
        card = self.cards.get(key)
        if card is None:
            card = self.cards[key] = Card(step=-1, due=now, added=now)
        card.step = -1
        card.due = now + RETRY_AFTER
        card.reviews += 1
        card.lapses += 1
        self.save()
        return card


def describe_wait(wait: timedelta) -> str:
    """'5 minutes', '4 hours', '3 days', '2 weeks', '6 months', ..."""
    minutes = max(1, round(wait.total_seconds() / 60))
    units = [(60 * 24 * 30, "month"), (60 * 24 * 7, "week"), (60 * 24, "day"), (60, "hour"), (1, "minute")]
    for size, unit in units:
        if minutes >= size:
            count = round(minutes / size)
            return f"{count} {unit}{'s' if count != 1 else ''}"
    return "a moment"
