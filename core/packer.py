"""Запаковка модов через Mikero pboProject + проверка актуальности по таймштампам.

Свой быстрый упаковщик убран: он собирал pbo с ошибками, и держать два
движка ради этого смысла не было. Режим сборки задаёт FullBuild (+C):
без него pboProject переиспользует temp и собирает инкрементально
(секунды), с ним чистит temp и пересобирает всё (проверено: 3,6 с
против 27,8 с на одном и том же моде).
"""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

from . import keyguard, krbuild
from .mods import ModInfo
from .settings import Settings, split_flags

# Два pboProject одновременно запускать нельзя. Свои настройки он держит в
# реестре, а рабочую папку temp — общую, и в режиме FullBuild чистит её на
# старте. Второй запуск вычищает temp первого прямо посреди его сборки: та
# либо обрывается с невнятной ошибкой, либо повисает до таймаута. Случай не
# выдуманный: запуск сервера пакует устаревшие моды, а со страницы модов в
# это же время жмут «Ребилд». Поэтому — строго по одному, второй ждёт.
_LOCK = threading.Lock()
_WAIT_SEC = 1800     # столько ждём очереди; дальше честно сообщаем, а не висим


def busy() -> bool:
    """Занят ли pboProject прямо сейчас."""
    return _LOCK.locked()


def wait_idle(on_wait=None, timeout: int = _WAIT_SEC) -> bool:
    """Ждёт, пока текущая запаковка закончится. False — не дождались.

    Нужно тем, кто сам не пакует, но зависит от результата: сервер, читающий
    pbo, не должен стартовать посреди чужой сборки — он прочитает файл,
    записанный наполовину, и упадёт на непонятном месте.
    """
    if not _LOCK.acquire(blocking=False):
        if on_wait is not None:
            on_wait()
        if not _LOCK.acquire(timeout=timeout):
            return False
    _LOCK.release()
    return True


# Служебные файлы, которые не считаются "изменением сорсов"
_IGNORE_SUFFIXES = {".meta", ".txa", ".bak", ".tmp"}


def _newest_mtime(directory: Path, newer_than: float | None = None) -> float:
    """Самый свежий mtime файла в папке рекурсивно (0 — папка пуста/недоступна).

    scandir, а не rglob: DirEntry несёт stat прямо из обхода каталога, и
    отдельный системный вызов на каждый файл не нужен. На 10 тысячах файлов
    сорсов это 34 мс вместо 395.

    newer_than — порог для раннего выхода: если спрашивают «есть ли что-то
    новее», незачем дообходить остаток, ответ уже известен. Возвращённое
    значение в этом случае не «самый свежий», а «первый найденный новее», чего
    для проверки устаревания достаточно.
    """
    newest = 0.0
    stack = [str(directory)]
    while stack:
        try:
            entries = os.scandir(stack.pop())
        except OSError:
            continue
        with entries:
            for e in entries:
                try:
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                        continue
                    if os.path.splitext(e.name)[1].lower() in _IGNORE_SUFFIXES:
                        continue
                    mt = e.stat().st_mtime
                except OSError:
                    continue
                if mt > newest:
                    newest = mt
                    if newer_than is not None and mt > newer_than:
                        return newest
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
        if not pbo.is_file():
            out.append(src)
            continue
        pbo_mtime = pbo.stat().st_mtime
        if _newest_mtime(spath, newer_than=pbo_mtime) > pbo_mtime:
            out.append(src)
    return out


def stale_mods(mods: list[ModInfo],
               force: bool = False) -> list[tuple[ModInfo, list[str]]]:
    """Локальные моды с сорсами, требующие перепаковки.

    force — собрать все, а не только изменившиеся. Нужно, когда изменилось не
    содержимое сорсов, а условия сборки: настройки pboProject, версия
    инструментов, содержимое чужого мода-зависимости. Сравнение дат про такое
    ничего не знает и честно говорит «всё свежее».
    """
    out = []
    for mod in mods:
        if not mod.can_have_sources or not mod.sources:
            continue
        stale = [s for s in mod.sources if Path(s).is_dir()] if force else stale_sources(mod)
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


