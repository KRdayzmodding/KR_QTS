"""Окно живого лога (сервер или клиент): подсветка, поиск, управление файлами."""
from __future__ import annotations

import html
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit
from qfluentwidgets import (
    PushButton, RadioButton, SearchLineEdit, CaptionLabel, MessageBox,
    FluentIcon as FIF,
)

from core.i18n import tr
from core import logsource

_COLORS = {"error": "#ff6b6b", "warning": "#e5c07b", "info": "#d4d4d4", "session": "#61afef"}
_MAX_BLOCKS = 20000  # строк в окне, старые вытесняются


class LogWindow(QWidget):
    """Самостоятельное окно — свободно перемещается и масштабируется."""

    def __init__(self, title: str):
        super().__init__(None, Qt.Window)
        self.setWindowTitle(title)
        self.resize(900, 500)
        self.directory: Path | None = None
        self.tailer: logsource.LogTailer | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        top = QHBoxLayout()
        self.search_edit = SearchLineEdit()
        self.search_edit.setPlaceholderText(tr("log.search_ph", "Поиск по логам…"))
        self.search_edit.returnPressed.connect(self._search)
        self.search_edit.searchSignal.connect(lambda _t: self._search())
        self.rb_current = RadioButton(tr("log.search_current", "Только в этом файле"))
        self.rb_all = RadioButton(tr("log.search_all", "Во всех файлах"))
        self.rb_current.setChecked(True)
        btn_search = PushButton(FIF.SEARCH, tr("log.search", "Найти"))
        btn_search.clicked.connect(self._search)
        top.addWidget(self.search_edit, 1)
        top.addWidget(self.rb_current)
        top.addWidget(self.rb_all)
        top.addWidget(btn_search)
        layout.addLayout(top)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(_MAX_BLOCKS)
        self.view.setFont(QFont("Consolas", 9))
        self.view.setStyleSheet("QPlainTextEdit{background:#1e1e1e;color:#d4d4d4;"
                                "border:1px solid #333;border-radius:6px;padding:4px;}")
        layout.addWidget(self.view, 1)

        bottom = QHBoxLayout()
        self.path_label = CaptionLabel("")
        btn_clear = PushButton(FIF.ERASE_TOOL, tr("log.clear", "Очистить"))
        btn_clear.setToolTip(tr("log.clear_tip",
                                "Очищает окно, файлы логов не трогает."))
        btn_clear.clicked.connect(self.view.clear)
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

    # ------------------------------------------------------------------ управление

    def set_directory(self, directory: Path | None) -> None:
        self.directory = directory
        self.path_label.setText(str(directory) if directory else
                                tr("log.no_dir", "Папка логов не определена"))
        # живой хвост — только скрипт-логи; RPT и прочее доступны через поиск
        self.tailer = (logsource.LogTailer(directory, pattern_filter="script_*.log")
                       if directory else None)
        if self.tailer:
            self.timer.start()
        else:
            self.timer.stop()

    def _poll(self) -> None:
        if not self.tailer:
            return
        for line in self.tailer.poll():
            if line.startswith("=== ") and line.endswith(" ==="):
                self._append(line, "session")
            else:
                self._append(line, logsource.classify(line))

    def _append(self, line: str, level: str) -> None:
        color = _COLORS.get(level, _COLORS["info"])
        self.view.appendHtml(f'<span style="color:{color};">{html.escape(line)}</span>')

    # ------------------------------------------------------------------ кнопки

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
            if self.tailer:
                self.tailer.current = None
                self.tailer._pos = 0
            n = logsource.delete_logs(self.directory)
            self._append(tr("log.deleted", "Удалено файлов: {n}", n=n), "session")

    def _search(self) -> None:
        if not self.directory:
            return
        q = self.search_edit.text().strip()
        if not q:
            return
        current = self.tailer.current if (self.rb_current.isChecked() and self.tailer) else None
        results = logsource.search_in_files(self.directory, q, current_only=current)
        self._append("", "info")
        self._append(tr("log.search_header", "=== Поиск «{q}»: найдено {n} ===",
                        q=q, n=len(results)), "session")
        for fname, lineno, text in results:
            self._append(f"{fname}:{lineno}: {text}", logsource.classify(text))
        self._append(tr("log.search_end", "=== Конец поиска ==="), "session")
