"""Запаковка модов через Mikero pboProject + проверка актуальности по таймштампам."""
from __future__ import annotations

import subprocess
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


def pack_source(settings: Settings, mod: ModInfo, source_dir: str,
                log_cb=None) -> tuple[bool, str]:
    """Собирает один PBO. Возвращает (успех, вывод pboProject)."""
    exe = settings.pbo_project_exe()
    if not Path(exe).is_file():
        return False, f"pboProject не найден: {exe}"

    if settings.clean_meta:
        removed = clean_meta(Path(source_dir))
        if removed and log_cb:
            log_cb(f"Удалено .meta файлов: {removed}")

    args = [exe, str(source_dir)]
    args += settings.pack_flags.split()
    args += [f"-M={mod.path}"]

    if log_cb:
        log_cb(" ".join(args))
    try:
        res = subprocess.run(
            args, capture_output=True, text=True, errors="replace",
            timeout=600, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return False, "pboProject: превышено время сборки (10 минут)"
    except OSError as e:
        return False, str(e)

    output = (res.stdout or "") + (res.stderr or "")
    ok = res.returncode == 0 and pbo_for_source(mod, source_dir).is_file()
    return ok, output.strip()
