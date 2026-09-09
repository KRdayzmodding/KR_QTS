"""Актуальность воркшоп-модов перед запуском.

Сервер, поднятый со старым модом, ведёт себя необъяснимо: скрипты не те,
конфиги не те, а в логах ничего про это не сказано. Ещё хуже мод, который
Steam качает прямо сейчас: файлы выкладываются по мере скачивания, и запуск
подхватывает половину.

Поэтому перед запуском состояние проверяется всегда, а привести моды в порядок
можно двумя способами:

* **подождать Steam** — он обновляет подписки сам, мы только опрашиваем его
  состояние и не даём стартовать раньше времени. Ничего ставить не нужно, но и
  поторопить Steam мы не можем;
* **скачать через SteamCMD** — принудительно и сейчас. Требует установленного
  SteamCMD и учётной записи, которая владеет игрой: анонимный вход к воркшопу
  DayZ доступа не даёт.

Пароль нигде не хранится. SteamCMD запоминает вход сам после первого ручного
запуска, и от нас ему нужно только имя учётной записи.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import steam_state
from .i18n import tr
from .mods import ModInfo, SOURCE_STEAM
from .steam_urls import APP_DAYZ

# Способы приведения модов в актуальное состояние.
WAIT = "wait"
STEAMCMD = "steamcmd"

# Почему мод не годится для запуска.
OUTDATED = "outdated"          # в мастерской версия новее
DOWNLOADING = "downloading"    # качается прямо сейчас, файлы неполные

POLL_SEC = 5.0                 # как часто спрашиваем Steam о его состоянии
STEAMCMD_TIMEOUT = 3600        # потолок на одну загрузку, секунды


@dataclass
class Stale:
    """Мод, с которым запускаться нельзя."""

    mod: ModInfo
    reason: str

    def text(self) -> str:
        if self.reason == DOWNLOADING:
            return tr("upd.mod_downloading", "{m}: качается Steam'ом", m=self.mod.name)
        return tr("upd.mod_outdated", "{m}: в мастерской версия новее", m=self.mod.name)


def steam_mods(mods: list[ModInfo]) -> list[ModInfo]:
    """Только воркшопные: у локальных и скачанных с GitHub версии нет."""
    return [m for m in mods if m.source == SOURCE_STEAM and m.workshop_id]


def stale(mods: list[ModInfo], appid: str = APP_DAYZ) -> list[Stale]:
    """Какие моды Steam считает устаревшими или недокачанными.

    Спрашиваем состояние самого Steam, а не мастерскую по сети: он знает
    точно, работает мгновенно и не зависит от того, есть ли интернет. Сеть
    нужна только чтобы узнать про обновление, о котором Steam ещё не в курсе, —
    это отдельная проверка на экране модов.
    """
    wanted = steam_mods(mods)
    if not wanted:
        return []
    ws = steam_state.workshop_state(appid)
    out: list[Stale] = []
    for mod in wanted:
        if mod.workshop_id in ws.downloading:
            out.append(Stale(mod, DOWNLOADING))
        elif mod.workshop_id in ws.outdated:
            out.append(Stale(mod, OUTDATED))
    return out


# ------------------------------------------------------------------ ожидание


def wait_for_steam(mods: list[ModInfo], on_wait=None, stop=None,
                   timeout: float = 1800, appid: str = APP_DAYZ) -> tuple[bool, str]:
    """Ждёт, пока Steam сам приведёт моды в порядок.

    Поторопить его нечем: команды «обнови вот этот предмет мастерской» у
    steam:// не существует. Поэтому просто не пускаем запуск вперёд и говорим,
    чего ждём, — молчаливое ожидание неотличимо от зависания.

    Возвращает (готово, причина отказа).
    """
    deadline = time.monotonic() + max(1.0, timeout)
    said = False
    while True:
        left = stale(mods, appid)
        if not left:
            return True, ""
        if stop is not None and stop():
            return False, tr("upd.cancelled", "Обновление модов отменено.")
        if not said and on_wait is not None:
            on_wait(left)
            said = True
        if time.monotonic() >= deadline:
            names = ", ".join(s.mod.name for s in left)
            return False, tr(
                "upd.wait_timeout",
                "Steam не обновил моды за отведённое время: {mods}. "
                "Откройте загрузки Steam и дождитесь их окончания.", mods=names)
        time.sleep(POLL_SEC)


# ------------------------------------------------------------------ SteamCMD


def content_dir(steamcmd_exe: str, appid: str = APP_DAYZ) -> Path:
    """Куда SteamCMD складывает скачанное. Рядом с собой, а не в библиотеку."""
    return Path(steamcmd_exe).parent / "steamapps" / "workshop" / "content" / appid


def build_command(steamcmd_exe: str, login: str, ids: list[str],
                  appid: str = APP_DAYZ) -> list[str]:
    """Команда SteamCMD на пачку модов.

    Пачкой, а не по одному: каждый запуск SteamCMD — это вход в Steam заново,
    десяток секунд на мод впустую.
    """
    args = [steamcmd_exe, "+login", login or "anonymous"]
    for item in ids:
        args += ["+workshop_download_item", appid, item]
    return args + ["+quit"]


def download(steamcmd_exe: str, login: str, mods: list[ModInfo],
             on_line=None, stop=None, appid: str = APP_DAYZ,
             timeout: int = STEAMCMD_TIMEOUT) -> tuple[bool, str]:
    """Скачивает моды через SteamCMD и кладёт файлы туда, откуда их берёт запуск.

    SteamCMD складывает всё в свою папку, а не в библиотеку Steam, поэтому
    после загрузки содержимое переносится в папку мода — ту самую, на которую
    запуск делает ссылку. Иначе скачали бы вхолостую.
    """
    exe = Path(steamcmd_exe)
    if not exe.is_file():
        return False, tr("upd.no_steamcmd", "SteamCMD не найден: {p}", p=steamcmd_exe)

    ids = [m.workshop_id for m in mods]
    if not ids:
        return True, ""

    try:
        proc = subprocess.Popen(
            build_command(str(exe), login, ids, appid),
            cwd=str(exe.parent), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:
        return False, str(e)

    deadline = time.monotonic() + timeout
    failed: list[str] = []
    try:
        for line in proc.stdout or ():
            line = line.rstrip()
            if line and on_line is not None:
                on_line(line)
            # SteamCMD не возвращает осмысленный код выхода на отказ по
            # отдельному предмету — приходится читать его вывод.
            if "ERROR!" in line or "Failure" in line:
                failed.append(line)
            if stop is not None and stop():
                proc.kill()
                return False, tr("upd.cancelled", "Обновление модов отменено.")
            if time.monotonic() > deadline:
                proc.kill()
                return False, tr("upd.cmd_timeout",
                                 "SteamCMD не уложился в отведённое время.")
    finally:
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()

    if failed:
        return False, "\n".join(failed[-5:])

    src_root = content_dir(str(exe), appid)
    for mod in mods:
        src = src_root / mod.workshop_id
        if not src.is_dir():
            return False, tr("upd.not_downloaded",
                             "SteamCMD не скачал {m}: нет папки {p}",
                             m=mod.name, p=str(src))
        ok, err = replace_contents(src, Path(mod.path))
        if not ok:
            return False, err
    return True, ""


def replace_contents(src: Path, dst: Path) -> tuple[bool, str]:
    """Переносит содержимое скачанного мода в его рабочую папку.

    Копируем поверх, а не сносим папку целиком: на неё может стоять ссылка из
    корня игры, и удаление оборвало бы её. По той же причине не трогаем саму
    папку — только то, что внутри.
    """
    try:
        dst.mkdir(parents=True, exist_ok=True)
        for item in dst.iterdir():
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
        for item in src.iterdir():
            target = dst / item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
    except OSError as e:
        return False, tr("upd.copy_failed", "Не удалось обновить папку мода {p}: {e}",
                         p=str(dst), e=str(e))
    return True, ""


# ------------------------------------------------------------------- общий вход


def bring_up_to_date(mods: list[ModInfo], settings, on_wait=None, on_line=None,
                     stop=None, appid: str = APP_DAYZ) -> tuple[bool, str]:
    """Приводит моды запуска в актуальное состояние выбранным способом.

    Возвращает (можно запускать, причина отказа). Пустой список устаревших —
    сразу «да»: ни ожидания, ни SteamCMD в обычном запуске не будет.
    """
    left = stale(mods, appid)
    if not left:
        return True, ""

    if on_wait is not None:
        on_wait(left)

    method = getattr(settings, "mod_update_method", WAIT)
    timeout = max(1, int(getattr(settings, "mod_update_timeout_min", 30))) * 60

    if method == STEAMCMD:
        exe = getattr(settings, "steamcmd_exe", "")
        login = getattr(settings, "steam_login", "")
        # Недокачанное Steam'ом трогать через SteamCMD нельзя: два клиента
        # пишут в одну папку. Сначала дожидаемся, пока он закончит, и только
        # потом качаем то, что осталось устаревшим.
        busy = [s.mod for s in left if s.reason == DOWNLOADING]
        if busy:
            ok, err = wait_for_steam(busy, stop=stop, timeout=timeout, appid=appid)
            if not ok:
                return False, err
        rest = [s.mod for s in stale(mods, appid)]
        if not rest:
            return True, ""
        return download(exe, login, rest, on_line=on_line, stop=stop, appid=appid)

    return wait_for_steam([s.mod for s in left], stop=stop, timeout=timeout,
                          appid=appid)
