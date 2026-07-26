"""Запаковка модов через Mikero pboProject + проверка актуальности по таймштампам."""
from __future__ import annotations

import shlex
import subprocess
import threading
from pathlib import Path

from .mods import ModInfo
from .settings import Settings

# Служебные файлы, которые не считаются "изменением сорсов"
_IGNORE_SUFFIXES = {".meta", ".txa", ".bak", ".tmp"}


def _newest_mtime(directory: Path) -> float:
    """Самый свежий mtime файла в папке рекурсивно (0 — папка пуста/недоступна)."""
    newest = 0.0
    try:
        for f in directory.rglob("*"):
            if f.is_file() and f.suffix.lower() not in _IGNORE_SUFFIXES:
                try:
                    mt = f.stat().st_mtime
                    if mt > newest:
                        newest = mt
                except OSError:
                    continue
    except OSError:
        pass
    return newest


def pbo_for_source(mod: ModInfo, source_dir: str) -> Path:
    """PBO, который pboProject собирает из этой папки сорсов: addons/<имя_папки>.pbo."""
    return Path(mod.path) / "addons" / (Path(source_dir).name + ".pbo")


def stale_sources(mod: ModInfo) -> list[str]:
    """Папки сорсов, которые новее своих PBO (или PBO ещё нет)."""
    out = []
    for src in mod.sources:
        spath = Path(src)
        if not spath.is_dir():
            continue
        pbo = pbo_for_source(mod, src)
        if not pbo.is_file() or _newest_mtime(spath) > pbo.stat().st_mtime:
            out.append(src)
    return out


def stale_mods(mods: list[ModInfo]) -> list[tuple[ModInfo, list[str]]]:
    """Локальные моды с сорсами, требующие перепаковки."""
    out = []
    for mod in mods:
        if mod.source != "local" or not mod.sources:
            continue
        stale = stale_sources(mod)
        if stale:
            out.append((mod, stale))
    return out


def clean_meta(source_dir: Path) -> int:
    """Удаляет *.meta в сорсах (мусор от Workbench). Возвращает число удалённых."""
    n = 0
    try:
        for f in source_dir.rglob("*.meta"):
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
    except OSError:
        pass
    return n


def pack_source(settings: Settings, mod: ModInfo, source_dir: str) -> tuple[bool, str]:
    """Собирает один PBO. Возвращает (успех, вывод pboProject).

    Вывод самого pboProject в лог не транслируется построчно — он либо пуст,
    либо состоит из служебного шума pboProject; вызывающий код показывает
    только краткий статус по каждому сорсу (см. ui/mods_panel.py, core/launcher.py),
    а этот полный текст — только при ошибке, для диагностики.
    """
    exe = settings.pbo_project_exe()
    if not Path(exe).is_file():
        return False, f"pboProject не найден: {exe}"

    if settings.clean_meta:
        clean_meta(Path(source_dir))

    args = [exe, str(source_dir)]
    # shlex (posix=True) — значения в кавычках с пробелами (пути, списки масок
    # исключений) остаются одним аргументом, а не рвутся построчным .split()
    try:
        args += shlex.split(settings.pack_flags, posix=True)
    except ValueError:
        args += settings.pack_flags.split()  # незакрытая кавычка и т.п.
    # движок задаём явно: иначе используется то, что осталось в реестре
    # с прошлой GUI-сессии pboProject (могло быть Arma3/OFP от другого проекта)
    args += ["-E=dayz", f"-M={mod.path}"]

    try:
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError as e:
        return False, str(e)

    # построчное чтение (не capture_output после завершения) — нужно, чтобы
    # сторожевой таймер мог убить зависший процесс, не дожидаясь общего wait()
    lines: list[str] = []
    timed_out = False

    def _kill_on_timeout() -> None:
        nonlocal timed_out
        timed_out = True
        proc.kill()

    watchdog = threading.Timer(600, _kill_on_timeout)
    watchdog.start()
    try:
        for line in iter(proc.stdout.readline, ""):
            lines.append(line.rstrip("\n"))
        returncode = proc.wait()
    finally:
        watchdog.cancel()
        proc.stdout.close()

    output = "\n".join(lines)
    if timed_out:
        return False, "pboProject: превышено время сборки (10 минут)\n" + output[-2000:]
    ok = returncode == 0 and pbo_for_source(mod, source_dir).is_file()
    return ok, output.strip()


def pack_source_fast(settings: Settings, mod: ModInfo, source_dir: str) -> tuple[bool, str]:
    """Быстрая запаковка через входящий в комплект pbo_packer.exe.

    Не подписывает pbo и не делает проверок ошибок pboProject — только для
    локальной отладки (verifySignatures=0). Возвращает (успех, вывод)."""
    exe = settings.pbo_packer_exe()
    if not Path(exe).is_file():
        return False, f"pbo_packer не найден: {exe}"

    if settings.clean_meta:
        clean_meta(Path(source_dir))

    output = pbo_for_source(mod, source_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    args = [exe, "pack", "-s", str(source_dir), "-o", str(output)]

    try:
        res = subprocess.run(
            args, capture_output=True, text=True, errors="replace",
            timeout=120, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return False, "pbo_packer: превышено время сборки (2 минуты)"
    except OSError as e:
        return False, str(e)

    out = ((res.stdout or "") + (res.stderr or "")).strip()
    ok = res.returncode == 0 and output.is_file()
    return ok, out


def pack_source_auto(settings: Settings, mod: ModInfo, source_dir: str) -> tuple[bool, str]:
    """Выбирает движок запаковки по settings.pack_engine ('fast' | 'full')."""
    if settings.pack_engine == "fast":
        return pack_source_fast(settings, mod, source_dir)
    return pack_source(settings, mod, source_dir)
