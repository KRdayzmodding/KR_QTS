"""Окно живого лога (сервер или клиент): подсветка, поиск, управление файлами."""
from __future__ import annotations

import html
import os
import re
import sys
from collections import deque
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
                               QLabel, QSizePolicy)
from qfluentwidgets import (
    PushButton, RadioButton, SearchLineEdit, CaptionLabel, CheckBox, MessageBox, ComboBox,
    FluentIcon as FIF, isDarkTheme, qconfig,
)

from core.i18n import tr
from core import logsource

# По сколько файлов подтягивать в режиме «во всех файлах». Их бывают сотни,
# и читать всё разом незачем: нужное почти всегда в последних.
_FILES_STEP = 10
_COLORS = {"error": "#ff6b6b", "warning": "#e5c07b", "info": "#d4d4d4", "session": "#61afef"}
_MAX_BLOCKS = 20000  # строк в окне, старые вытесняются

# Подсветка отдельных токенов внутри строки (поверх общего цвета по уровню) —
# порядок групп важен: более специфичные (time/tag/string/keyword) идут перед
# общим number, иначе номер внутри времени/тега перехватил бы совпадение
_TOKEN_RE = re.compile(
    r"(?P<time>\b\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\b)"
    r"|(?P<tag>\[[^\]\r\n]{1,60}\])"
    r"|(?P<string>\"[^\"\r\n]*\")"
    r"|(?P<keyword>\b(?:error|warning|exception|fatal|critical|deprecated|obsolete"
    r"|cannot find|can't|missing)\b)"
    r"|(?P<number>-?\d+\.\d+|\b\d{5,}\b)",
    re.IGNORECASE,
)
_TOKEN_COLORS = {
    "time": "#61afef",     # синий — временные метки
    "tag": "#c678dd",      # фиолетовый — [KR_CORE] и подобные теги в скобках
    "string": "#98c379",   # зелёный — строки в кавычках
    "number": "#d19a66",   # оранжевый — числа/координаты, SteamID и т.п.
}


_MATCH_STYLE = "background:#5a4a00;color:#ffe08a;font-weight:700;"


def _highlight(line: str, query: str = "") -> str:
    """HTML с раскрашенными токенами; текст вне токенов — без цвета (наследует
    цвет уровня строки, заданный обёрткой в _show).

    Найденное по поиску подсвечивается поверх: подсветка идёт первым проходом,
    а разметка токенов — уже по кускам между совпадениями. Иначе пришлось бы
    вставлять теги внутрь тегов.
    """
    if query:
        out, low, pos = [], line.lower(), 0
        while True:
            i = low.find(query, pos)
            if i < 0:
                out.append(_highlight(line[pos:]))
                return "".join(out)
            out.append(_highlight(line[pos:i]))
            out.append(f'<span style="{_MATCH_STYLE}">'
                       f'{html.escape(line[i:i + len(query)])}</span>')
            pos = i + len(query)
    out = []
    pos = 0
    for m in _TOKEN_RE.finditer(line):
        if m.start() > pos:
            out.append(html.escape(line[pos:m.start()]))
        kind = m.lastgroup
        text = html.escape(m.group())
        if kind == "keyword":
            out.append(f'<b style="color:{_COLORS["error"]};">{text}</b>')
        else:
            out.append(f'<span style="color:{_TOKEN_COLORS[kind]};">{text}</span>')
        pos = m.end()
    out.append(html.escape(line[pos:]))
    return "".join(out)


class _SearchWorker(QThread):
    """Поиск по файлам логов в фоне.

    Отменяется флагом, а не завершением потока: прервать чтение файла снаружи
    нельзя, зато сам обход проверяет флаг и выходит. Устаревший поиск при этом
    не дочитывает сотни мегабайт впустую.
    """
    done = Signal(int, list, bool)   # номер запроса, результаты, «один файл»

    def __init__(self, directory, query: str, current_only, limit: int,
                 req: int, one_file: bool, parent=None):
        super().__init__(parent)
        self.directory = directory
        self.query = query
        self.current_only = current_only
        self.limit = limit
        self.req = req
        self.one_file = one_file
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            res = logsource.search_in_files(
                self.directory, self.query, current_only=self.current_only,
                max_results=self.limit, cancel=lambda: self._cancelled)
        except OSError:
            res = []
        if not self._cancelled:
            self.done.emit(self.req, res, self.one_file)


