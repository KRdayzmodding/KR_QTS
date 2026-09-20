"""Ручка изменения высоты: тянешь вниз — виджет над ней становится выше.

Списки в карточках живут в прокручиваемой странице, поэтому «растянуть до
конца окна» им не годится: страница просто станет длиннее. А видеть хочется
больше шести строк сразу. Ручка решает это ровно так, как решают текстовые
поля в браузере: взял за нижний край и потянул.

Высоту запоминает тот, кто ручку поставил, — она относится к списку, а не к
самой ручке.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from ui import tokens

HEIGHT = 10             # полоска, за которую берутся
_DOTS = 3               # столько точек-насечек, как принято у ручек


class Resizer(QWidget):
    """Полоска под виджетом: тянет его высоту мышью.

    Двойной щелчок возвращает высоту по умолчанию: подобрать её обратно
    вручную тяжелее, чем испортить.
    """

    resized = Signal(int)       # новая высота — кому её сохранять

    def __init__(self, target: QWidget, default: int, minimum: int = 120,
                 maximum: int = 2000, parent=None):
        super().__init__(parent)
        self.target = target
        self.default = default
        self.minimum = minimum
        self.maximum = maximum
        self._from = QPoint()
        self._start_h = 0
        self.setFixedHeight(HEIGHT)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip(tr_hint())

    # ------------------------------------------------------------- рисование

    def paintEvent(self, e):        # имя метода задаёт Qt
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(tokens.color("divider"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        mid = self.height() / 2
        step = 6
        x0 = self.width() / 2 - step * (_DOTS - 1) / 2
        for i in range(_DOTS):
            p.drawEllipse(QPoint(int(x0 + i * step), int(mid)), 1, 1)

    # --------------------------------------------------------------- перетаскивание

    def mousePressEvent(self, e):   # имя метода задаёт Qt
        self._from = e.globalPosition().toPoint()
        self._start_h = self.target.height()

    def mouseMoveEvent(self, e):    # имя метода задаёт Qt
        if self._from.isNull():
            return
        delta = e.globalPosition().toPoint().y() - self._from.y()
        self._apply(self._start_h + delta)

    def mouseReleaseEvent(self, e):  # имя метода задаёт Qt
        self._from = QPoint()
        self.resized.emit(self.target.height())

    def mouseDoubleClickEvent(self, e):     # имя метода задаёт Qt
        self._apply(self.default)
        self.resized.emit(self.target.height())

    def _apply(self, height: int) -> None:
        self.target.setFixedHeight(max(self.minimum, min(self.maximum, height)))


def tr_hint() -> str:
    from core.i18n import tr
    return tr("common.resize_hint",
              "Потяните, чтобы изменить высоту. Двойной щелчок — вернуть как было")
