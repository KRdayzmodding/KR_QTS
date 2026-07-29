"""Статус запуска в журнале главной страницы: сервер, клиент, память, срывы.

Журнал запуска намеренно короткий — подробности лежат в окнах логов. Здесь
только то, что нужно видеть, не отрываясь от кнопки «Запустить»:

    Сервер: [KR] test TEST ................ [запущен]
      Скриптовая память: 2_GameLib 0% · 3_Game 14% · 4_World 32% · 5_Mission 11%
    Клиент: DayZDiag_x64 .................. [не запустился]
      Запуск сорван: 4_World — ar_buttstocks.c(11) — Invalid statement ')'

Сервер и клиент разделены: у них свои логи в разных папках, свои наборы модов
(-serverMod клиенту не уходит) и свои лимиты — одна общая строка не сказала бы,
где именно смотреть.

Блок переписывается на месте — так же, как таблица запаковки: иначе за один
запуск в журнал улетело бы несколько десятков почти одинаковых строк.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from core import crashlog, logsource, scriptmem
from core.i18n import tr

SERVER, CLIENT = "server", "client"

_DIM = "#777777"
_ERR = "#ff6b6b"
_ENGINE = "#e5c07b"
_MIN_WIDTH = 34
_INDENT = "&nbsp;&nbsp;"

# «Player "Kramtsov" (steamID=765… pos=<…>) is connected» — пишется в RPT
# сервера в момент, когда игрок реально вошёл в мир. Запущенный процесс клиента
# об этом ничего не говорит: окно может висеть на загрузке или не достучаться
# до сервера вовсе.
_JOIN_RE = re.compile(r'Player\s+".*?".*?\bis connected\b')


class _Side:
    """Состояние одной стороны — сервера или клиента."""

    def __init__(self, title: str):
        self.title = title
        self.name = ""
        self.state = ""
        self.active = False
        self.usage: dict[str, scriptmem.Usage] = {}
        self.crash: crashlog.CrashReport | None = None


class LaunchStatus:
    """Живой блок статуса внутри QPlainTextEdit журнала запуска."""

    def __init__(self, view: QPlainTextEdit):
        self.view = view
        self.sides = {
            SERVER: _Side(tr("common.server", "Сервер")),
            CLIENT: _Side(tr("common.client", "Клиент")),
        }
        self._block = -1

    # ------------------------------------------------------------- отрисовка

    def _line_head(self, side: _Side) -> str:
        left = f"{side.name} ".ljust(_MIN_WIDTH, ".")
        text = html.escape(f"{side.title}: {left} [{side.state}]")
        return f'<span style="color:#d4d4d4;">{text}</span>'

    def _line_memory(self, side: _Side) -> str:
        parts = []
        for layer in scriptmem.LAYERS:
            u = side.usage.get(layer)
            if u is None:
                # слой ещё не скомпилирован — показываем прочерк, а не 0%:
                # ноль читался бы как «памяти не занято», а это не так
                parts.append(f'<span style="color:{_DIM};">{layer} —</span>')
                continue
            col = scriptmem.color(u.percent)
            weight = ";font-weight:700" if u.dangerous else ""
            parts.append(f'<span style="color:{col}{weight};">{layer} '
                         f'{u.percent:.0f}%</span>')
        head = html.escape(tr("status.memory", "Скриптовая память") + ": ")
        return _INDENT + f'<span style="color:#d4d4d4;">{head}</span>' + " · ".join(parts)

    def _line_crash(self, side: _Side) -> str:
        """Причина сорвавшегося запуска — из crash-лога.

        Считать `(E)`-строки в RPT смысла нет: их там 71, и 63 из них — ругань
        движка на текстуры GUI, одинаковая при любом наборе модов. Значение
        имеет ровно одно: собрались скрипты или нет, и если нет — где именно.
        """
        c = side.crash
        if not c:
            return ""
        head = html.escape(tr("status.crash_head", "Запуск сорван") + ": ")
        return (_INDENT + f'<span style="color:{_ERR};font-weight:700;">{head}'
                f'{html.escape(c.summary())}</span>')

    def _html(self) -> str:
        lines: list[str] = []
        for key in (SERVER, CLIENT):
            side = self.sides[key]
            if not side.active:
                continue
            lines += [ln for ln in (self._line_head(side), self._line_memory(side),
                                    self._line_crash(side)) if ln]
        return "<br>".join(lines)

    def _render(self) -> None:
        doc = self.view.document()
        if self._block < 0 or self._block >= doc.blockCount():
            return
        cursor = QTextCursor(doc.findBlockByNumber(self._block))
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        cursor.removeSelectedText()
        # BlockUnderCursor забирает и разделитель перед блоком — возвращаем его,
        # кроме случая самого первого блока, у которого разделителя нет
        if self._block > 0:
            cursor.insertBlock()
        cursor.insertHtml(self._html())
        cursor.endEditBlock()

    # -------------------------------------------------------------- действия

    def start(self, server_name: str = "", client_name: str = "") -> None:
        """Начинает новый блок. Пустое имя = сторона не запускается и не
        показывается вовсе — пустая строка «Клиент: [—]» только мешала бы."""
        for key, name in ((SERVER, server_name), (CLIENT, client_name)):
            side = self.sides[key]
            side.name = name
            side.active = bool(name)
            side.state = tr("status.starting", "запускается")
            side.usage = {}
            side.crash = None
        self.view.appendHtml(self._html())
        # индекс — по факту вставки: в пустом документе appendHtml пишет в уже
        # существующий блок 0 и нового не создаёт
        self._block = self.view.document().blockCount() - 1

    def set_running(self, side: str) -> None:
        self.sides[side].state = tr("status.running", "запущен")
        self._render()

    def set_connecting(self, side: str) -> None:
        """Процесс живёт, но своей работы ещё не делает.

        Для клиента запущенный процесс ничего не значит: окно может висеть на
        загрузке или вовсе не достучаться до сервера. Запущенным считаем его с
        момента, когда игрок реально оказался в игре.
        """
        self.sides[side].state = tr("status.connecting", "подключается")
        self._render()

    def set_stopped(self, side: str) -> None:
        self.sides[side].state = tr("status.stopped", "остановлен")
        self._render()

    def set_usage(self, side: str, usage: scriptmem.Usage) -> None:
        self.sides[side].usage[usage.layer] = usage
        self._render()

    def set_crash(self, side: str, report) -> None:
        self.sides[side].crash = report
        self.sides[side].state = tr("status.failed", "не запустился")
        self._render()


class LaunchMonitor(QObject):
    """Следит за папкой логов одной стороны: память слоёв и срыв запуска.

    Два источника, оба обязательны. Память слоёв движок пишет только в RPT
    (живой хвост окна логов читает script_*.log — там её нет). А причину
    сорвавшегося запуска — только в отдельный crash_<дата>.log, и появляется
    он ровно тогда, когда запуск не удался.

    Всё считается строго за текущую сессию: файлы, лежавшие в папке на момент
    старта, запоминаются и игнорируются. Иначе первым же делом всплыл бы
    crash-лог прошлого запуска — как раз тот, ради исправления которого запуск
    и повторяют.
    """
    usage = Signal(str, object)     # сторона, scriptmem.Usage
    danger = Signal(str, object)    # впервые перевалило за 95%
    limit = Signal(str, object)     # лимит достигнут
    crashed = Signal(str, object)   # сторона, crashlog.CrashReport
    player_joined = Signal(str)     # в RPT сервера появился подключившийся игрок

    def __init__(self, side: str, parent=None):
        super().__init__(parent)
        self.side = side
        self._dir = None
        self._tailer: logsource.LogTailer | None = None
        self._known: set[str] = set()         # RPT, существовавшие до запуска
        self._known_crash: set[str] = set()   # crash-логи, существовавшие до запуска
        self._file = None                     # RPT текущей сессии
        self._crashed = False
        self._joined = False
        # слои, о которых уже сказали; раздельно, иначе слой, доросший до 96% и
        # потом упёршийся в лимит, второго — главного — сообщения бы не дал
        self._warned: set[str] = set()
        self._over: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._poll)

    def start(self, directory) -> None:
        self.stop()
        if not directory:
            return
        self._reset()
        self._dir = Path(directory)
        self._known = {str(f) for f in logsource.log_files(directory)
                       if f.suffix.upper() == ".RPT"}
        self._known_crash = crashlog.crash_files(self._dir)
        self._tailer = logsource.LogTailer(directory, pattern_filter="*.RPT")
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._tailer = None

    def _reset(self) -> None:
        self._file = None
        self._crashed = False
        self._joined = False
        self._warned.clear()
        self._over.clear()

    def _poll(self) -> None:
        if not self._tailer:
            return
        self._check_crash()
        lines = self._tailer.poll()
        current = self._tailer.current
        if current is None or str(current) in self._known:
            # RPT этого запуска ещё не создан — читаем пока старый, молчим
            return
        if current != self._file:
            self._file = current

        for line in lines:
            if not self._joined and _JOIN_RE.search(line):
                self._joined = True
                self.player_joined.emit(self.side)
            u = scriptmem.parse(line)
            if not u:
                continue
            self.usage.emit(self.side, u)
            # о каждом слое предупреждаем один раз: World компилируется заново
            # при каждой смене миссии, и повторные окна были бы навязчивы
            if u.over_limit and u.layer not in self._over:
                self._over.add(u.layer)
                self._warned.add(u.layer)
                self.limit.emit(self.side, u)
            elif u.dangerous and not u.over_limit and u.layer not in self._warned:
                self._warned.add(u.layer)
                self.danger.emit(self.side, u)

    def _check_crash(self) -> None:
        """Появился ли crash-лог этой сессии.

        Сообщаем один раз: движок дописывает файл не мгновенно, и без флага
        одно падение расползлось бы в несколько одинаковых окон.
        """
        if self._crashed or not self._dir:
            return
        path = crashlog.newest_since(self._dir, self._known_crash)
        if not path:
            return
        self._crashed = True
        self.crashed.emit(self.side, crashlog.parse(path))
