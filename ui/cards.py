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
FREE = 16777215                         # «потолка нет» на языке Qt


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
        # Двигаем высоту самой карточки, а не её содержимого. Пока анимировали
        # тело, карточка узнавала о его новом размере следующим проходом
        # раскладки — и на кадр отставала: тело уже ужалось, рамка ещё нет, а
        # потом проваливалась сразу на восемьдесят пикселей. Со стороны это
        # выглядело как дёрганье по вертикали и «что-то заезжает под шапку».
        self._ani = QPropertyAnimation(self, b"maximumHeight", self)
        self._ani.setDuration(DURATION_MS)
        self._ani.setEasingCurve(QEasingCurve.Type.OutQuad)
        # Подключаемся один раз: перецепление обработчика на каждый щелчок
        # заставляло Qt ругаться на отключение несуществующей связи.
        self._ani.finished.connect(self._after)
        # Раскладка страницы пересчитывается в том же кадре, что и высота
        # карточки. Без этого соседи узнают о новом размере следующим проходом
        # и на кадр отстают — карточка уже уехала, журнал под ней ещё нет.
        self._ani.valueChanged.connect(self._relayout)

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
        self._ani.stop()
        shut = self.head.sizeHint().height()
        if open_:
            self.body.setVisible(True)
            # Целевую высоту меряем при снятом потолке: под потолком подсказка
            # размера врёт, и анимация доезжала не туда.
            self.setMaximumHeight(FREE)
            full = self.sizeHint().height()
            self.setMaximumHeight(self.height())
            self._ani.setStartValue(shut)
            self._ani.setEndValue(full)
        else:
            self._ani.setStartValue(self.height())
            self._ani.setEndValue(shut)
        self._ani.start()

    def _relayout(self, *_a) -> None:
        parent = self.parentWidget()
        box = parent.layout() if parent is not None else None
        if box is not None:
            box.activate()

    def _after(self) -> None:
        """После анимации снимаем потолок высоты и прячем свёрнутое.

        Потолок нужен только на время движения: оставленный навсегда, он
        обрезал бы содержимое, если текст в строке станет длиннее.
        """
        if not self._open:
            # Свёрнутое тело прячем совсем, иначе от него остаётся полоска.
            self.body.setVisible(False)
        # Потолок снимаем в обоих случаях: свёрнутую высоту задаёт шапка, а
        # раскрытую — содержимое, и оставленный потолок обрезал бы его, когда
        # строки перестроятся в одну колонку.
        self.setMaximumHeight(FREE)


def rows_card(icon, title: str, summary: str, rows: list[QWidget]) -> Section:
    card = Section(icon, title, rows)
    card.set_summary(summary)
    return card
