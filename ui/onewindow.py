"""Одно окно на одно дело: повторный вызов поднимает открытое, а не плодит.

Немодальные окна — скачивание шаблона, копирование миссии, чужие настройки —
открываются по кнопке, и ничто не мешает нажать её дважды. Второе окно делает
ту же работу над теми же файлами: в лучшем случае человек путается, в худшем
две копии пишут в одну папку.

Модальных диалогов это не касается: пока такой открыт, до кнопки не добраться.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

_user32 = ctypes.windll.user32

_SW_RESTORE = 9
_GW_OWNER = 4


def show_once(owner, key: str, make):
    """Показывает окно, а если оно уже открыто — поднимает его.

    owner — объект, который держит список (страница, панель); key — что это
    за окно (обычно путь, над которым оно работает). make вызывается только
    когда окна ещё нет.
    """
    live = getattr(owner, "_one_windows", None)
    if live is None:
        live = {}
        owner._one_windows = live
    window = live.get(key)
    if window is not None and _usable(window):
        window.show()
        window.raise_()
        window.activateWindow()
        return window
    window = make()
    live[key] = window
    # Выбрасываем из списка сами: закрытое окно Qt удаляет не сразу, а
    # обращение к удалённому роняет программу насмерть.
    window.destroyed.connect(lambda *_a, k=key: live.pop(k, None))
    window.show()
    window.raise_()
    return window


def _usable(window) -> bool:
    """Годится ли показать это окно снова.

    Закрытое окно — ушедшее: человек его закрыл, и следующее нажатие кнопки
    означает «сделай заново», а не «покажи мне ту же законченную работу».
    Свёрнутое при этом остаётся своим — его мы поднимем.

    Удалённый в C++ виджет отвечает на любой вопрос исключением, а не False.
    """
    try:
        return bool(window.isVisible())
    except RuntimeError:
        return False


def raise_process_window(pid: int) -> bool:
    """Поднимает окно чужой программы по её pid. False — окна не нашли.

    Нужно для кнопок, которые открывают чужое приложение: нажатая второй раз,
    такая кнопка должна показать уже открытое окно, а не запустить вторую
    копию. Окно ищем перебором верхнеуровневых: своего способа спросить у
    чужого процесса «где твоё окно» в Windows нет.
    """
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _param):
        owner = ctypes.c_uint32()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if (owner.value == pid and _user32.IsWindowVisible(hwnd)
                and not _user32.GetWindow(hwnd, _GW_OWNER)):
            found.append(hwnd)
            return False        # первого видимого достаточно
        return True

    try:
        _user32.EnumWindows(visit, 0)
    except OSError:
        return False
    if not found:
        return False
    hwnd = found[0]
    _user32.ShowWindow(hwnd, _SW_RESTORE)
    _user32.SetForegroundWindow(hwnd)
    return True
