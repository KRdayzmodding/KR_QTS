"""Запаковка модов через Mikero pboProject + проверка актуальности по таймштампам.

Свой быстрый упаковщик убран: он собирал pbo с ошибками, и держать два
движка ради этого смысла не было. Режим сборки задаёт FullBuild (+C):
без него pboProject переиспользует temp и собирает инкрементально
(секунды), с ним чистит temp и пересобирает всё (проверено: 3,6 с
против 27,8 с на одном и том же моде).
"""
from __future__ import annotations

import shlex
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


def native(path: str | Path) -> str:
    """Путь в родной для Windows форме, с обратными слэшами.

    Пути сорсов хранятся так, как их когда-то выбрали, и нередко приходят с
    прямыми слэшами (P:/KR/...). Для pboProject это существенно: у него свой
    разбор командной строки, а префикс он вычисляет от корня диска P:.
    str() от строки ничего не нормализует — нужен явный проход через Path.
    """
    return str(Path(path))


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


def _pboproject_temp() -> Path:
    """Папка, куда pboProject кладёт свои логи сборки.

    Настройка лежит в реестре относительно рабочего диска (обычно P:\\temp).
    """
    drive, temp = "P:\\", "temp"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Mikero\pboProject\Settings") as k:
            try:
                drive = winreg.QueryValueEx(k, "prj_Pdrive")[0] or drive
            except OSError:
                pass
            try:
                temp = winreg.QueryValueEx(k, "drive_temp_folder")[0] or temp
            except OSError:
                pass
    except (ImportError, OSError):
        pass
    p = Path(temp)
    return p if p.is_absolute() else Path(drive) / temp


def _pboproject_log(source_dir: str) -> str:
    """Хвост лога сборки — единственная внятная диагностика pboProject."""
    log = _pboproject_temp() / f"{Path(source_dir).name}.packing.log"
    try:
        return log.read_text(encoding="utf-8", errors="replace")[-4000:].strip()
    except OSError:
        return ""


def pack_source(settings: Settings, mod: ModInfo, source_dir: str) -> tuple[bool, str]:
    """Собирает один PBO. Возвращает (успех, текст для диагностики).

    ВАЖНО: stdout/stderr pboProject перенаправлять нельзя — ни в pipe, ни даже
    в DEVNULL. При любом перенаправлении он перестаёт применять префикс из
    $PBOPREFIX$, и pbo собирается вообще без префикса. Проверено перебором:
    8 прогонов из 8 с перехватом дают prefix=none, без перехвата — верный
    префикс, причём cwd и CREATE_NO_WINDOW на это не влияют.

    Перехват всё равно был бесполезен: в stdout pboProject не пишет ничего
    (это GUI-приложение), а вся диагностика идёт в свой лог — его и читаем.
    """
    exe = settings.pbo_project_exe()
    if not Path(exe).is_file():
        return False, f"pboProject не найден: {exe}"
    # проверяем и сорсы: иначе опечатка в пути выглядит как невнятный сбой
    # самого тула, а не как понятная ошибка
    if not Path(source_dir).is_dir():
        return False, f"папка сорсов не найдена: {source_dir}"

    if settings.clean_meta:
        clean_meta(Path(source_dir))

    # +R — не пользовательская настройка, а обязательное условие: все опции
    # CLI pboProject пишет в реестр, то есть каждый запуск молча переписывает
    # настройки его GUI. С +R они восстанавливаются после сессии. Без этого
    # «в GUI всё настроено правильно» перестаёт быть правдой после первой же
    # сборки, и любая диагностика сравнивает состояние, испорченное ею самой.
    #
    # Ставится сразу за путём к сорсам, до пользовательских флагов: у Mikero
    # свой разбор командной строки, и порядок опций для него значим.
    args = [exe, native(source_dir), "+R"]
    # shlex (posix=True) — значения в кавычках с пробелами (пути, списки масок
    # исключений) остаются одним аргументом, а не рвутся построчным .split()
    try:
        flags = shlex.split(settings.pack_flags, posix=True)
    except ValueError:
        flags = settings.pack_flags.split()  # незакрытая кавычка и т.п.
    # Режим сборки задаёт FullBuild (C), а не строка флагов: пользователь
    # выбирает его на главной странице, и выбор должен побеждать.
    flags = [f for f in flags if f not in ("+C", "-C")]
    flags.append("+C" if settings.pack_engine == "full" else "-C")
    args += flags
    # Движок задаём явно по той же причине, что и +R: иначе берётся то, что
    # осталось в реестре от прошлой GUI-сессии (могло быть Arma3/OFP).
    args += ["-E=dayz", f"-M={native(mod.path)}"]

    try:
        # без capture_output/DEVNULL — см. предупреждение в докстроке
        res = subprocess.run(args, timeout=600,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return False, ("pboProject: превышено время сборки (10 минут)\n"
                       + _pboproject_log(source_dir))
    except OSError as e:
        return False, str(e)

    ok = res.returncode == 0 and pbo_for_source(mod, source_dir).is_file()
    return ok, "" if ok else _pboproject_log(source_dir)


def pack_source_auto(settings: Settings, mod: ModInfo, source_dir: str) -> tuple[bool, str]:
    """Единственный движок — pboProject; режим задаёт settings.pack_engine."""
    return pack_source(settings, mod, source_dir)