class _LoadWorker(QThread):
    """Чтение последних файлов лога в фоне.

    RPT за неделю набирают сотни мегабайт, и читать их на главном потоке —
    это замерзание окна на всё время чтения. Объём ограничен: показать больше
    нескольких десятков тысяч строк всё равно нечем.
    """
    done = Signal(int, list, int)   # номер запроса, строки, сколько файлов ещё есть

    def __init__(self, files: list, rest: int, limit: int, req: int, parent=None):
        super().__init__(parent)
        self.files = files
        self.rest = rest
        self.limit = limit
        self.req = req
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        out: list[tuple[str, str]] = []
        # от старых к новым: в окне свежее должно оказаться внизу
        for path in reversed(self.files):
            if self._cancelled:
                return
            out.append((f"=== {path.name} ===", "session"))
            try:
                with open(path, "rb") as f:
                    for raw in f:
                        if self._cancelled:
                            return
                        line = raw.decode("utf-8", "replace").rstrip("\r\n")
                        out.append((line, logsource.classify(line)))
                        if len(out) >= self.limit:
                            break
            except OSError as e:
                out.append((f"{path.name}: {e}", "error"))
            if len(out) >= self.limit:
                break
        if not self._cancelled:
            self.done.emit(self.req, out, self.rest)


class LogWindow(QWidget):
    """Самостоятельное окно — свободно перемещается и масштабируется."""

    def __init__(self, title: str, accent: str = "#61afef", banner_text: str = "",
                 key: str = ""):
        super().__init__(None, Qt.Window)
        self.setWindowTitle(title)
        self.resize(900, 500)
        self.key = key                  # «server» / «client» — чьё это окно
        self.directory: Path | None = None
        self.kind = "script"            # выбранный вид логов, см. logsource.KINDS
        self._known: set[str] = set()   # файлы, лежавшие до начала запуска
        self._shown_files = _FILES_STEP # сколько файлов показано в режиме «все»
        self._load_req = 0
        self._load_worker: _LoadWorker | None = None
        self.tailers: list[logsource.LogTailer] = []
        self.tailer: logsource.LogTailer | None = None   # первый из них — для поиска
        self._path_text = ""

        # само окно — обычный QWidget, в отличие от диалогов qfluentwidgets
        # фон себе не красит вообще (остаётся системным светлым даже в тёмной
        # теме) — красим вручную и подписываемся на смену темы «на лету»
        self._apply_bg()
        qconfig.themeChanged.connect(self._apply_bg)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        # цветная плашка с названием окна — чтобы окна сервера и клиента
        # различались с первого взгляда, а не только текстом в заголовке ОС
        banner = QLabel(banner_text or title)
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner.setStyleSheet(
            f"QLabel{{background:{accent};color:#ffffff;font-weight:600;"
            f"font-size:16pt;padding:8px 10px;border-radius:6px;}}")
        layout.addWidget(banner)

        top = QHBoxLayout()
        # Вид лога — слева от поиска: он определяет, по чему вообще смотрим,
        # и менять его логично до того, как что-то искать.
        self.kind_combo = ComboBox()
        for value, label in (("script", tr("log.kind_script", "Скрипты")),
                             ("crash", tr("log.kind_crash", "Падения")),
                             ("rpt", tr("log.kind_rpt", "RPT"))):
            self.kind_combo.addItem(label, userData=value)
        self.kind_combo.setMinimumWidth(120)
        self.kind_combo.setToolTip(tr("log.kind_tip",
                                      "Скрипты — ошибки модов; падения — почему "
                                      "сорвался запуск; RPT — полный журнал движка."))
        self.kind_combo.currentIndexChanged.connect(lambda _i: self._kind_changed())
        self.search_edit = SearchLineEdit()
        self.search_edit.setPlaceholderText(tr("log.search_ph", "Поиск по логам…"))
        # поиск интерактивный: список сужается по мере набора, без Enter
        self.search_edit.textChanged.connect(self._search_typed)
        self.search_edit.returnPressed.connect(self._apply_search)
        self.search_edit.searchSignal.connect(lambda _t: self._apply_search())
        self.rb_current = RadioButton(tr("log.search_session", "Текущая сессия"))
        self.rb_all = RadioButton(tr("log.search_all", "Во всех файлах"))
        self.rb_current.setChecked(True)
        self.rb_current.toggled.connect(lambda _c: self._reload())
        # галка живёт здесь, а не в нижнем ряду: там она стояла после пути к
        # папке логов и ездила по горизонтали вслед за его длиной
        self.chk_on_top = CheckBox(tr("log.on_top", "Поверх всех окон"))
        self.chk_on_top.setToolTip(tr("log.on_top_tip",
                                      "Окно не будет уходить за игру и редактор."))
        self.chk_on_top.toggled.connect(self._on_top_toggled)
        top.addWidget(self.kind_combo)
        top.addWidget(self.search_edit, 1)
        top.addWidget(self.rb_current)
        top.addWidget(self.rb_all)
        top.addWidget(self.chk_on_top)
        layout.addLayout(top)

        self.btn_more = PushButton(FIF.CHEVRON_DOWN_MED, "")
        self.btn_more.setVisible(False)
        self.btn_more.clicked.connect(self._load_more)
        layout.addWidget(self.btn_more)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(_MAX_BLOCKS)
        self.view.setFont(QFont("Consolas", 9))
        self.view.setStyleSheet("QPlainTextEdit{background:#1e1e1e;color:#d4d4d4;"
                                "border:1px solid #333;border-radius:6px;padding:4px;}")
        layout.addWidget(self.view, 1)

        bottom = QHBoxLayout()
        self.path_label = CaptionLabel("")
        # путь к папке логов бывает длиннее окна; без этого он растягивал ряд и
        # уносил кнопки вправо — теперь обрезается многоточием по месту
        self.path_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                      QSizePolicy.Policy.Preferred)
        btn_clear = PushButton(FIF.ERASE_TOOL, tr("log.clear", "Очистить"))
        btn_clear.setToolTip(tr("log.clear_tip",
                                "Очищает окно, файлы логов не трогает."))
        btn_clear.clicked.connect(self._clear)
        btn_open = PushButton(FIF.FOLDER, tr("log.open_dir", "Открыть папку"))
        btn_open.clicked.connect(self._open_dir)
        btn_delete = PushButton(FIF.DELETE, tr("log.delete_files", "Удалить файлы логов"))
        btn_delete.setToolTip(tr("log.delete_tip",
                                 "Удаляет все файлы логов в папке. Окно не очищается."))
        btn_delete.clicked.connect(self._delete_files)
        bottom.addWidget(self.path_label, 1)
        bottom.addWidget(btn_clear)
        bottom.addWidget(btn_open)
        bottom.addWidget(btn_delete)
        layout.addLayout(bottom)

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._poll)

        # Все полученные строки держим у себя: поиск фильтрует именно их, а
        # QPlainTextEdit прочитать построчно с разметкой уже нельзя. Предел
        # тот же, что у виджета, — старое вытесняется одинаково.
        self._buffer: deque = deque(maxlen=_MAX_BLOCKS)
        self._query = ""
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)   # набор идёт быстрее перерисовки
        self._search_timer.timeout.connect(self._apply_search)
        # номер запроса: ответ устаревшего поиска приходит после нового и
        # затирал бы его результат
        self._search_req = 0
        self._search_worker: _SearchWorker | None = None
        self._on_top = False

        # кому сообщить о смене галки — главное окно сохраняет её в настройки.
        # Состояние своё у каждого окна: держать поверх всего обычно нужно одно
        # из двух, а второе в это же время только мешало бы.
        self.on_top_changed = None

    # ------------------------------------------------------------------ управление

    def _on_top_toggled(self, on: bool) -> None:
        self.set_on_top(on)
        if self.on_top_changed:
            self.on_top_changed(self.key, on)

    def set_on_top(self, on: bool) -> None:
        """Флаг «поверх всех» и синхронизация галки."""
        if self.chk_on_top.isChecked() != on:
            self.chk_on_top.blockSignals(True)
            self.chk_on_top.setChecked(on)
            self.chk_on_top.blockSignals(False)
        self._on_top = on
        self._apply_on_top()

    def _apply_on_top(self) -> None:
        """Ставит окно поверх остальных.

        Через setWindowFlag Qt пересоздаёт нативное окно, и его приходится
        показывать заново — окно на мгновение исчезает и появляется, то самое
        моргание. SetWindowPos меняет тот же признак у существующего окна, без
        пересоздания. На не-Windows и при любой осечке остаётся прежний путь.
        """
        if self._set_topmost_native(self._on_top):
            return
        if bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) == self._on_top:
            return
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._on_top)
        if visible:
            self.show()

    def _set_topmost_native(self, on: bool) -> bool:
        """SetWindowPos поверх/не поверх. False — не получилось, зовите Qt.

        Типы аргументов объявляются обязательно: по умолчанию ctypes считает
        int 32-битным и режет 64-битный HWND, после чего вызов молча
        возвращает 0 и ничего не делает.
        """
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            from ctypes import wintypes
            HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
            fn = ctypes.windll.user32.SetWindowPos
            fn.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            fn.restype = wintypes.BOOL
            return bool(fn(wintypes.HWND(int(self.winId())),
                           wintypes.HWND(HWND_TOPMOST if on else HWND_NOTOPMOST),
                           0, 0, 0, 0,
                           SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE))
        except Exception:  # noqa: BLE001 — winapi через ctypes: любая осечка означает «не вышло», дальше запасной путь
            return False

    def showEvent(self, event):
        # признак топмоста живёт у нативного окна: при повторном показе Qt
        # создаёт его заново, и признак нужно проставить снова
        super().showEvent(event)
        if self._on_top:
            self._apply_on_top()

    def _apply_bg(self) -> None:
        bg = "rgb(43, 43, 43)" if isDarkTheme() else "white"
        self.setStyleSheet(f"QWidget{{background-color:{bg};}}")

    def _show_path(self) -> None:
        """Путь с многоточием по ширине метки; полный — в подсказке."""
        text = self._path_text
        fm = self.path_label.fontMetrics()
        width = max(80, self.path_label.width())
        self.path_label.setText(fm.elidedText(text, Qt.TextElideMode.ElideMiddle, width))
        self.path_label.setToolTip(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._show_path()

    def set_directory(self, directory: Path | None, new_session: bool = True) -> None:
        """Задаёт папку логов. new_session — начинается запуск клиента/сервера.

        Момент запуска запоминается снимком уже лежащих файлов: всё, что
        появится после, и есть текущая сессия. Без этого «текущая сессия»
        показывала бы логи прошлого запуска — как раз того, ради исправления
        которого запуск и повторяют.
        """
        self.directory = directory
        self._path_text = (str(directory) if directory else
                           tr("log.no_dir", "Папка логов не определена"))
        self._show_path()
        if new_session:
            self._known = {str(p) for kind in logsource.KINDS
                           for p in logsource.files_of_kind(directory, kind)}
        self._reload()

    def _kind_changed(self) -> None:
        self.kind = self.kind_combo.currentData() or "script"
        self._reload()

    def _session_file(self) -> Path | None:
        """Файл выбранного вида, появившийся уже после начала запуска."""
        newest = logsource.newest_of_kind(self.directory, self.kind)
        return None if newest is None or str(newest) in self._known else newest

    def _reload(self) -> None:
        """Пересобирает окно под выбранный вид и режим."""
        self.timer.stop()
        self.tailers = []
        self.tailer = None
        self._buffer.clear()
        self.view.clear()
        self.btn_more.setVisible(False)
        if self._load_worker:
            self._load_worker.cancel()
            self._load_worker = None
        if not self.directory:
            self._show(tr("log.no_dir", "Папка логов не определена"), "session")
            return

        if self.rb_current.isChecked():
            if self._session_file() is None:
                self._show(tr("log.no_session",
                              "Клиент или сервер ещё не запускались — "
                              "показывать нечего."), "session")
                return
            # тейлер сам переходит на более новый файл, если движок его заведёт
            tailer = logsource.LogTailer(
                self.directory, pattern_filter=logsource.KINDS[self.kind][0])
            self.tailers = [tailer]
            self.tailer = tailer
            self.timer.start()
            return
        self._load_recent(self._shown_files)

    def _load_recent(self, count: int) -> None:
        """Показывает последние count файлов выбранного вида."""
        files = logsource.files_of_kind(self.directory, self.kind)
        if not files:
            self._show(tr("log.no_files", "Файлов этого вида в папке нет."), "session")
            return
        self._shown_files = count
        take, rest = files[:count], max(0, len(files) - count)
        self._load_req += 1
        self._show(tr("log.loading", "Чтение файлов…"), "session")
        worker = _LoadWorker(take, rest, _MAX_BLOCKS, self._load_req, self)
        worker.done.connect(self._load_done)
        self._load_worker = worker
        worker.start()

    def _load_done(self, req: int, lines: list, rest: int) -> None:
        if req != self._load_req:
            return
        self.view.clear()
        self._buffer.clear()
        for line, level in lines:
            self._buffer.append((line, level))
            self._show(line, level)
        self.btn_more.setVisible(rest > 0)
        if rest > 0:
            self.btn_more.setText(tr("log.more", "Загрузить ещё ({n} файлов)", n=rest))

    def _load_more(self) -> None:
        self._load_recent(self._shown_files + _FILES_STEP)

    def _poll(self) -> None:
        for tailer in self.tailers:
            for line in tailer.poll():
                if line.startswith("=== ") and line.endswith(" ==="):
                    self._append(line, "session")
                else:
                    self._append(line, logsource.classify(line))

    def _append(self, line: str, level: str) -> None:
        self._buffer.append((line, level))
        # при активном фильтре новые строки показываем, только если подходят —
        # иначе живой хвост затирал бы результат поиска
        if not self._query or self._query in line.lower():
            self._show(line, level)

    def _show(self, line: str, level: str) -> None:
        color = _COLORS.get(level, _COLORS["info"])
        self.view.appendHtml(f'<span style="color:{color};">'
                             f'{_highlight(line, self._query)}</span>')

    # ------------------------------------------------------------------ поиск

    def _search_typed(self, _text: str) -> None:
        self._search_timer.start()

    _SEARCH_LIMIT = 5000    # больше в окно всё равно не имеет смысла лить

    def _apply_search(self) -> None:
        """Оставляет в окне только подходящие строки.

        Ищем по файлу на диске, а не по тому, что успело натечь живым хвостом:
        хвост держит последние строки одного script-лога, их обычно пара
        десятков, и поиск по ним не поиск, а видимость. «Только в этом файле» —
        текущий лог сессии целиком, «во всех файлах» — вся папка логов.

        Пустой запрос возвращает окно к живому хвосту.
        """
        self._search_timer.stop()
        self._query = self.search_edit.text().strip().lower()
        raw = self.search_edit.text().strip()
        self.view.clear()
        if not self._query:
            for line, level in self._buffer:
                self._show(line, level)
            return
        if not self.directory:
            for line, level in self._buffer:
                if self._query in line.lower():
                    self._show(line, level)
            return

        # Чтение папки логов уходит в поток: она линейно зависит от объёма
        # (19 МБ — 53 мс), а за неделю RPT набирают сотни мегабайт. На главном
        # потоке это означало бы замерзание окна на каждую букву.
        one_file = self.rb_current.isChecked()
        current = self.tailer.current if (one_file and self.tailer) else None
        self._search_req += 1
        self._show(tr("log.searching", "Поиск «{q}»…", q=raw), "session")
        worker = _SearchWorker(self.directory, self._query, current,
                               self._SEARCH_LIMIT, self._search_req, one_file, self)
        worker.done.connect(self._search_done)
        if self._search_worker:
            self._search_worker.cancel()    # прошлый запрос уже неактуален
        self._search_worker = worker
        worker.start()

    def _search_done(self, req: int, results: list, one_file: bool) -> None:
        """Показывает результат, если он всё ещё относится к текущему запросу."""
        if req != self._search_req:
            return
        raw = self.search_edit.text().strip()
        self.view.clear()
        if not results:
            self._show(tr("log.search_none", "Ничего не найдено: «{q}»", q=raw), "session")
            return
        for fname, lineno, text in results:
            # имя файла нужно только когда файлов несколько; номер строки —
            # всегда, иначе в отфильтрованном виде теряешь место в логе
            prefix = f"{lineno}: " if one_file else f"{fname}:{lineno}: "
            self._show(prefix + text, logsource.classify(text))
        if len(results) >= self._SEARCH_LIMIT:
            self._show(tr("log.search_capped",
                          "=== показаны первые {n}; уточните запрос ===",
                          n=self._SEARCH_LIMIT), "session")

    # ------------------------------------------------------------------ кнопки

    def _clear(self) -> None:
        """Чистит и окно, и буфер: иначе следующий же поиск вернул бы всё назад."""
        self._buffer.clear()
        self.view.clear()

    def _open_dir(self) -> None:
        if self.directory and self.directory.is_dir():
            os.startfile(str(self.directory))  # noqa: S606 — открытие проводника

    def _delete_files(self) -> None:
        if not self.directory:
            return
        box = MessageBox(
            tr("log.delete_title", "Удаление логов"),
            tr("log.delete_confirm", "Удалить все файлы логов в {p}?", p=self.directory),
            self,
        )
        if box.exec():
            # файлов больше нет — тейлеры должны начать с чистого листа,
            # иначе продолжат читать с прежнего смещения в новом файле
            for t in self.tailers:
                t._restart(None)
            n = logsource.delete_logs(self.directory)
            self._append(tr("log.deleted", "Удалено файлов: {n}", n=n), "session")

