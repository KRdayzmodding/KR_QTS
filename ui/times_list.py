"""Список времён перезапуска: выбор времени, «Добавить» и сами времена кнопками.

Раньше это было свободное текстовое поле: человек писал «1, 2, 5», а понято
ли это как часы, было видно только по подсказке снизу. Здесь угадывать
нечего — время выбирается часами, запись добавляется кнопкой.

Времена показаны рядами по шесть, а не столбцом: расписание на пять-шесть
записей столбцом растягивало окно вниз и читалось хуже, чем те же числа в
одну строку. Нажатие по времени убирает его — добавить обратно стоит одного
клика, так что дешевле, чем отдельная кнопка удаления и выделение.

Записи всегда отсортированы по возрастанию и не повторяются: расписание
читают глазами, и «05:00, 01:00, 05:00» — лишняя работа для читателя.
"""
from __future__ import annotations

from PySide6.QtCore import QTime, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, FluentIcon as FIF, PushButton, TimePicker

from core.i18n import tr
from core.watchdog import format_times, parse_times

# Сколько времён помещается в ряд. Шесть — это «каждые четыре часа» одной
# строкой, самый частый случай; дальше ряды добавляются сами.
PER_ROW = 6


class TimesList(QWidget):
    """Времена перезапуска: часы и «Добавить» сверху, сами времена — кнопками."""

    changed = Signal()

    def __init__(self, times: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._times: list[int] = []
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.picker = TimePicker()
        self.picker.setTime(QTime(4, 0))
        self.b_add = PushButton(FIF.ADD, tr("times.add", "Добавить"))
        self.b_add.clicked.connect(self._add)
        top.addWidget(self.picker)
        top.addWidget(self.b_add)
        top.addStretch(1)
        col.addLayout(top)

        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(4)
        col.addLayout(self.grid)

        self.empty = CaptionLabel(tr("times.empty", "Времена не заданы"))
        self.empty.setMinimumWidth(1)
        col.addWidget(self.empty)

        self.set_values(times)

    # --------------------------------------------------------------- данные

    def minutes(self) -> list[int]:
        """Времена в минутах от полуночи, по возрастанию."""
        return list(self._times)

    def text(self) -> str:
        """Строка для пресета: «01:00, 05:00»."""
        return format_times(self._times)

    def set_values(self, times: str) -> None:
        self._times = parse_times(times)
        self._rebuild()

    # ------------------------------------------------------------ отрисовка

    def _rebuild(self) -> None:
        """Перекладывает кнопки: шесть в ряд, рядов сколько нужно."""
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for i, minutes in enumerate(self._times):
            self.grid.addWidget(self._chip(minutes), i // PER_ROW, i % PER_ROW)
        # пустые столбцы в последнем ряду прижимаем влево, иначе кнопки
        # растянутся по всей ширине и ряд перестанет читаться рядом
        self.grid.setColumnStretch(PER_ROW, 1)
        self.empty.setVisible(not self._times)

    def _chip(self, minutes: int) -> PushButton:
        text = f"{minutes // 60:02d}:{minutes % 60:02d}"
        b = PushButton(text)
        # Ширина под «00:00» с запасом, не больше: шесть кнопок в ряд должны
        # умещаться в окно вместе с подписью поля слева.
        b.setFixedWidth(64)
        b.setToolTip(tr("times.remove_tip", "Убрать {t} из расписания", t=text))
        b.clicked.connect(lambda _checked=False, m=minutes: self._remove(m))
        return b

    # -------------------------------------------------------------- правки

    def _add(self) -> None:
        t = self.picker.getTime()
        value = t.hour() * 60 + t.minute()
        if value in self._times:
            return      # повтор молча пропускаем: время уже стоит в расписании
        self._times = sorted(self._times + [value])
        self._rebuild()
        self.changed.emit()

    def _remove(self, minutes: int) -> None:
        if minutes not in self._times:
            return
        self._times = [t for t in self._times if t != minutes]
        self._rebuild()
        self.changed.emit()
