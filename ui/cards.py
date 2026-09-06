"""Сворачиваемая карточка с итогом в шапке.

Своя, а не `ExpandGroupSettingCard` из библиотеки: та считает высоту
содержимого по своим меркам — её строки одинаковой высоты, а у нас в строке
два-три ряда текста. Из-за расхождения под содержимым оставалась пустая полоса
и в раскрытом, и в свёрнутом виде.

Свёрнутая шапка обязана показывать итог: «модов: 3», «Выключена — правки не
попадут в игру». Иначе сворачивание прячет состояние, и человек запускает
сервер, не зная, что запаковка выключена.

Выведено из прототипа (tools/mockup.py) после того, как форма устоялась.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CardWidget, IconWidget, StrongBodyLabel, TransparentToolButton,
    FluentIcon as FIF,
)

from ui import tokens
from ui.rows import shrink
from qfluentwidgets import CaptionLabel

DURATION_MS = 180                       # шкала движения из docs/UX.md, раздел 10


class Section(CardWidget):
    """Карточка с шапкой, итогом и сворачиваемым содержимым."""

    def __init__(self, icon, title: str, rows: list[QWidget], parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        self.head = QWidget(self)
        self.head.setCursor(Qt.CursorShape.PointingHandCursor)
        hrow = QHBoxLayout(self.head)
        hrow.setContentsMargins(tokens.SPACE_M, tokens.SPACE_S,
                                tokens.SPACE_M, tokens.SPACE_S)
        hrow.setSpacing(tokens.SPACE_S)
        ic = IconWidget(icon, self.head)
        ic.setFixedSize(18, 18)
        hrow.addWidget(ic)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(StrongBodyLabel(title))
        self.summary = shrink(CaptionLabel(""))
        text.addWidget(self.summary)
        hrow.addLayout(text, 1)
        self.chevron = TransparentToolButton(FIF.CHEVRON_DOWN_MED)
        self.chevron.setFixedSize(24, 24)
        self.chevron.clicked.connect(self.toggle)
        hrow.addWidget(self.chevron)
        col.addWidget(self.head)
        self.head.mousePressEvent = lambda _e: self.toggle()

        self.body = QWidget(self)
        brow = QVBoxLayout(self.body)
        brow.setContentsMargins(tokens.SPACE_M, 0, tokens.SPACE_M, tokens.SPACE_S)
        brow.setSpacing(tokens.SPACE_XS)
        for r in rows:
            brow.addWidget(r)
        col.addWidget(self.body)

        self._open = True
        self._ani = QPropertyAnimation(self.body, b"maximumHeight", self)
        self._ani.setDuration(DURATION_MS)
        self._ani.setEasingCurve(QEasingCurve.Type.OutQuad)
        # Подключаемся один раз: перецепление обработчика на каждый щелчок
        # заставляло Qt ругаться на отключение несуществующей связи.
        self._ani.finished.connect(self._after)

    # ------------------------------------------------------------- состояние

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)
        self.summary.setVisible(bool(text))

    def is_open(self) -> bool:
        return self._open

    def toggle(self) -> None:
        self.set_open(not self._open)

    def set_open(self, open_: bool) -> None:
        if open_ == self._open:
            return
        self._open = open_
        self.chevron.setIcon(FIF.CHEVRON_DOWN_MED if open_ else FIF.CHEVRON_RIGHT_MED)
        height = self.body.sizeHint().height()
        self._ani.stop()
        if open_:
            self.body.setVisible(True)
            self._ani.setStartValue(0)
            self._ani.setEndValue(height)
        else:
            self._ani.setStartValue(self.body.height() or height)
            self._ani.setEndValue(0)
        self._ani.start()

    def _after(self) -> None:
        """После анимации снимаем потолок высоты и прячем свёрнутое.

        Потолок нужен только на время движения: оставленный навсегда, он
        обрезал бы содержимое, если текст в строке станет длиннее.
        """
        if self._open:
            self.body.setMaximumHeight(16777215)
        else:
            self.body.setVisible(False)


def rows_card(icon, title: str, summary: str, rows: list[QWidget]) -> Section:
    card = Section(icon, title, rows)
    card.set_summary(summary)
    return card
