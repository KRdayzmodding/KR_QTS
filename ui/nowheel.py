"""Правила колеса мыши: что листается и что не листается.

Первое: колесо листает страницу, а не правит числа под курсором.
Второе: список, докрутившийся до края, не передаёт колесо странице под собой.


Поля с числами по умолчанию перехватывают колесо и меняют значение. В длинных
окнах — настройках, редакторе пресета — это ловушка: человек листает список,
курсор проезжает над полем, и порт или интервал перезапуска тихо меняются. Тем
более что менялись бы они молча: ни подтверждения, ни следа.

Поэтому колесо у таких полей отбираем и отдаём наверх, тому, кто листает.
Фильтр ставится один раз на всё приложение: так под правило попадают и поля,
которые появятся позже, и не нужно помнить про него в каждом окне.

С клавиатуры значения по-прежнему меняются стрелками, и стрелочки самого поля
никуда не делись.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint
from PySide6.QtWidgets import QAbstractScrollArea, QAbstractSpinBox, QApplication


class WheelGuard(QObject):
    """Съедает колесо у числовых полей и отдаёт его области прокрутки."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.Wheel or not isinstance(obj, QAbstractSpinBox):
            return False
        # Просто «не принять» событие мало: обычное всплытие к родителю
        # работает лишь на первой доставке, а мы её как раз и перехватили.
        # Поэтому ищем ближайшую прокручиваемую область и отдаём колесо ей
        # напрямую — в её viewport, потому что именно он листает содержимое.
        area = _scroll_area(obj)
        if area is not None:
            QApplication.sendEvent(area.viewport(), event)
        return True


# Шаг колеса: столько проезжает страница за один щелчок, когда ведёт край
# карточки к экрану. Примерно как обычный шаг колеса в Windows.
_STEP = 110


class ChainGuard(QObject):
    """Колесо над списком: страница подхватывает движение, но не убегает.

    Правило одно на два случая.

    Список ещё не докручен, но до края ему осталось меньше щелчка — остаток
    отдаём списку, а хвост щелчка уже уходит странице. Без этого страница
    трогалась ровно в тот миг, когда список упёрся, и это читалось как рывок.

    Список докручен — страница едет дальше, но ровно до края карточки, в
    которой он лежит: вверх до шапки (там кнопка сворачивания), вниз до низа
    (там ручка размера и подсказка). Дошли — стоим: рука делает одно движение,
    и уносить её в другое место нечестно.
    """

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.Wheel:
            return False
        area = _area_of_viewport(obj)
        if area is None:
            return False
        page = _outer_area(area)
        if page is not None:
            return self._hand_off(area, page, event)     # колесо пришло списку
        inner = _inner_area_under(event, area)
        if inner is None:
            return False        # курсор не над списком — страница едет как обычно
        self._move_page(area, inner, event, _STEP)
        return True

    # ----------------------------------------------------------------- шаги

    def _hand_off(self, inner, page, event) -> bool:
        """Остаток хода списка отдаём ему, хвост щелчка — странице."""
        down = event.angleDelta().y() < 0
        bar = inner.verticalScrollBar()
        left = (bar.maximum() - bar.value()) if down else bar.value()
        if left >= _STEP:
            return False        # списку есть куда ехать — не вмешиваемся
        if left:
            bar.setValue(bar.maximum() if down else 0)
        self._move_page(page, inner, event, _STEP - left)
        return True

    def _move_page(self, page, inner, event, step: int) -> None:
        """Двигает страницу к нужному краю карточки, но не дальше него."""
        if step <= 0:
            return
        down = event.angleDelta().y() < 0
        anchor = _anchor_of(inner, page)
        top = anchor.mapTo(page.viewport(), QPoint(0, 0)).y()
        hidden = (top + anchor.height() - page.viewport().height()) if down else -top
        if hidden <= 0:
            return
        bar = page.verticalScrollBar()
        move = min(hidden, step)
        bar.setValue(bar.value() + (move if down else -move))


def _outer_area(area: QAbstractScrollArea):
    """Область прокрутки, внутри которой лежит эта. None — она и есть внешняя."""
    node = area.parentWidget()
    while node is not None:
        if isinstance(node, QAbstractScrollArea):
            return node
        node = node.parentWidget()
    return None


def _anchor_of(widget, page: QAbstractScrollArea):
    """Карточка, в которой лежит список. Нет такой — сам список."""
    node = widget
    while node is not None and node is not page.widget():
        if node.property("wheelAnchor"):
            return node
        node = node.parentWidget()
    return widget


def _area_of_viewport(obj: QObject) -> QAbstractScrollArea | None:
    """Область прокрутки, чей это viewport. None — это не viewport."""
    parent = obj.parentWidget() if hasattr(obj, "parentWidget") else None
    if isinstance(parent, QAbstractScrollArea) and parent.viewport() is obj:
        return parent
    return None


def _inner_area_under(event, page: QAbstractScrollArea) -> QAbstractScrollArea | None:
    """Вложенная в page область под курсором, которой есть что листать.

    Ищем по дереву виджетов, а не через widgetAt: тот смотрит на экран и
    порядок окон, то есть отвечает по-разному в зависимости от того, что
    сейчас поверх, а нам нужен ответ про содержимое страницы.
    """
    widget = page.viewport().childAt(event.position().toPoint())
    while widget is not None and widget is not page:
        if (isinstance(widget, QAbstractScrollArea)
                and widget.verticalScrollBar().maximum() > 0):
            return widget
        widget = widget.parentWidget()
    return None


def _scroll_area(widget: QObject) -> QAbstractScrollArea | None:
    """Ближайшая прокручиваемая область выше по дереву. None — её нет."""
    parent = widget.parentWidget() if hasattr(widget, "parentWidget") else None
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea):
            return parent
        parent = parent.parentWidget()
    return None


_guard: WheelGuard | None = None
_chain: ChainGuard | None = None


def install(app: QApplication) -> WheelGuard:
    """Ставит правило на всё приложение. Возвращённый объект надо держать живым."""
    global _guard, _chain
    if _guard is None:
        _guard = WheelGuard()
        app.installEventFilter(_guard)
    if _chain is None:
        _chain = ChainGuard()
        app.installEventFilter(_chain)
    return _guard
