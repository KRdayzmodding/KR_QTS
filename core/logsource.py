"""Источники логов: поиск папок, живой хвост с подхватом нового файла сессии."""
from __future__ import annotations

import os
import re
from pathlib import Path

from .launcher import resolve_path
from .presets import ServerPreset
from .settings import Settings, EXPERIMENTAL

# Файлы логов DayZ (новый файл на каждую сессию, с таймштампом в имени)
LOG_PATTERNS = ("*.RPT", "script*.log", "*.ADM", "crash*.log", "error.log")

_ERROR_RE = re.compile(r"error|critical|fatal|exception|can't|cannot find|missing", re.IGNORECASE)
_WARN_RE = re.compile(r"warning|obsolete|deprecated|unable to", re.IGNORECASE)


def classify(line: str) -> str:
    """info | warning | error — для цветовой дифференциации."""
    if _ERROR_RE.search(line):
        return "error"
    if _WARN_RE.search(line):
        return "warning"
    return "info"


def server_log_dir(preset: ServerPreset, settings: Settings, branch: str) -> Path | None:
    from .layout import resolve_profiles
    p = resolve_profiles(preset.profiles, settings, branch, preset.mode)
    return Path(p) if p else None


def client_log_dir(branch: str) -> Path | None:
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return None
    # У Experimental-клиента своя папка (уточняется; DayZ Exp — наиболее вероятное имя)
    name = "DayZ Exp" if branch == EXPERIMENTAL else "DayZ"
    p = Path(local) / name
    if branch == EXPERIMENTAL and not p.is_dir():
        p = Path(local) / "DayZ"
    return p


def log_files(directory: Path) -> list[Path]:
    """Все файлы логов в папке, новые первыми."""
    files: list[Path] = []
    if directory and directory.is_dir():
        for pattern in LOG_PATTERNS:
            files.extend(directory.glob(pattern))
    files = list(set(files))
    files.sort(key=lambda f: f.stat().st_mtime if f.exists() else 0, reverse=True)
    return files


class LogTailer:
    """Читает лог инкрементально; при появлении более нового файла переключается на него."""

    def __init__(self, directory: Path, pattern_filter: str | None = None):
        self.directory = directory
        self.pattern_filter = pattern_filter  # например "*.RPT", None = все
        self.current: Path | None = None
        self._pos = 0

    def _candidates(self) -> list[Path]:
        files = log_files(self.directory)
        if self.pattern_filter:
            files = [f for f in files if f.match(self.pattern_filter)]
        return files

    def poll(self) -> list[str]:
        """Новые строки с момента прошлого вызова (может переключить файл)."""
        files = self._candidates()
        if not files:
            return []
        newest = files[0]
        lines: list[str] = []

        if self.current != newest:
            # новая сессия — начинаем файл с начала
            self.current = newest
            self._pos = 0
            lines.append(f"=== {newest.name} ===")

        try:
            size = self.current.stat().st_size
            if size < self._pos:  # файл пересоздан/обрезан
                self._pos = 0
            if size > self._pos:
                with open(self.current, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(self._pos)
                    chunk = f.read()
                    self._pos = f.tell()
                lines.extend(chunk.splitlines())
        except OSError:
            pass
        return lines


def search_in_files(directory: Path, query: str, current_only: Path | None = None,
                    max_results: int = 500) -> list[tuple[str, int, str]]:
    """Поиск по логам. Возвращает [(имя файла, номер строки, строка)]."""
    results: list[tuple[str, int, str]] = []
    q = query.lower()
    files = [current_only] if current_only else log_files(directory)
    for f in files:
        if not f or not f.is_file():
            continue
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    if q in line.lower():
                        results.append((f.name, i, line.rstrip()))
                        if len(results) >= max_results:
                            return results
        except OSError:
            continue
    return results


def delete_logs(directory: Path) -> int:
    """Удаляет все файлы логов в папке. Возвращает число удалённых."""
    n = 0
    for f in log_files(directory):
        try:
            f.unlink()
            n += 1
        except OSError:
            pass
    return n
