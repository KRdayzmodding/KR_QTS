"""Окно обновления: что нового и что с этим делать.

Открывается только по желанию пользователя — из пункта в панели навигации.
Само не всплывает: человек мог запускать сервер в спешке, и модальное окно
поперёк этого было бы наглостью.
"""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QTextBrowser
from qfluentwidgets import (
    PushButton, PrimaryPushButton, BodyLabel, StrongBodyLabel, CaptionLabel,
    ProgressBar, FluentIcon as FIF, isDarkTheme,
)

from core.i18n import tr
from core.updater import Release
from core.version import VERSION
from ui.theme import ThemedDialog


def _size(n: int) -> str:
    return f"{n / 1024 / 1024:.0f} МБ" if n else ""


class UpdateDialog(ThemedDialog):
    """Описание релиза, кнопка загрузки и её ход.

    Окно не закрывается на время скачивания: прогресс виден здесь же, а если
    закрыть — загрузка продолжится, о готовности скажет пункт в навигации.
    """

    def __init__(self, rel: Release, downloading: bool = False,
                 ready: bool = False, parent=None):
        super().__init__(parent)
        self.rel = rel
        self.action = ""          # что выбрал пользователь: download | restart
        self.setWindowTitle(tr("upd.title", "Обновление"))
        self.resize(560, 520)

        layout = QVBoxLayout(self)
        layout.addWidget(StrongBodyLabel(
            tr("upd.head", "Версия {new}", new=rel.version)))
        layout.addWidget(CaptionLabel(
            tr("upd.current", "У вас установлена {cur}", cur=VERSION)))

        self.notes = QTextBrowser(self)
        self.notes.setOpenExternalLinks(True)
        self.notes.setMarkdown(rel.changelog or tr(
            "upd.no_notes", "Автор не оставил описания изменений."))
        # тёмный текст на светлой теме и наоборот — QTextBrowser своего фона
        # от qfluentwidgets не наследует
        bg, fg = ("#2b2b2b", "#d4d4d4") if isDarkTheme() else ("#ffffff", "#202020")
        self.notes.setStyleSheet(
            f"QTextBrowser{{background:{bg};color:{fg};border:1px solid #444;"
            f"border-radius:6px;padding:6px;}}")
        layout.addWidget(self.notes, 1)

        self.bar = ProgressBar(self)
        self.bar.setVisible(downloading)
        layout.addWidget(self.bar)
        self.status = CaptionLabel("")
        layout.addWidget(self.status)

        btns = QHBoxLayout()
        b_page = PushButton(FIF.LINK, tr("upd.page", "Страница релиза"))
        b_page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(rel.page)))
        b_page.setEnabled(bool(rel.page))
        b_later = PushButton(tr("upd.later", "Позже"))
        b_later.clicked.connect(self.reject)
        btns.addWidget(b_page)
        btns.addStretch(1)
        btns.addWidget(b_later)

        if ready:
            self.b_main = PrimaryPushButton(FIF.SYNC,
                                            tr("upd.restart", "Перезапустить и установить"))
            self.b_main.clicked.connect(lambda: self._choose("restart"))
        else:
            size = _size(rel.asset_size)
            text = (tr("upd.download_size", "Скачать ({s})", s=size) if size
                    else tr("upd.download", "Скачать"))
            self.b_main = PrimaryPushButton(FIF.DOWNLOAD, text)
            self.b_main.clicked.connect(lambda: self._choose("download"))
            # нечего качать — релиз без приложенного архива
            if not rel.downloadable:
                self.b_main.setEnabled(False)
                self.status.setText(tr("upd.no_asset",
                                       "К релизу не приложен файл сборки — "
                                       "скачайте со страницы релиза."))
        self.b_main.setEnabled(self.b_main.isEnabled() and not downloading)
        btns.addWidget(self.b_main)
        layout.addLayout(btns)

        if downloading:
            self.status.setText(tr("upd.downloading", "Скачивание…"))

    def _choose(self, what: str) -> None:
        self.action = what
        self.accept()

    def set_progress(self, got: int, total: int) -> None:
        self.bar.setVisible(True)
        self.b_main.setEnabled(False)
        if total:
            self.bar.setValue(int(got * 100 / total))
        self.status.setText(tr("upd.progress", "Скачано {a} из {b}",
                               a=_size(got), b=_size(total)))


class RestartDialog(ThemedDialog):
    """Обновление скачано — предложение перезапуститься."""

    def __init__(self, rel: Release, parent=None):
        super().__init__(parent)
        self.restart_now = False
        self.setWindowTitle(tr("upd.ready_title", "Обновление готово"))
        self.resize(420, 170)
        layout = QVBoxLayout(self)
        layout.addWidget(StrongBodyLabel(
            tr("upd.ready_head", "Версия {v} скачана", v=rel.version)))
        note = BodyLabel(tr("upd.ready_body",
                            "Файлы приложения будут заменены при перезапуске. "
                            "Запущенные сервер и клиент это не затронет."))
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        b_later = PushButton(tr("upd.later", "Позже"))
        b_later.clicked.connect(self.reject)
        b_now = PrimaryPushButton(FIF.SYNC, tr("upd.restart_now", "Перезапустить сейчас"))
        b_now.clicked.connect(self._now)
        btns.addWidget(b_later)
        btns.addWidget(b_now)
        layout.addLayout(btns)

    def _now(self) -> None:
        self.restart_now = True
        self.accept()
