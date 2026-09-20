"""Ручка изменения размера: тянешь — соседний блок становится больше.

Списки и панели живут внутри прокручиваемой страницы, поэтому «растянуть до
конца окна» им не годится: страница просто станет длиннее. А видеть хочется
больше шести строк сразу. Ручка решает это ровно так, как решают текстовые
поля в браузере: взял за край и потянул.

Горизонтальная тянет высоту того, что над ней; вертикальная — ширину того,
что слева. Размер запоминает тот, кто ручку поставил: он относится к блоку, а
не к самой ручке.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from ui import tokens

THICK = 18              # поперёк — столько места занимает полоска
_DOTS = 5               # насечки на подложке
_PILL = 76              # длина подложки под насечками
_PILL_T = 12            # её толщина


class Resizer(QWidget):
    """Полоска-ручка рядом с виджетом: тянет его размер мышью.

    Двойной щелчок возвращает размер по умолчанию: подобрать его обратно
    руками тяжелее, чем испортить.
    """

    resized = Signal(int)       # новый размер — кому его сохранять

    def __init__(self, target: QWidget, default: int, minimum: int = 120,
                 maximum: int = 2000, vertical: bool = False,
                 apply=None, parent=None):
        """vertical=True — ручка стоит сбоку и тянет ширину.

        apply — как применить размер, если мало просто задать его виджету
        (панель разделов, например, ещё и показывает подписи).
        """
        super().__init__(parent)
        self.target = target
        self.default = default
        self.minimum = minimum
        self.maximum = maximum
        self.vertical = vertical
        self._apply_cb = apply
        self._from = QPoint()
        self._start = 0
        self._hover = False
        if vertical:
            self.setFixedWidth(THICK)
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setFixedHeight(THICK)
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip(_hint())

    # ------------------------------------------------------------- рисование

    def paintEvent(self, e):        # имя метода задаёт Qt
        """Подложка-таблетка с насечками.

        Точки цветом линии на тёмной теме терялись: человек не видел, что за
        край можно взяться. Поэтому подложка заметная — цвет поля ввода с
        рамкой, как у кнопки, — а под мышью она ещё и подсвечивается.
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        thick = _PILL_T
        # Линия во всю длину: она и показывает, где именно проходит край, за
        # который берутся. Одна таблетка посреди пустоты читалась как значок
        # неизвестно чего.
        p.setPen(QColor(tokens.color("divider")))
        if self.vertical:
            p.drawLine(w // 2, 0, w // 2, h)
            pill = QRectF((w - thick) / 2, (h - _PILL) / 2, thick, _PILL)
        else:
            p.drawLine(0, h // 2, w, h // 2)
            pill = QRectF((w - _PILL) / 2, (h - thick) / 2, _PILL, thick)
        p.setBrush(QColor(tokens.color("border" if self._hover else "raised")))
        p.drawRoundedRect(pill, thick / 2, thick / 2)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(tokens.color("text" if self._hover else "text")))
        step = 7
        for i in range(_DOTS):
            shift = int(step * (i - (_DOTS - 1) / 2))
            if self.vertical:
                p.drawEllipse(QPoint(w // 2, h // 2 + shift), 1, 1)
            else:
                p.drawEllipse(QPoint(w // 2 + shift, h // 2), 1, 1)

    def enterEvent(self, e):        # имя метода задаёт Qt
        self._hover = True
        self.update()

    def leaveEvent(self, e):        # имя метода задаёт Qt
        self._hover = False
        self.update()

    # ----------------------------------------------------------- перетаскивание

    def _size(self) -> int:
        return self.target.width() if self.vertical else self.target.height()

    def mousePressEvent(self, e):   # имя метода задаёт Qt
        self._from = e.globalPosition().toPoint()
        self._start = self._size()

    def mouseMoveEvent(self, e):    # имя метода задаёт Qt
        if self._from.isNull():
            return
        now = e.globalPosition().toPoint()
        delta = (now.x() - self._from.x()) if self.vertical else (now.y() - self._from.y())
        self._apply(self._start + delta)

    def mouseReleaseEvent(self, e):  # имя метода задаёт Qt
        self._from = QPoint()
        self.resized.emit(self._size())

    def mouseDoubleClickEvent(self, e):     # имя метода задаёт Qt
        self._apply(self.default)
        self.resized.emit(self._size())

    def _apply(self, size: int) -> None:
        size = max(self.minimum, min(self.maximum, size))
        if self._apply_cb is not None:
            self._apply_cb(size)
        elif self.vertical:
            self.target.setFixedWidth(size)
        else:
            self.target.setFixedHeight(size)


def _hint() -> str:
    from core.i18n import tr
    return tr("common.resize_hint",
              "Потяните, чтобы изменить размер. Двойной щелчок — вернуть как было")
