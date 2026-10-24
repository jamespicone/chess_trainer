"""Settings that persist between runs, saved as a small JSON file in your home folder."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

SETTINGS_PATH = Path.home() / ".chess_trainer" / "settings.json"


@dataclass
class PgnFile:
    path: str
    enabled: bool = True


@dataclass
class Settings:
    files: list[PgnFile] = field(default_factory=list)
    side: str = "white"  # "white" or "black"
    max_moves: int = 0  # stop each game after this many moves; 0 for no limit
    new_per_day: int = 10
    learn_new: bool = True  # show the good moves you haven't played yet
    opponent_mistakes: bool = True
    hide_opponent_comments: bool = True
    # Where to save; None means don't save (used by tests and scripts).
    path: Path | None = field(default=None, repr=False)

    @classmethod
    def load(cls, path: Path = SETTINGS_PATH) -> Settings:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            files = [PgnFile(**entry) for entry in data.pop("files", [])]
            return cls(files=files, path=path, **data)
        except FileNotFoundError:
            return cls(path=path)
        except (OSError, ValueError, TypeError):
            # A damaged settings file shouldn't stop the app starting.
            return cls(path=path)

    def save(self) -> None:
        if self.path is None:
            return
        data = asdict(self)
        del data["path"]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
