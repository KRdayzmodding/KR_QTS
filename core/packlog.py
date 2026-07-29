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

from dataclasses import dataclass, field
from pathlib import Path

PACKING, BINARIZE = "packing", "bin"
KINDS = (PACKING, BINARIZE)

WARNING, ERROR = "warning", "error"
_MARK_WORDS = (WARNING, ERROR)
_MAX_STARS = 3

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


def _parse_mark(line: str) -> tuple[str, int]:
    """Разбирает метку в начале строки: («warning»|«error»|"", длина метки).

    Метка бывает в видах «Warning: ...», «***warning***: ...», «ERRORS!».
    Именно в начале — иначе в предупреждения попадёт любая строка, где слово
    встретилось внутри (например «data\\sounds\\error.ogg:loading...»).

    Раньше здесь стояла регулярка `^\\s*\\*{0,3}\\s*(warning|error)s?\\s*...`.
    Два `\\s*` вокруг необязательных звёздочек давали катастрофический откат:
    длинную строку из пробелов движок разбивал между ними всеми возможными
    способами. Замер: строка из 4000 пробелов — 124 мс, и время на символ
    удваивалось с каждым удвоением длины. Обход посимвольно линеен по длине и
    делает ровно то же самое.
    """
    n = len(line)
    i = 0
    while i < n and line[i].isspace():
        i += 1
    stars = 0
    while i < n and line[i] == "*" and stars < _MAX_STARS:
        i += 1
        stars += 1
    while i < n and line[i].isspace():
        i += 1

    low = line.lower()
    for word in _MARK_WORDS:
        if not low.startswith(word, i):
            continue
        j = i + len(word)
        if j < n and low[j] == "s":          # warnings / errors
            j += 1
        while j < n and line[j].isspace():
            j += 1
        stars = 0
        while j < n and line[j] == "*" and stars < _MAX_STARS:
            j += 1
            stars += 1
        while j < n and line[j].isspace():
            j += 1
        if j < n and line[j] in ":!":
            j += 1
        # длина без хвостовых пробелов: красим саму метку, не отступ за ней
        return word, len(line[:j].rstrip())
    return "", 0


def mark_of(line: str) -> str:
    """warning | error | "" — что это за строка.

    Строки из IGNORED считаются обычными: так они разом выпадают и из
    счётчиков, и из отфильтрованного вида, и из подсветки.
    """
    word, _ = _parse_mark(line)
    return "" if not word or ignored(line) else word


def mark_len(line: str) -> int:
    """Длина самой метки — красим только её, а не строку целиком.

    У игнорируемых строк метки нет: иначе в полном тексте они подсвечивались
    бы наравне с настоящими предупреждениями.
    """
    word, length = _parse_mark(line)
    return 0 if not word or ignored(line) else length


@dataclass
class LogReport:
    """Один лог одного PBO."""
    name: str                 # имя pbo без расширения (оно же имя папки сорсов)
    kind: str                 # PACKING | BINARIZE
    path: Path | None = None
    lines: list[str] = field(default_factory=list)
    warnings: int = 0
    errors: int = 0
    truncated: bool = False   # строк было больше MAX_LINES, показана только часть

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


# Предел на число строк в памяти. Обычный лог сборки — десятки килобайт, но
# FullBuild большого мода с включённым подробным выводом раздувается на порядки,
# а показать в окне всё равно можно лишь малую часть.
MAX_LINES = 200_000


def read(name: str, kind: str) -> LogReport:
    """Читает лог и считает предупреждения с ошибками.

    Читается построчно, а не целиком: файл пишет чужой процесс, и его размер
    нам заранее неизвестен. Открытый файл при этом не мешает pboProject
    дописывать — Windows разрешает чтение параллельно с записью.

    Логи pboProject пишутся с BOM, поэтому utf-8-sig: иначе первая строка
    приходит с невидимым \\ufeff и ломает разбор метки в её начале.

    Ошибки чтения не поднимаются наверх: лог — вспомогательная вещь, из-за
    занятого или удалённого файла окно запаковки падать не должно. Что успели
    прочитать до обрыва, то и возвращаем.
    """
    path = log_path(name, kind)
    rep = LogReport(name=name, kind=kind, path=path)
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n").rstrip("\r")
                if len(rep.lines) < MAX_LINES:
                    rep.lines.append(line)
                elif not rep.truncated:
                    rep.truncated = True
                mark = mark_of(line)
                if mark == WARNING:
                    rep.warnings += 1
                elif mark == ERROR:
                    rep.errors += 1
    except OSError:
        # PermissionError — файл держит pboProject; FileNotFoundError — лога
        # этой сборки ещё нет либо его успели удалить
        pass
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
