"""Сторона приложения: разбирает запросы внешнего управления и отвечает.

Пока движок живёт внутри окна, здесь же и живёт разбор. На втором этапе
оркестровка уедет в core/engine.py, окно станет представлением, а этот модуль
переедет за ней — протокол при этом не изменится, и написанные инструменты
продолжат работать.

Главное правило: наружу не задаётся ни одного вопроса. Спрашивать некого, а
процесс, замерший в ожидании ответа, — худший вид поломки для скрипта. Поэтому
предстартовая проверка возвращает список проблем текстом, а не диалогом.

Ожидание готовности сделано опросом, а не подпиской на пять сигналов:
состояние стороны собирается из процесса, готовности слоя и признака
остановки, и единственный честный способ узнать его — спросить у окна тем же
методом, которым его спрашивают индикаторы.
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from core import cliproto, logsource, overlay
from core.cliargs import ModRef, Overlay
from core.i18n import tr
from core.launcher import CLIENT, SERVER

POLL_MS = 500

# Виды логов, которые отдаём наружу. Консоль — только у сервера: её пишет
# движок сервера по logFile из serverDZ.cfg, у клиента такого файла нет.
SERVER_KINDS = ("script", "rpt", "console", "crash")
CLIENT_KINDS = ("script", "rpt", "crash")


def _overlay_from(data: dict) -> Overlay:
    """Восстанавливает накладку из присланного словаря.

    Разбор идёт по известным полям, а не через конструктор с распаковкой:
    инструмент постарше пришлёт меньше полей, поновее — больше, и ни то, ни
    другое не должно ронять движок.
    """
    ov = Overlay()
    for name in ("preset", "extra_client", "extra_server"):
        if isinstance(data.get(name), str):
            setattr(ov, name, data[name])
    for name in ("server", "client"):
        if isinstance(data.get(name), bool):
            setattr(ov, name, data[name])
    for name in ("params_client", "params_server"):
        if isinstance(data.get(name), dict):
            setattr(ov, name, dict(data[name]))
    for name in ("mods_replace", "server_mods_replace"):
        if isinstance(data.get(name), list):
            setattr(ov, name, [str(x) for x in data[name]])
    if isinstance(data.get("forget"), list):
        ov.forget = [str(x) for x in data["forget"]]
    if isinstance(data.get("pack"), str):
        ov.pack = data["pack"]
    ov.rebuild = bool(data.get("rebuild"))
    for item in data.get("mods") or []:
        if not isinstance(item, dict):
            continue
        ov.mods.append(ModRef(
            ref=str(item.get("ref", "")),
            side=str(item.get("side", "both")),
            add_sources=[str(x) for x in item.get("add_sources") or []],
            drop_sources=[str(x) for x in item.get("drop_sources") or []]))
    return ov


class CliServer(QObject):
    """Отвечает на запросы канала. Живёт столько же, сколько окно."""

    def __init__(self, win) -> None:
        super().__init__(win)
        self.win = win
        self._waits: list[_Wait] = []

    # ---------------------------------------------------------------- ответы

    def handle(self, conn, line: str) -> None:
        """Разбирает строку запроса и отвечает — сразу или после ожидания."""
        data = cliproto.decode(line)
        rid = int(data.get("id") or 1)
        cmd = str(data.get("cmd") or "")

        if not getattr(self.win.settings, "external_control", True):
            # Выключено человеком — отвечаем внятно, а не молчим: инструмент
            # иначе не отличит запрет от поломки канала.
            return self._reply(conn, cliproto.fail(
                rid, cliproto.E_NOT_CONFIGURED,
                tr("cli.disabled", "Внешнее управление выключено."),
                tr("cli.disabled_hint",
                   "Включается в настройках, раздел «Внешнее управление»."),
                cliproto.EXIT_NOT_READY))

        if cmd == "status":
            return self._reply(conn, cliproto.ok(rid, self.report()))
        if cmd == "show":
            self.win.restore_from_tray()
            return self._reply(conn, cliproto.ok(rid, self.report()))
        if cmd == "quit":
            self._reply(conn, cliproto.ok(rid, self.report()))
            # После ответа, а не до: закрыться раньше, чем ответ уйдёт по
            # каналу, значит оставить вызывающего с оборванным соединением.
            QTimer.singleShot(200, self.win.quit_app)
            return None
        if cmd == "stop":
            return self._stop(conn, rid, data)
        if cmd in ("launch", ""):
            return self._launch(conn, rid, data)
        return self._reply(conn, cliproto.fail(
            rid, cliproto.E_UNKNOWN_CMD,
            tr("cli.unknown_cmd", "Не знаю команду «{c}».").format(c=cmd),
            tr("cli.unknown_cmd_hint", "Известные: launch, stop, status, show, quit.")))

    def _reply(self, conn, line: str) -> None:
        if conn is None:
            return
        try:
            conn.write(line.encode("utf-8") + b"\n")
            conn.flush()
            conn.waitForBytesWritten(3000)
            conn.disconnectFromServer()
        except (OSError, RuntimeError):
            pass       # вызывающий отвалился — его дело, движок не при чём

    # -------------------------------------------------------------- команды

    def _stop(self, conn, rid: int, data: dict) -> None:
        if not (self.win.server_running() or self.win.client_running()):
            return self._reply(conn, cliproto.ok(rid, self.report()))
        self.win._stop_selected()
        if not data.get("wait"):
            return self._reply(conn, cliproto.ok(rid, self.report()))
        self._wait_for(conn, rid, want={}, seconds=int(data["wait"]), until_down=True)
        return None

    def _find_preset(self, name: str):
        """Пресет по имени или по имени файла — регистр не важен.

        Человек напишет «dev», а в списке лежит «Dev (Chernarus)»: ищем и по
        отображаемому имени, и по имени файла, иначе команда из скрипта будет
        падать на заглавной букве.
        """
        want = (name or "").strip().lower()
        for i, p in enumerate(self.win.presets):
            if want in (p.name.strip().lower(), p.file_stem().lower()):
                return i, p
        return -1, None

    def _launch(self, conn, rid: int, data: dict) -> None:
        win = self.win
        ov = _overlay_from(data.get("args") or {})

        busy = win._busy_state()
        if busy in ("prep", "stop"):
            return self._reply(conn, cliproto.fail(
                rid, cliproto.E_BUSY,
                tr("cli.busy", "Программа занята: {s}.").format(s=busy),
                tr("cli.busy_hint", "Дождись окончания или потуши: qtsctl stop"),
                cliproto.EXIT_NOT_READY))

        if ov.preset:
            idx, found = self._find_preset(ov.preset)
            if found is None:
                names = ", ".join(p.name for p in win.presets) or "—"
                return self._reply(conn, cliproto.fail(
                    rid, cliproto.E_NO_PRESET,
                    tr("cli.no_preset", "Пресета «{n}» нет.").format(n=ov.preset),
                    tr("cli.no_preset_hint", "Есть: {list}").format(list=names),
                    cliproto.EXIT_NOT_READY))
            if idx != win.launch_page.preset_combo.currentIndex():
                win.launch_page.preset_combo.setCurrentIndex(idx)
        if not win.current:
            return self._reply(conn, cliproto.fail(
                rid, cliproto.E_NOT_CONFIGURED,
                tr("cli.no_presets", "В программе нет ни одного пресета."),
                "", cliproto.EXIT_NOT_READY))

        plan = overlay.plan(ov, win.registry)
        overlay.commit(plan, win.registry, win.settings)
        preset = overlay.apply(win.current, ov, plan)

        # Накладка не видна в окне, а поведение меняет — значит о ней надо
        # сказать там, куда человек смотрит. Иначе он сверится с пресетом и
        # полчаса будет искать, откуда взялся filePatching.
        win._append_log(tr("cli.launch_note", "— Запуск извне: пресет «{n}» —",
                           n=preset.name))

        error = win._launch(preset=preset, quiet=True, pack=ov.pack,
                            rebuild=ov.rebuild)
        if error:
            return self._reply(conn, cliproto.fail(
                rid, cliproto.E_NOT_CONFIGURED, error, "", cliproto.EXIT_NOT_READY))

        want = {SERVER: preset.launch_server, CLIENT: preset.launch_client}
        seconds = int(data.get("wait") or 0)
        if data.get("detach") or not seconds:
            return self._reply(conn, cliproto.ok(rid, self.report(plan)))
        self._wait_for(conn, rid, want, seconds, plan=plan)
        return None

    # -------------------------------------------------------------- ожидание

    def _wait_for(self, conn, rid: int, want: dict, seconds: int,
                  plan=None, until_down: bool = False) -> None:
        w = _Wait(self, conn, rid, want, seconds, plan, until_down)
        self._waits.append(w)
        w.start()

    def _drop(self, w) -> None:
        if w in self._waits:
            self._waits.remove(w)

    # ---------------------------------------------------------------- отчёт

    def report(self, plan=None) -> dict:
        win = self.win
        out = {"preset": win.current.name if win.current else "",
               "pack": win.pack_table.report(),
               "server": self._side(SERVER),
               "client": self._side(CLIENT),
               "problems": self._problems()}
        if win.launch_error:
            out["error"] = win.launch_error
        if plan is not None:
            out["notes"] = [n.as_dict() for n in plan.notes]
        return out

    def _side(self, side: str) -> dict:
        win = self.win
        st = win.launch_status.sides[side]
        pid = win.side_pid(side)
        data = {"requested": bool(st.active or pid),
                "started": bool(pid) and win.process_state(pid) == win.ST_RUN,
                "ready": win.launch_status.is_ready(side),
                "state": win.side_state(side),
                "script_errors": win.launch_status.errors(side),
                "crashed": st.crash is not None,
                "logs": self._logs(side)}
        if pid:
            data["pid"] = pid
        if side == SERVER and win.current:
            data["port"] = win.current.port
        return data

    def _logs(self, side: str) -> dict:
        """Прямые пути к файлам логов — чтобы читать, а не искать.

        Отдаём и при провале: там они нужнее всего. Пустые виды пропускаем,
        иначе вызывающий получит словарь из одних None и будет их проверять.
        """
        win = self.win
        try:
            if side == SERVER:
                folder = logsource.server_log_dir(win.current, win.settings,
                                                  win._branch()) if win.current else None
                kinds = SERVER_KINDS
            else:
                folder = logsource.client_log_dir(win._branch())
                kinds = CLIENT_KINDS
        except (OSError, AttributeError):
            return {}
        out = {}
        for kind in kinds:
            found = logsource.newest_of_kind(Path(folder) if folder else None, kind)
            if found:
                out[kind] = str(found)
        return out

    def pack_failed(self) -> bool:
        """Сорвалась ли сборка. По таблице, а не по тексту ошибки: разбирать
        сообщение, чтобы понять, что случилось, — способ ошибиться при первом
        же переводе."""
        return any(i.get("status") == "fail"
                   for i in self.win.pack_table.report()["items"])

    def _problems(self) -> list:
        """Ошибки скриптов и сорванные запуски — списком, а не кодом возврата.

        Наше дело сообщить факт; что с ним делать, решает тот, кто запускал.
        """
        out = []
        for side in (SERVER, CLIENT):
            st = self.win.launch_status.sides[side]
            if st.crash is not None:
                out.append(_crash_dict(side, "crash", st.crash))
            if st.errors:
                item = _crash_dict(side, "script_error", st.last_error)
                item["count"] = st.errors
                out.append(item)
        return out


def _crash_dict(side: str, kind: str, report) -> dict:
    out = {"side": side, "kind": kind}
    if report is None:
        return out
    out["text"] = report.summary() if hasattr(report, "summary") else str(report)
    for name in ("file", "line", "layer", "message"):
        value = getattr(report, name, "")
        if value:
            out[name] = value
    path = getattr(report, "path", None)
    if path:
        out["log"] = str(path)
    return out


class _Wait(QObject):
    """Ожидание готовности одним таймером.

    Опрос, а не подписка: состояние стороны складывается из живого процесса,
    готовности слоя и признака остановки, и собирает его окно. Спрашивать его
    тем же методом, которым спрашивают индикаторы, — единственный способ не
    разойтись с тем, что видит человек.
    """

    def __init__(self, server: CliServer, conn, rid: int, want: dict,
                 seconds: int, plan, until_down: bool) -> None:
        super().__init__(server)
        self.server = server
        self.conn = conn
        self.rid = rid
        self.want = want
        self.plan = plan
        self.until_down = until_down
        self.deadline = time.monotonic() + max(1, seconds)
        self.started = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self._tick)

    def start(self) -> None:
        self.timer.start()
        self._tick()

    def _finish(self, code: int) -> None:
        self.timer.stop()
        report = self.server.report(self.plan)
        report["seconds"] = int(time.monotonic() - self.started)
        self.server._reply(self.conn, cliproto.ok(self.rid, report, code))
        self.server._drop(self)
        self.deleteLater()

    def _tick(self) -> None:
        win = self.server.win
        if self.until_down:
            if not (win.server_running() or win.client_running()):
                return self._finish(cliproto.EXIT_OK)
        else:
            done = True
            for side, wanted in self.want.items():
                if wanted and not win.launch_status.is_ready(side):
                    done = False
            if done:
                return self._finish(cliproto.EXIT_OK)
            # Сорванный запуск ждать бессмысленно: сторона уже не поднимется —
            # отвечаем сразу, а не по таймауту.
            if win.launch_error:
                return self._finish(cliproto.EXIT_PACK if self.server.pack_failed()
                                    else cliproto.EXIT_SERVER)
            for side, wanted in self.want.items():
                if wanted and win.launch_status.sides[side].crash is not None:
                    return self._finish(cliproto.EXIT_SERVER if side == SERVER
                                        else cliproto.EXIT_CLIENT)

        if time.monotonic() < self.deadline:
            return None
        code = cliproto.EXIT_OK
        if self.until_down:
            code = cliproto.EXIT_CRASHED
        elif self.want.get(SERVER) and not win.launch_status.is_ready(SERVER):
            code = cliproto.EXIT_SERVER
        elif self.want.get(CLIENT) and not win.launch_status.is_ready(CLIENT):
            code = cliproto.EXIT_CLIENT
        return self._finish(code)
