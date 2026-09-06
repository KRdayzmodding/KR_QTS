"""qtsctl — внешнее управление KR QTS из командной строки.

Отдельный вход, а не ключ основной программы: собранная версия оконная, у неё
нет stdout и быть не должно — консоль прячется первой строкой main(), иначе
консольные помощники pboProject заводят себе окна. А задача в редакторе — это
командная строка с выводом в панель, и без потока вывода она бессмысленна.

Справка работает всегда: она живёт здесь и в канал не лезет. Знакомство с
инструментом не должно начинаться с ошибки «программа не запущена».
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import clihelp, cliargs, clipipe, cliproto
from core.cliargs import CliError
from core.settings import Settings
from core import i18n

# Запас поверх запрошенного ожидания: ответ идёт по каналу уже после того, как
# движок сдался сам, и обрывать его на полуслове — значит потерять отчёт.
SLACK_SEC = 60.0
DEFAULT_TIMEOUT = 900.0


def _out(text: str) -> None:
    """Печать без падения на кодировке консоли.

    Windows-консоль под русской локалью — cp866, и «—» в ней нет. Ронять
    инструмент из-за тире недопустимо: он мог только что поднять сервер.
    """
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    sys.stdout.write(text.encode(enc, "replace").decode(enc, "replace") + "\n")


def _app_command() -> list[str]:
    """Чем поднимать QTS: собранный exe рядом или исходники."""
    here = Path(__file__).resolve().parent
    exe = here / "KR_QTS.exe"
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve().parent / "KR_QTS.exe"
    if exe.is_file():
        return [str(exe)]
    return [sys.executable, str(here / "main.py")]


def _start_engine() -> bool:
    """Поднимает QTS и ждёт, пока он откроет канал.

    Окно при этом не показывается — программа уходит в трей, как по ярлыку
    быстрого запуска: инструмент просил запустить сервер, а не лезть на экран.
    """
    try:
        subprocess.Popen(_app_command() + ["--quiet"],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        return False
    return True


def _payload(req: cliargs.Request) -> dict:
    body = {"args": cliproto.plain(req.overlay)}
    if req.wait is not None:
        body["wait"] = req.wait
    if req.timeout is not None:
        body["timeout"] = req.timeout
    if req.detach:
        body["detach"] = True
    return body


def _timeout(req: cliargs.Request) -> float:
    if req.timeout is not None:
        return req.timeout + SLACK_SEC
    if req.wait is not None:
        return req.wait + SLACK_SEC
    return DEFAULT_TIMEOUT


def _talk(req: cliargs.Request) -> dict:
    """Один разговор с движком. Возвращает разобранный ответ."""
    line = cliproto.request(req.command, _payload(req))
    want_start = req.overlay.start
    try:
        return cliproto.decode(clipipe.send(line, timeout=_timeout(req)))
    except clipipe.EngineDown:
        pass
    if not want_start:
        return cliproto.decode(cliproto.fail(
            1, cliproto.E_INTERNAL,
            i18n.tr("cli.no_engine", "KR QTS не запущен."),
            i18n.tr("cli.no_engine_hint",
                    "Запусти программу или добавь +start, чтобы поднять её "
                    "молча, без окна."),
            cliproto.EXIT_NO_ENGINE))
    if not _start_engine():
        return cliproto.decode(cliproto.fail(
            1, cliproto.E_INTERNAL,
            i18n.tr("cli.start_failed", "Не удалось запустить KR QTS."),
            "", cliproto.EXIT_NO_ENGINE))
    try:
        # Канал открывается не мгновенно: процесс уже живёт, а сервер канала
        # поднимается после чтения настроек. Отсюда повторы, а не одна попытка.
        return cliproto.decode(clipipe.send(line, tries=40, pause=0.5,
                                            timeout=_timeout(req)))
    except clipipe.EngineDown as e:
        return cliproto.decode(cliproto.fail(
            1, cliproto.E_INTERNAL,
            i18n.tr("cli.no_answer", "KR QTS запущен, но не отвечает: {e}").format(e=e),
            "", cliproto.EXIT_NO_ENGINE))


def main(argv: list[str]) -> int:
    try:
        i18n.load(Settings.load().language)
    except Exception:                                   # noqa: BLE001
        i18n.load("ru")     # настроек может не быть вовсе — справка нужна и так

    try:
        req = cliargs.parse(argv)
    except CliError as e:
        _out(e.full())
        return cliproto.EXIT_ARGS

    # Ждём по умолчанию: скрипт почти всегда хочет знать исход, а не «команда
    # принята». Кому надо вернуться сразу — тот скажет это словом +detach.
    if (req.command in (cliargs.LAUNCH, cliargs.RESTART, cliargs.STOP)
            and req.wait is None and not req.detach):
        req.wait = cliargs.WAIT_DEFAULT

    if req.command == cliargs.HELP:
        if req.as_json:
            _out(json.dumps(clihelp.capabilities(), ensure_ascii=False, indent=2))
        else:
            _out(clihelp.render(req.help_topic))
        return cliproto.EXIT_OK

    reply = _talk(req)
    if not reply:
        _out(i18n.tr("cli.bad_reply", "Непонятный ответ от KR QTS."))
        return cliproto.EXIT_NO_ENGINE

    if req.as_json:
        _out(json.dumps(reply.get("report") or reply.get("error") or {},
                        ensure_ascii=False, indent=2))
    elif reply.get("ok"):
        _out(clihelp.render_report(reply.get("report") or {}))
    else:
        err = reply.get("error") or {}
        _out(err.get("text", ""))
        if err.get("hint"):
            _out(err["hint"])
    return int(reply.get("exit", cliproto.EXIT_OK))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