def pack_source(settings: Settings, mod: ModInfo, source_dir: str,
                on_wait=None) -> tuple[bool, str]:
    """Собирает один PBO. Возвращает (успех, текст для диагностики).

    ВАЖНО: stdout/stderr pboProject перенаправлять нельзя — ни в pipe, ни даже
    в DEVNULL. При любом перенаправлении он перестаёт применять префикс из
    $PBOPREFIX$, и pbo собирается вообще без префикса. Проверено перебором:
    8 прогонов из 8 с перехватом дают prefix=none, без перехвата — верный
    префикс, причём cwd и CREATE_NO_WINDOW на это не влияют.

    Перехват всё равно был бесполезен: в stdout pboProject не пишет ничего
    (это GUI-приложение), а вся диагностика идёт в свой лог — его и читаем.

    on_wait зовётся один раз, если пришлось встать в очередь за другой
    запаковкой: молчаливое ожидание неотличимо от зависания.
    """
    exe = settings.pbo_project_exe()
    if not Path(exe).is_file():
        return False, f"pboProject не найден: {exe}"
    # проверяем и сорсы: иначе опечатка в пути выглядит как невнятный сбой
    # самого тула, а не как понятная ошибка
    if not Path(source_dir).is_dir():
        return False, f"папка сорсов не найдена: {source_dir}"

    # Дальше начинается сама сборка — с этого места и до конца работает
    # ровно один pboProject, см. _LOCK.
    if not _LOCK.acquire(blocking=False):
        if on_wait is not None:
            on_wait()
        if not _LOCK.acquire(timeout=_WAIT_SEC):
            return False, ("другая запаковка не завершилась за "
                           f"{_WAIT_SEC // 60} минут — сборка отменена")
    try:
        return _pack_locked(settings, mod, source_dir)
    finally:
        _LOCK.release()


# Следы обфускатора, лежащие прямо в папках сорсов, рядом с config.cpp:
# .6w_pack / .6w_obf — его конфиг (защищаемые имена, пути, настройки), а
# <мод>_OBFCACHE/obfuscated_entities.json — карта «настоящее имя →
# обфусцированное», то есть обфускация, приложенная к себе же в расшифрованном
# виде. Первый уже уехал в боевой pbo открытым текстом.
#
# Эти маски дописываются к списку -X всегда, даже если в настройках их нет:
# список исключений правится руками и в диалоге, забыть строчку можно один
# раз, а выложенный pbo назад не вернёшь.
_MUST_EXCLUDE = (".6w_pack", ".6w_obf", ".6w*",
                 "obfuscated_entities.json", "*OBFCACHE*",
                 "hobf_pack.settings.json")


def _with_sign_key(flags: list[str], settings: Settings) -> list[str]:
    """Ставит ключ подписи из настроек, выкидывая всё, что сказано во флагах.

    Ключ — общая настройка: он один на проект, а движков два. Пока он жил
    внутри строки флагов, у подписи было две двери — поле в окне флагов и
    сама строка, — и они расходились. Теперь источник один, а строка флагов
    про подпись больше ничего не решает.
    """
    out = [f for f in flags
           if (f[1:3] if f[:1] in "+-" else f[:2]).upper() != "K="
           and f not in ("+K", "-K")]
    key = (getattr(settings, "sign_key", "") or "").strip()
    out.append(f"+K={key}" if key else "-K")
    return out


def _with_must_exclude(flags: list[str]) -> list[str]:
    """Дописывает обязательные маски в -X=; ключа нет — добавляет его.

    Знак у ключа pboProject не различает (+X и -X для списков равнозначны),
    поэтому ищем по «X=», а не по флагу целиком.
    """
    out: list[str] = []
    found = False
    for f in flags:
        key = f[1:3] if f[:1] in "+-" else f[:2]
        if key.upper() == "X=" and "=" in f:
            found = True
            head, _, value = f.partition("=")
            masks = [m for m in value.split(",") if m]
            masks += [m for m in _MUST_EXCLUDE if m not in masks]
            f = head + "=" + ",".join(masks)
        out.append(f)
    if not found:
        out.append("-X=" + ",".join(_MUST_EXCLUDE))
    return out


