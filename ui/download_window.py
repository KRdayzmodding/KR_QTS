"""Неблокирующее окно загрузки миссии: прогресс, скачанный объём, таймер."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import (
    ProgressBar, IndeterminateProgressBar, PushButton, StrongBodyLabel,
    BodyLabel, CaptionLabel,
)

from core.downloader import MissionDownloadWorker
from core.i18n import tr
from core.missions import CatalogEntry


def _fmt_size(n: int) -> str:
    mb = n / (1024 * 1024)
    return f"{mb:.1f} МБ" if mb < 1024 else f"{mb / 1024:.2f} ГБ"


def _fmt_time(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


class DownloadWindow(QWidget):
    """Самостоятельное окно; закрывать его не обязательно — загрузка идёт в потоке."""
    finished_ok = Signal(str)  # путь установленной миссии

    def __init__(self, entry: CatalogEntry, target_dir: Path, target_name: str,
                 replace: bool = False, keep_storage: bool = True):
        super().__init__(None, Qt.Window)
        self.setWindowTitle(tr("dl.title", "Загрузка миссии: {n}", n=target_name))
        self.resize(460, 180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.addWidget(StrongBodyLabel(f"{entry.title}  →  {target_name}"))
        self.status = BodyLabel(tr("dl.starting", "Подготовка…"))
        layout.addWidget(self.status)

        self.bar_unknown = IndeterminateProgressBar()
        self.bar_known = ProgressBar()
        self.bar_known.hide()
        layout.addWidget(self.bar_unknown)
        layout.addWidget(self.bar_known)

        row = QHBoxLayout()
        self.stats = CaptionLabel("")
        self.btn_cancel = PushButton(tr("dl.cancel", "Отмена"))
        self.btn_cancel.clicked.connect(self._cancel)
        row.addWidget(self.stats, 1)
        row.addWidget(self.btn_cancel)
        layout.addLayout(row)

        self.worker = MissionDownloadWorker(entry, target_dir, target_name,
                                            replace=replace, keep_storage=keep_storage)
        self.worker.status.connect(self.status.setText)
        self.worker.progress.connect(self._progress)
        self.worker.done.connect(self._done)
        self.bar_unknown.start()
        self.worker.start()

    def _progress(self, got: int, total: int, elapsed: float) -> None:
        speed = got / elapsed / (1024 * 1024) if elapsed > 0 else 0
        if total > 0:
            if self.bar_known.isHidden():
                self.bar_unknown.hide()
                self.bar_known.show()
            self.bar_known.setValue(int(got * 100 / total))
            self.stats.setText(tr("dl.stats_total",
                                  "{got} из {total}   •   {spd:.1f} МБ/с   •   {t}",
                                  got=_fmt_size(got), total=_fmt_size(total),
                                  spd=speed, t=_fmt_time(elapsed)))
        else:
            self.stats.setText(tr("dl.stats",
                                  "Скачано {got}   •   {spd:.1f} МБ/с   •   {t}",
                                  got=_fmt_size(got), spd=speed, t=_fmt_time(elapsed)))

    def _done(self, ok: bool, result: str) -> None:
        self.bar_unknown.stop()
        self.bar_unknown.hide()
        self.bar_known.show()
        if ok:
            self.bar_known.setValue(100)
            self.status.setText(tr("dl.done", "Готово: {p}", p=result))
            self.finished_ok.emit(result)
        else:
            self.bar_known.error()
            self.status.setText(result)
        self.btn_cancel.setText(tr("dl.close", "Закрыть"))
        self.btn_cancel.clicked.disconnect()
        self.btn_cancel.clicked.connect(self.close)

    def _cancel(self) -> None:
        if self.worker.isRunning():
            self.worker.cancel()
            self.status.setText(tr("dl.cancelling", "Отмена…"))
        else:
            self.close()

    def closeEvent(self, event) -> None:  # noqa: N802 — API Qt
        if self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        event.accept()
