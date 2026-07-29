"""Разбор логов pboProject.

pboProject — GUI-приложение и в stdout не пишет ничего (перенаправлять его
вывод к тому же нельзя, см. core/packer.pack_source). Вся диагностика идёт в
два файла на рабочем диске:

    <temp>\\<имя>.packing.log — сборка pbo
    <temp>\\<имя>.bin.log     — бинаризация

Отсюда берутся и счётчики для журнала на главной странице, и содержимое окон
«Логи запаковки».
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

PACKING, BINARIZE = "packing", "bin"
KINDS = (PACKING, BINARIZE)

# Метка ставится в начале строки: «Warning: ...», «***warning***: ...».
# Именно в начале — иначе в предупреждения попадёт любая строка, где слово
# встретилось внутри (например «data\\sounds\\error.ogg:loading...»).
_MARK_RE = re.compile(r"^\s*\*{0,3}\s*(warning|error)s?\s*\*{0,3}\s*[:!]?", re.I)

WARNING, ERROR = "warning", "error"

# Предупреждения, которые для нашей сборки шума не несут: они сыплются
# десятками на каждой бинаризации и заслоняют собой всё остальное. Такие
# строки не считаются и в отфильтрованном виде не показываются — но остаются
# в полном тексте по галке «Показать полностью».
# Сравнение по подстроке в нижнем регистре: у этих предупреждений хвост
# всегда разный (путь к модели, значение сетки).
IGNORED = (
    "terrain grid",
    "no components in",
)


def ignored(line: str) -> bool:
    low = line.lower()
    return any(frag in low for frag in IGNORED)


def mark_of(line: str) -> str:
    """warning | error | "" — что это за строка.

    Строки из IGNORED считаются обычными: так они разом выпадают и из
    счётчиков, и из отфильтрованного вида, и из подсветки.
    """
    m = _MARK_RE.match(line)
    if not m or ignored(line):
        return ""
    return m.group(1).lower()


def mark_len(line: str) -> int:
    """Длина самой метки — красим только её, а не строку целиком.

    У игнорируемых строк метки нет: иначе в полном тексте они подсвечивались
    бы наравне с настоящими предупреждениями.
    """
    if not mark_of(line):
        return 0
    return len(_MARK_RE.match(line).group(0).rstrip())


@dataclass
class LogReport:
    """Один лог одного PBO."""
    name: str                 # имя pbo без расширения (оно же имя папки сорсов)
    kind: str                 # PACKING | BINARIZE
    path: Path | None = None
    lines: list[str] = field(default_factory=list)
    warnings: int = 0
    errors: int = 0

    @property
    def exists(self) -> bool:
        return bool(self.lines) or (self.path is not None and self.path.is_file())

    @property
    def clean(self) -> bool:
        return not (self.warnings or self.errors)

    def marked_lines(self) -> list[str]:
        """Только предупреждения и ошибки — режим по умолчанию в окне логов."""
        return [ln for ln in self.lines if mark_of(ln)]


def temp_dir() -> Path:
    """Папка логов pboProject: путь берётся из его же настроек в реестре."""
    drive, temp = "P:\\", "temp"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Mikero\pboProject\Settings") as k:
            for name, default in (("prj_Pdrive", drive), ("drive_temp_folder", temp)):
                try:
                    value = winreg.QueryValueEx(k, name)[0]
                except OSError:
                    continue
                if value:
                    if name == "prj_Pdrive":
                        drive = value
                    else:
                        temp = value
    except (ImportError, OSError):
        pass
    p = Path(temp)
    return p if p.is_absolute() else Path(drive) / temp


def log_path(name: str, kind: str) -> Path:
    suffix = "packing.log" if kind == PACKING else "bin.log"
    return temp_dir() / f"{name}.{suffix}"


def read(name: str, kind: str) -> LogReport:
    """Читает лог и считает предупреждения с ошибками.

    Логи pboProject пишутся с BOM, поэтому utf-8-sig: иначе первая строка
    приходит с невидимым \\ufeff и ломает разбор метки в её начале.
    """
    path = log_path(name, kind)
    rep = LogReport(name=name, kind=kind, path=path)
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return rep
    rep.lines = text.splitlines()
    for line in rep.lines:
        mark = mark_of(line)
        if mark == WARNING:
            rep.warnings += 1
        elif mark == ERROR:
            rep.errors += 1
    return rep


def read_all(names: list[str], kind: str) -> list[LogReport]:
    return [read(n, kind) for n in names]


def counts(name: str) -> tuple[int, int]:
    """Суммарные (предупреждения, ошибки) по обоим логам одного PBO —
    для короткой пометки в журнале главной страницы."""
    w = e = 0
    for kind in KINDS:
        rep = read(name, kind)
        w += rep.warnings
        e += rep.errors
    return w, e
