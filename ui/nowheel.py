"""Колесо мыши листает страницу, а не правит числа под курсором.

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


def _scroll_area(widget: QObject) -> QAbstractScrollArea | None:
    """Ближайшая прокручиваемая область выше по дереву. None — её нет."""
    parent = widget.parentWidget() if hasattr(widget, "parentWidget") else None
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea):
            return parent
        parent = parent.parentWidget()
    return None


_guard: WheelGuard | None = None


def install(app: QApplication) -> WheelGuard:
    """Ставит правило на всё приложение. Возвращённый объект надо держать живым."""
    global _guard
    if _guard is None:
        _guard = WheelGuard()
        app.installEventFilter(_guard)
    return _guard