def _pack_locked(settings: Settings, mod: ModInfo, source_dir: str) -> tuple[bool, str]:
    """Сама сборка. Зовётся только под _LOCK — см. комментарий у него."""
    exe = settings.pbo_project_exe()
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
    # Свой разбор, а не shlex: в posix-режиме он съедает обратные слэши и путь
    # к ключу подписи приходил к pboProject без разделителей. См. split_flags.
    flags = split_flags(settings.pack_flags)
    # Режим сборки задаёт FullBuild (C), а не строка флагов: пользователь
    # выбирает его на главной странице, и выбор должен побеждать.
    flags = [f for f in flags if f not in ("+C", "-C")]
    flags.append("+C" if settings.pack_engine == "full" else "-C")
    flags = _with_must_exclude(_with_sign_key(flags, settings))
    args += flags
    # Движок задаём явно по той же причине, что и +R: иначе берётся то, что
    # осталось в реестре от прошлой GUI-сессии (могло быть Arma3/OFP).
    args += ["-E=dayz", f"-M={native(mod.path)}"]

    # pboProject в конце сборки жмёт Enter через keybd_event, и нажатие уходит
    # в чужое окно — недописанное сообщение отправляется само. См. keyguard.
    keyguard.arm()
    try:
        # без capture_output/DEVNULL — см. предупреждение в докстроке
        res = subprocess.run(args, timeout=600,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return False, ("pboProject: превышено время сборки (10 минут)\n"
                       + _pboproject_log(source_dir))
    except OSError as e:
        return False, str(e)
    finally:
        keyguard.disarm()

    out = pbo_for_source(mod, source_dir)
    ok = res.returncode == 0 and out.is_file()
    if not ok:
        return False, _pboproject_log(source_dir)
    inside = forbidden_entries(out)
    if inside:
        # Файл обфускатора внутри pbo. Проверяется по таблице имён, то есть
        # ловится и тогда, когда содержимое сжато и строк в нём не видно.
        return False, ("В готовый PBO попали файлы обфускатора: "
                       + ", ".join(inside)
                       + ".\nПроверьте список исключений в настройках "
                         "pboProject и соберите заново.")
    leaked = leaked_secrets(out)
    if leaked:
        # Не предупреждение: pbo с настройками обфускации — это утечка, и
        # уехать дальше она не должна. Файл оставляем на месте, чтобы было
        # что осмотреть.
        return False, ("В готовом PBO найдены служебные строки обфускатора: "
                       + ", ".join(leaked)
                       + ".\nУберите из папки сорсов следы обфускатора "
                         "(.6w_pack, .6w_obf, папки *_OBFCACHE) и соберите "
                         "заново.")
    return True, ""


# Приметы обфускатора: в собранном моде их быть не может, а в его конфиге
# (.6w_pack, .6w_obf) и кэше переименований они есть всегда.
_SECRETS = (b"identifiers_to_pack", b"default_identifier",
            b"obfuscated_definitions")


# Имена файлов внутри pbo, которых там быть не должно: конфиг обфускатора и
# кэш переименований. Сверяется с таблицей файлов, а не с содержимым, поэтому
# работает и когда pbo сжат.
_FORBIDDEN_NAMES = (".6w_pack", ".6w_obf", "obfuscated_entities.json",
                    "hobf_pack.settings.json")


def pbo_entries(pbo: Path, limit: int = 1 << 20) -> list[str]:
    """Имена файлов внутри pbo. Пусто — заголовок прочитать не удалось.

    Таблица файлов лежит в начале pbo открытым текстом независимо от сжатия и
    обфускации содержимого: имя с нулём на конце, за ним пять uint32. Список
    кончается пустым именем. Читаем только заголовок — с запасом, но не весь
    файл: pbo бывает в сотни мегабайт.
    """
    import struct
    try:
        with open(pbo, "rb") as f:
            head = f.read(limit)
    except OSError:
        return []
    names: list[str] = []
    done = False
    pos = 0
    while pos < len(head):
        end = head.find(b"\0", pos)
        if end < 0 or end + 21 > len(head):
            break
        raw = head[pos:end]
        pos = end + 1
        try:
            method = struct.unpack_from("<I", head, pos)[0]
        except struct.error:
            break
        pos += 20               # пять uint32: метод и четыре размера/времени
        if not raw:
            if method == 0x56657273:    # «Vers» — служебная запись со свойствами
                while pos < len(head):
                    end = head.find(b"\0", pos)
                    if end < 0:
                        return names
                    key = head[pos:end]
                    pos = end + 1
                    if not key:         # пустой ключ — конец свойств
                        break
                continue
            done = True         # пустое имя без «Vers» — конец таблицы файлов
            break
        names.append(raw.decode("cp1251", "replace"))
    if not done and limit < (16 << 20):
        # Таблица не кончилась — значит заголовок длиннее прочитанного куска.
        # Молча отдать половину списка нельзя: по нему решают, чисто ли в pbo.
        return pbo_entries(pbo, limit * 8)
    return names


def forbidden_entries(pbo: Path) -> list[str]:
    """Файлы обфускатора, попавшие в pbo. Пусто — чисто."""
    bad: list[str] = []
    for name in pbo_entries(pbo):
        leaf = name.replace("/", "\\").rsplit("\\", 1)[-1].lower()
        if leaf in _FORBIDDEN_NAMES and name not in bad:
            bad.append(name)
    return bad


def leaked_secrets(pbo: Path) -> list[str]:
    """Служебные строки, найденные в готовом PBO. Пусто — чисто.

    Читаем кусками: pbo бывает в сотни мегабайт, и держать его в памяти ради
    двух подстрок незачем. Куски перекрываем, иначе строка, попавшая на стык,
    не нашлась бы.

    Содержимое в pbo обычно сжато, и тогда строк тут не видно — это нижняя
    граница проверки, а не вся она: имена файлов смотрит forbidden_entries,
    им сжатие не мешает.
    """
    found: list[str] = []
    tail = b""
    try:
        with open(pbo, "rb") as f:
            while chunk := f.read(1 << 20):
                blob = tail + chunk
                for needle in _SECRETS:
                    name = needle.decode()
                    if needle in blob and name not in found:
                        found.append(name)
                if len(found) == len(_SECRETS):
                    break
                tail = blob[-32:]
    except OSError:
        return []       # не прочитали — не выдумываем находок
    return found


def pack_source_auto(settings: Settings, mod: ModInfo, source_dir: str,
                     on_wait=None, on_event=None, stop=None) -> tuple[bool, str]:
    """Собирает PBO тем движком, который выбран в настройках.

    Движков два: Mikero pboProject (по умолчанию) и [KR] Project Builder —
    программа из KR DevToolkit, которую мы зовём как exe. Режим сборки
    (обычная или полная) задаёт settings.pack_engine и понимают оба.

    Очередь общая: у обоих своя папка temp и свой инкремент, но запускать
    две сборки разом всё равно нельзя — вторая будет мешать первой.
    """
    if (getattr(settings, "pack_tool", "pboproject") or "pboproject") != "krbuild":
        return pack_source(settings, mod, source_dir, on_wait=on_wait)

    why = krbuild.missing(settings)
    if why:
        return False, f"Project Builder: {why}"
    if not _LOCK.acquire(blocking=False):
        if on_wait is not None:
            on_wait()
        if not _LOCK.acquire(timeout=_WAIT_SEC):
            return False, ("другая запаковка не завершилась за "
                           f"{_WAIT_SEC // 60} минут — сборка отменена")
    try:
        ok, text = krbuild.pack(settings, mod, source_dir,
                                on_event=on_event, stop=stop)
    finally:
        _LOCK.release()
    if not ok:
        return ok, text
    # Проверку следов обфускатора оставляем и здесь, но только дешёвую — по
    # таблице имён в заголовке pbo (0,06 мс). Обфускации у Project Builder
    # есть её конфигу взяться неоткуда; но список исключений там свой, и
    # ошибиться в нём можно так же, как в чужом. Побайтовый поиск строк для
    # этого движка не зовём: читать сотни мегабайт ради невозможного случая
    # незачем.
    inside = forbidden_entries(pbo_for_source(mod, source_dir))
    if inside:
        return False, ("В готовый PBO попали файлы обфускатора: "
                       + ", ".join(inside)
                       + ".\nПроверьте список исключений в настройках Project Builder.")
    return True, text
