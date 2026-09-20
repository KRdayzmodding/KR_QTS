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

from PySide6.QtCore import QEvent, QObject
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


class ChainGuard(QObject):
    """Не даёт колесу перескочить с упёршегося списка на страницу под ним.

    Перехватываем не у списка, а у страницы: к ней событие приходит уже
    после того, как список отказался его брать. Если курсор стоит над
    вложенной областью, которой есть куда листать, — значит она просто
    упёрлась в край, и страница здесь ни при чём.
    """

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.Wheel:
            return False
        page = _area_of_viewport(obj)
        if page is None:
            return False
        inner = _inner_area_under(event, page)
        return inner is not None


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
