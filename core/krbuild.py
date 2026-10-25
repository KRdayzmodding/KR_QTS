"""Запаковка через [KR] Project Builder — чужую программу из Dev Toolkit.

Движок там свой целиком: рапификация конфигов, бинаризация моделей, текстуры,
звук, упаковка, около полусотни проверок и автоисправлений. Мы его не
повторяем и не тащим к себе внутрь — зовём `ProjectBuilder.exe` и показываем
ход в своём журнале. Код живёт в другом репозитории и активно меняется; отдельный
процесс — это и есть граница, за которой его изменения нас не ломают.

Разговариваем машинно: с ключом `--json` программа печатает в stdout по
строке JSON на событие, а человеческий текст уводит в stderr. Разбирать её
текстовый лог было бы дешевле на день работы и дороже потом: поменяется
формулировка — мы молча перестанем видеть ошибки.

Договорённость о событиях (поле `event`, версия в `v`):

    start    source, target, prefix
    stage    stage (scan|copy|build|refs|texheaders|pack), done, total
    finding  level (error|warning|info), file, path, line?, col?, where?,
             text, code, mark? — mark=true значит, что находку можно пометить
             на модели командой `ProjectBuilder.exe --mark МОДЕЛЬ КОД`
             (в счёт журнала идут только error и warning)
    decision text
    done     ok, packed, pbo, files, bytes, seconds, errors, warnings, log
    refused  text — отказ до начала работы, следом придёт done с ok=false

Неизвестные события и поля пропускаем молча: так на той стороне могут
добавлять новое, не спрашивая нас.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .mods import ModInfo
from .settings import Settings

# Сколько ждём одну сборку. Их упаковщик занимает все ядра и на большом моде
# работает минутами; час — это «что-то пошло не так», а не «долго».
TIMEOUT_SEC = 3600

# Имена этапов у них машинные, а показываем мы своими словами: у QTS три
# языка, и строки должны приходить из нашего словаря, а не из чужого вывода.
STAGES = {
    "scan": "mods.stage_scan",
    "copy": "mods.stage_copy",
    "build": "mods.stage_build",
    "refs": "mods.stage_refs",
    "texheaders": "mods.stage_texheaders",
    "pack": "mods.stage_pack",
    # Подпись идёт после упаковки и только когда ключ задан в настройках KR
    # Build. Своего ключа мы ему не передаём: командной строкой он их не
    # принимает, и подменять его настройки мы не будем.
    "sign": "mods.stage_sign",
}


def gui_exe(settings: Settings) -> str:
    """Окно Project Builder; пусто — не нашли.

    Ищется в той же общей папке инструментов, что и консольная половина:
    у тулкита «Имя.exe» — командная строка, «Имя_GUI.exe» — окно, и помнить
    это должен не человек.
    """
    from .settings import PACKER_GUI_NAMES, find_first_tool, toolkit_root
    root = toolkit_root(getattr(settings, "krbuild_exe", ""))
    return find_first_tool(root, PACKER_GUI_NAMES) if root else ""


def exe_path(settings: Settings) -> str:
    """Путь к exe: в настройках может стоять как сам файл, так и его папка."""
    getter = getattr(settings, "krbuild_cli", None)
    return getter() if callable(getter) else ""


def version_of(exe: str) -> str:
    """Версия программы из runtime/versions.json рядом с ней; пусто — не знаем.

    Сами версии мы ни с чем не сверяем: это подпись под найденным путём,
    чтобы человек видел, какую именно сборку подхватил QTS, когда у него на
    диске их несколько.
    """
    path = Path(exe or "")
    if not str(path):
        return ""
    # У установки версия лежит в tools/<Тулза>/current — строка ASCII без
    # перевода строки. Это их договор с нами: тот же файл читает запускалка
    # на C, выбирая папку версии, поэтому формат не поменяется молча.
    # state.json рядом с ним выглядит удобнее, но это внутренний файл
    # обновлялки. Спрашивать саму программу (--version) дороже: это запуск
    # процесса ради строки под полем ввода.
    stem = path.stem
    if stem.endswith("_GUI"):
        stem = stem[:-4]
    current = path.parent / "tools" / stem / "current"
    try:
        text = current.read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        text = ""
    if text:
        return text
    # Распакованная раздача: tools/ там нет, версии лежат рядом с exe.
    book = path.parent / "runtime" / "versions.json"
    try:
        data = json.loads(book.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    entry = data.get(path.stem) if isinstance(data, dict) else None
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("version") or "")


def missing(settings: Settings) -> str:
    """Почему нельзя паковать этим движком. Пусто — можно."""
    from .settings import toolkit_root
    root = toolkit_root(getattr(settings, "krbuild_exe", ""))
    if not root:
        return ("Dev Toolkit не установлен, и папка не задана в настройках")
    exe = exe_path(settings)
    if not exe or not Path(exe).is_file():
        return f"в папке {root} не нашёлся запаковщик (ProjectBuilder.exe)"
    return ""


def pack(settings: Settings, mod: ModInfo, source_dir: str,
         on_event=None, stop=None) -> tuple[bool, str]:
    """Собирает один PBO. Возвращает (успех, текст для журнала).

    on_event(dict) зовётся на каждое разобранное событие — из того же потока,
    в котором идёт сборка. Через него страница рисует этапы и находки.

    stop — объект с методом is_set(): пока сборка идёт, мы его опрашиваем и на
    взведённом просим программу остановиться строкой в stdin. Убивать процесс
    не нужно: своя остановка у неё штатная, она не оставляет мусора и честно
    отвечает итогом.
    """
    why = missing(settings)
    if why:
        return False, why
    if not Path(source_dir).is_dir():
        return False, f"папка сорсов не найдена: {source_dir}"

    args = [exe_path(settings), native(source_dir), native(str(mod.path)), "--json"]
    if settings.pack_engine == "full":
        args.append("--full")
    return _run(args, on_event=on_event, stop=stop)


def dry_run(settings: Settings, mod: ModInfo, source_dir: str) -> dict:
    """Что изменилось бы при сборке, без самой сборки.

    Отвечает их программа, а не мы: считать это самостоятельно значило бы
    повторять её инкремент, а он знает и про свои настройки, и про свою
    версию. На большом моде прогон стоит пару секунд, поэтому спрашиваем по
    требованию, а не держим колонку живой.
    """
    if missing(settings) or not Path(source_dir).is_dir():
        return {}
    args = [exe_path(settings), native(source_dir), native(str(mod.path)),
            "--json", "--dry-run"]
    last: dict = {}

    def keep(ev: dict) -> None:
        if ev.get("event") == "done":
            last.clear()
            last.update(ev)

    _run(args, on_event=keep, stop=None)
    return last


def native(path: str | Path) -> str:
    """Путь с родными разделителями.

    Прямые слэши чужим программам не отдаём: движок DayZ на `-config` с ними
    отвечает «файл не найден», и это стоило нам неработающей сборки на чужой
    машине. Привычка дешевле проверки каждого случая.
    """
    return str(Path(path))


def _run(args: list[str], on_event=None, stop=None) -> tuple[bool, str]:
    """Гоняет программу и разбирает её события. Возвращает (успех, текст)."""
    findings: list[dict] = []
    refused = ""
    done: dict = {}
    try:
        proc = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            errors="replace", bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError as e:
        return False, str(e)

    asked_stop = False
    try:
        for line in proc.stdout:            # построчно, не дожидаясь конца
            if stop is not None and not asked_stop and stop.is_set():
                asked_stop = True
                _ask_stop(proc)
            event = _parse(line)
            if event is None:
                continue
            kind = event.get("event")
            if kind == "finding":
                findings.append(event)
            elif kind == "refused":
                refused = str(event.get("text", ""))
            elif kind == "done":
                done = event
            if on_event is not None:
                on_event(event)
        proc.wait(timeout=TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        proc.kill()
        return False, f"Project Builder: превышено время сборки ({TIMEOUT_SEC // 60} минут)"
    finally:
        if proc.stdin and not proc.stdin.closed:
            try:
                proc.stdin.close()
            except OSError:
                pass

    if refused:
        return False, refused
    ok = bool(done.get("ok")) if done else proc.returncode == 0
    if done.get("cancelled"):
        return False, "сборка остановлена"
    return ok, summary(findings, done, ok)


def _ask_stop(proc) -> None:
    """Просит остановиться — строкой в stdin, как договорились."""
    try:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.write("stop\n")
            proc.stdin.flush()
    except OSError:
        pass        # не дошло — останется таймаут и kill, но это крайний путь


def _parse(line: str) -> dict | None:
    """Строка вывода -> событие. Не JSON — не наше дело, молчим.

    Программа обещает печатать в stdout только JSON, но обещание чужое: одна
    строка отладки от чужой библиотеки не должна валить сборку.
    """
    line = line.strip()
    if not line or not line.startswith("{"):
        return None
    try:
        event = json.loads(line)
    except ValueError:
        return None
    return event if isinstance(event, dict) else None


def where(event: dict) -> str:
    """Место находки одной строкой: файл, а при наличии — строка и столбец."""
    place = str(event.get("file") or event.get("path") or "")
    line = event.get("line")
    if line:
        place += f", строка {line}"
        if event.get("col"):
            place += f", столбец {event['col']}"
    elif event.get("where"):
        place += f" ({event['where']})"
    return place


def _text_of(event: dict) -> str:
    """Текст находки без повтора места.

    Ссылочные находки приходят так: where = «CfgVehicles/X.hiddenSelections»,
    а text начинается с него же. Место мы и так показываем отдельно, и вместе
    получалось «(CfgVehicles/X): CfgVehicles/X. Файла … нет» — строка вдвое
    длиннее, и глаз спотыкается ровно там, где должен читать суть.
    """
    text = str(event.get("text", "")).strip()
    place = str(event.get("where") or "")
    if place and text.startswith(place):
        text = text[len(place):].lstrip(" .:")
    return text


def summary(findings: list[dict], done: dict, ok: bool) -> str:
    """Текст для журнала: сперва счёт, потом сами находки.

    Ошибки показываем все: список проблем не должен исчезать за «и ещё 14».
    Предупреждения при удачной сборке не разворачиваем — их бывают десятки, и
    они не мешают pbo появиться.
    """
    errors = [f for f in findings if f.get("level") == "error"]
    warnings = [f for f in findings if f.get("level") == "warning"]
    head = []
    if errors:
        head.append(f"ошибок: {len(errors)}")
    if warnings:
        head.append(f"предупреждений: {len(warnings)}")
    if ok and done.get("packed") is False:
        head.append("изменений нет")
    lines = [", ".join(head)] if head else []
    for f in errors or (warnings if not ok else []):
        lines.append(f"[{f.get('code', '?')}] {where(f)}: {_text_of(f)}")
    if done.get("log"):
        lines.append(f"полный лог: {done['log']}")
    return "\n".join(lines)
