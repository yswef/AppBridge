"""Persistent user settings stored as JSON in the user data directory."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)


@dataclass
class Settings:
    library_dir: str = ""
    language: str = "system"  # system | ar | en
    theme: str = "system"  # system | light | dark
    split_size_mb: int = 2048
    include_install_bat: bool = True
    verify_before_install: bool = True
    show_system_apps: bool = False


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or paths.user_data_dir() / "settings.json"
        self._lock = threading.Lock()
        self.settings = self._load()

    def _load(self) -> Settings:
        s = Settings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            known = {f.name for f in fields(Settings)}
            for k, v in data.items():
                if k in known and isinstance(v, type(getattr(s, k))):
                    setattr(s, k, v)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log.warning("Could not read settings (%s); using defaults", e)
        if not s.library_dir:
            s.library_dir = str(paths.default_library_dir())
        return s

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self.settings), ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def update(self, changes: dict) -> Settings:
        known = {f.name: type(getattr(self.settings, f.name)) for f in fields(Settings)}
        for k, v in changes.items():
            if k not in known:
                continue
            if known[k] is int and isinstance(v, (int, float)) and not isinstance(v, bool):
                v = int(v)
            if not isinstance(v, known[k]):
                raise ValueError(f"Invalid value for {k}")
            setattr(self.settings, k, v)
        self.save()
        return self.settings

    def as_dict(self) -> dict:
        return asdict(self.settings)
