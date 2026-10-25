"""Окно установки [KR] Dev Toolkit: загрузка установщика и его запуск.

Подтверждения перед началом нет: загрузку можно оборвать в любой миг, а
лишний вопрос «точно скачать?» после нажатия кнопки «Скачать и установить»
— это второй раз спросить то же самое. Зато видно, откуда файл и сколько его
осталось: 137 мегабайт идут не мгновенно.

Саму установку ведёт их установщик в своём окне — он спрашивает папку и
работает без прав администратора. Мы ждём, пока он закроется, и говорим,
нашёлся тулкит или нет.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    BodyLabel, CaptionLabel, ProgressBar, PushButton, StrongBodyLabel,
)

from core import toolkit_setup
from core.i18n import tr
from ui import tokens
from ui.theme import ThemedDialog, link_html


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.0f}"


class ToolkitSetupDialog(ThemedDialog):
    """Качает установщик, запускает его и ждёт, чем кончилось."""

    installed = Signal()        # установщик закрылся, тулкит нашёлся

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("toolkit.title", "Установка [KR] Dev Toolkit"))
        self.resize(*tokens.WIN_S)
        self._worker: toolkit_setup.SetupWorker | None = None
        self._proc = None
        self._path = ""
        self._watch = QTimer(self)
        self._watch.setInterval(1000)
        self._watch.timeout.connect(self._poll_installer)

        box = QVBoxLayout(self)
        box.setContentsMargins(tokens.SPACE_L, tokens.SPACE_L,
                               tokens.SPACE_L, tokens.SPACE_L)
        box.setSpacing(tokens.SPACE_S)

        box.addWidget(StrongBodyLabel(tr(
            "toolkit.head", "Запаковщик, которым будет собираться мод")))
        about = CaptionLabel(tr(
            "toolkit.about",
            "Project Builder входит в [KR] Dev Toolkit — отдельную программу. "
            "Она ставится без прав администратора и дальше обновляется сама; "
            "QTS найдёт её после установки без лишних настроек."))
        about.setWordWrap(True)
        box.addWidget(about)

        # Откуда файл — видно до того, как он скачан, а не после.
        source = CaptionLabel("")
        source.setTextFormat(Qt.TextFormat.RichText)
        source.setOpenExternalLinks(True)
        source.setWordWrap(True)
        source.setText(tr("toolkit.source", "Источник: {link}",
                          link=link_html(
                              f"https://github.com/{toolkit_setup.REPO}/releases/tag/"
                              f"{toolkit_setup.SETUP_TAG}",
                              f"github.com/{toolkit_setup.REPO}")))
        box.addWidget(source)

        self.bar = ProgressBar()
        self.bar.setRange(0, 0)         # пока не знаем размер — бегущая
        box.addWidget(self.bar)

        self.note = BodyLabel(tr("toolkit.asking", "Узнаём размер загрузки…"))
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        box.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.close_btn = PushButton(tr("common.cancel", "Отмена"))
        self.close_btn.clicked.connect(self.reject)
        buttons.addWidget(self.close_btn)
        box.addLayout(buttons)

        QTimer.singleShot(0, self._start)

    # ------------------------------------------------------------ загрузка

    def _start(self) -> None:
        self._worker = toolkit_setup.SetupWorker(parent=self)
        self._worker.progress.connect(self._progress)
        self._worker.done.connect(self._downloaded)
        self._worker.failed.connect(self._failed)
        self._worker.start()

    def _progress(self, got: int, total: int) -> None:
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(got)
            self.note.setText(tr("toolkit.getting", "Скачано {got} из {total} МБ",
                                 got=_mb(got), total=_mb(total)))
        else:
            self.note.setText(tr("toolkit.getting_blind", "Скачано {got} МБ",
                                 got=_mb(got)))

    def _downloaded(self, path: str) -> None:
        self.bar.setRange(0, 0)
        self._proc = toolkit_setup.launch(path)
        if self._proc is None:
            self._failed(tr("toolkit.no_run", "не удалось запустить установщик"))
            return
        self._path = path
        self.note.setText(tr(
            "toolkit.running",
            "Установщик запущен — продолжайте в его окне. Это окно можно "
            "закрыть, установке оно не мешает."))
        # Кнопка больше не отменяет загрузку: отменять нечего.
        self.close_btn.setText(tr("common.close", "Закрыть"))
        self._watch.start()

    def _failed(self, why: str) -> None:
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.note.setText(tr("toolkit.failed", "Не получилось: {why}", why=why))
        self.close_btn.setText(tr("common.close", "Закрыть"))

    # ------------------------------------------------------------ установка

    def _poll_installer(self) -> None:
        """Ждём, пока установщик закроется, и смотрим, что получилось."""
        if self._proc is None or self._proc.poll() is None:
            return
        self._watch.stop()
        from core.settings import toolkit_home
        if toolkit_home():
            # Установщик больше не нужен: 137 МБ в папке настроек — мусор,
            # а адрес постоянный, понадобится — скачаем снова.
            toolkit_setup.forget(self._path)
            self.installed.emit()
            self.accept()
            return
        self.note.setText(tr(
            "toolkit.not_found",
            "Установщик закрылся, а тулкит не нашёлся. Если установка была "
            "отменена — запустите её снова; если папку выбрали свою — укажите "
            "её в поле выше."))

    def reject(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        self._watch.stop()
        super().reject()
