import json
from datetime import datetime, timedelta

from trainer.progress import INTERVALS, RETRY_AFTER, Progress, describe_wait


class Clock:
    """A clock the tests can move forward."""

    def __init__(self) -> None:
        self.time = datetime(2026, 1, 1, 9, 0)

    def __call__(self) -> datetime:
        return self.time

    def advance(self, wait: timedelta) -> None:
        self.time += wait


def test_cards_climb_the_ladder_and_fall_back_on_a_mistake():
    clock = Clock()
    progress = Progress(clock=clock)
    card = progress.learned("position")
    assert card.step == 0 and card.due == clock.time + INTERVALS[0]
    assert not progress.is_due("position")

    clock.advance(INTERVALS[0])
    assert progress.is_due("position")
    card = progress.passed("position")
    assert card.step == 1 and card.due == clock.time + INTERVALS[1]

    card = progress.failed("position")
    assert card.step == -1 and card.due == clock.time + RETRY_AFTER and card.lapses == 1
    clock.advance(RETRY_AFTER)
    card = progress.passed("position")
    assert card.step == 0 and card.due == clock.time + INTERVALS[0]


def test_the_top_step_repeats():
    progress = Progress()
    progress.learned("position")
    for _ in range(len(INTERVALS) + 3):
        card = progress.passed("position")
    assert card.step == len(INTERVALS) - 1


def test_new_positions_are_counted_per_day():
    clock = Clock()
    progress = Progress(clock=clock)
    progress.learned("a")
    progress.failed("b")  # a position you got wrong the first time you met it
    assert progress.added_today() == 2
    clock.advance(timedelta(days=1))
    assert progress.added_today() == 0


def test_saving_and_loading(tmp_path):
    path = tmp_path / "progress.json"
    progress = Progress(path)
    progress.learned("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -")
    progress.failed("another")
    progress.played("another", "e2e4")
    loaded = Progress.load(path)
    assert loaded.cards.keys() == progress.cards.keys()
    assert loaded.cards["another"].step == -1
    assert loaded.cards["another"].due == progress.cards["another"].due.replace(microsecond=0)
    assert loaded.cards["another"].moves == {"e2e4"}


def test_a_file_saved_before_moves_were_recorded_still_loads(tmp_path):
    path = tmp_path / "progress.json"
    card = {"step": 0, "due": "2026-01-01T13:00:00", "added": "2026-01-01T09:00:00", "reviews": 0, "lapses": 0}
    path.write_text(json.dumps({"version": 1, "cards": {"position": card}}), encoding="utf-8")
    assert Progress.load(path).cards["position"].moves == set()


def test_a_damaged_file_is_kept_aside(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text("{not json", encoding="utf-8")
    progress = Progress.load(path)
    assert progress.cards == {}
    assert (tmp_path / "progress.damaged.json").exists()


def test_describe_wait():
    assert describe_wait(timedelta(minutes=5)) == "5 minutes"
    assert describe_wait(timedelta(hours=4)) == "4 hours"
    assert describe_wait(timedelta(days=1)) == "1 day"
    assert describe_wait(timedelta(weeks=2)) == "2 weeks"
    assert describe_wait(timedelta(days=180)) == "6 months"
