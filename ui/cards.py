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

from PySide6.QtCore import (QEasingCurve, QPropertyAnimation, Qt, QTimer,
                            Signal)
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CardWidget, IconWidget, StrongBodyLabel, TransparentToolButton,
    FluentIcon as FIF,
)

from ui import tokens
from ui.rows import shrink
from qfluentwidgets import CaptionLabel

DURATION_MS = 180                       # шкала движения из docs/UX.md, раздел 10
DURATION_LONG_MS = 250                  # длинный ход: карточка в тысячу пикселей
_CHASE_LIMIT = 3                        # сколько раз догонять подросшее содержимое
_CHASE_EPS = 8                          # разница, которой можно пренебречь
FREE = 16777215                         # «потолка нет» на языке Qt


class Section(CardWidget):
    """Карточка с шапкой, итогом и сворачиваемым содержимым."""

    # Раскрыли. Нужен тем, кто строит содержимое по требованию: свёрнутое тело
    # для Qt всё равно «показано», и на событие показа полагаться нельзя.
    opened = Signal()

    def __init__(self, icon, title: str, rows: list[QWidget], parent=None):
        super().__init__(parent)
        # Метка для правила колеса: докручивая страницу вверх ради списка
        # внутри карточки, доезжать надо до её шапки, а не до верха списка —
        # иначе кнопка «свернуть» так и остаётся за краем. См. ui/nowheel.
        self.setProperty("wheelAnchor", True)
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
        self._chase = 0         # догоняний подряд, см. _catch_up
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
        if open_:
            self.opened.emit()      # содержимое могло ждать этого, чтобы собраться
        self.chevron.setIcon(FIF.CHEVRON_DOWN_MED if open_ else FIF.CHEVRON_RIGHT_MED)
        self._ani.stop()
        shut = self._shut()
        if open_:
            # Высоту раскрытой карточки нельзя ни предсказать, ни получить
            # на месте. Подсказка размера врёт, и крупно: в «Настройках
            # сервера» строки перестраиваются в колонки по ширине, и sizeHint
            # обещал 1098 px против настоящих 4103 — анимация доезжала до
            # обещанного, а потом карточка допрыгивала на три тысячи. Спросить
            # раскладку прямо здесь тоже нельзя: карточка лежит в области
            # прокрутки, и настоящий размер она получает только следующим
            # проходом цикла событий.
            #
            # Поэтому снимаем потолок и ждём один проход, погасив на это время
            # отрисовку окна: раскладка успевает посчитать правду, а на экран
            # промежуточное состояние не попадает. Один кадр задержки глазом
            # не виден, зато ход начинается и кончается там, где должен.
            self.body.setVisible(True)
            self.setMaximumHeight(FREE)
            window = self.window()
            if window is not None:
                window.setUpdatesEnabled(False)
            QTimer.singleShot(0, self._begin_open)
            return
        self._set_range(self.height(), shut)
        self._run()

    def _begin_open(self) -> None:
        """Второй шаг раскрытия: высота уже посчитана, можно ехать."""
        window = self.window()
        try:
            if not self._open:
                return              # успели свернуть обратно
            self._set_range(self._shut(), self.height())
            self._run()
        finally:
            if window is not None:
                window.setUpdatesEnabled(True)

    def _run(self) -> None:
        """Пускает ход, выбрав длительность по расстоянию.

        Шкала 120/180/250 из docs/UX.md, п.10. Карточка модов едет больше
        тысячи пикселей, и за 180 мс это одиннадцать кадров по сто — глаз
        читает их как прыжки, а не как движение. Короткому ходу лишние
        миллисекунды, наоборот, вредят.
        """
        distance = abs(self._ani.endValue() - self._ani.startValue())
        self._ani.setDuration(DURATION_MS if distance < 400 else DURATION_LONG_MS)
        self._ani.start()

    def _shut(self) -> int:
        """Высота свёрнутой карточки — настоящая, а не обещанная.

        Подсказка размера шапки больше реальной на 16–32 px: в ней заложен
        полный текст итога, который на экране укорочен. Ход заканчивался на
        обещанной высоте, и карточка потом оседала на эти пикселы — мелко, но
        заметно, потому что оседала рывком.
        """
        return self.head.height() or self.head.sizeHint().height()

    def _set_range(self, start: int, end: int) -> None:
        """Задаёт пределы анимации, не трогая само свойство.

        У остановленной анимации setEndValue пересчитывает текущее значение и
        тут же пишет его в свойство: карточка на мгновение получала полную
        высоту, страница раскладывалась под неё, и только потом начинался ход
        от шапки. Замерено по valueChanged: первым приходило 1235 px, вторым —
        75 px.
        """
        self._ani.blockSignals(True)
        try:
            self._ani.setStartValue(start)
            self._ani.setEndValue(end)
        finally:
            self._ani.blockSignals(False)
        self.setMaximumHeight(start)

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
            self._chase = 0
        # Потолок снимаем в обоих случаях: свёрнутую высоту задаёт шапка, а
        # раскрытую — содержимое, и оставленный потолок обрезал бы его, когда
        # строки перестроятся в одну колонку.
        self.setMaximumHeight(FREE)
        if self._open:
            # Через проход цикла: раскладка досчитывает высоту не сразу, и
            # спрошенная в тот же миг она равна той, на которой мы встали —
            # догонять было бы нечего, а карточка потом всё равно подрастала.
            QTimer.singleShot(0, self._catch_up)

    def _catch_up(self) -> None:
        """Доезжает, если содержимое оказалось выше, чем было в начале хода.

        У «Настроек сервера» раскладка досчитывает высоту не за один проход, а
        за пять: 155 → 1018 → 1070 → 4103 (замерено). Предсказать итог нельзя
        ничем — ни подсказкой размера, ни одним проходом цикла. Поэтому после
        хода сверяемся с тем, что получилось, и недостающее доезжаем тем же
        движением, а не отдаём скачком на три тысячи пикселей.

        Догоняем не бесконечно: три раза, дальше остаток уже мелкий.
        """
        self._relayout()
        target = self.height()
        done = int(self._ani.endValue())
        if self._chase >= _CHASE_LIMIT or abs(target - done) <= _CHASE_EPS:
            self._chase = 0
            return
        self._chase += 1
        self._set_range(done, target)
        self._run()


def rows_card(icon, title: str, summary: str, rows: list[QWidget]) -> Section:
    card = Section(icon, title, rows)
    card.set_summary(summary)
    return card
