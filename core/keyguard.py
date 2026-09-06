"""Гасит синтетические нажатия Enter, которые pboProject шлёт в чужие окна.

pboProject.exe импортирует из USER32 функцию keybd_event и в конце сборки
жмёт ею Enter. Нажатие уходит не ему, а тому окну, которое сейчас в фокусе:
человек пакует мод, продолжает печатать в редакторе или мессенджере — и
недописанная строка отправляется сама. Проверено дважды: разбор таблицы
импорта pboProject.exe (keybd_event там есть) и низкоуровневый хук во время
реальной сборки — событие приходит с флагом LLKHF_INJECTED, код 13.

Чинить это в самом pboProject нельзя, поэтому ловим нажатие на подходе:
пока идёт запаковка, стоит хук WH_KEYBOARD_LL, и события Enter с признаком
«подставлено программой» до окон не доходят. Всё остальное — живые нажатия,
любые другие клавиши, любые нажатия вне запаковки — проходит как обычно.

Два уточнения по месту:

* Хук живёт на своём потоке с собственным циклом сообщений. Windows зовёт
  колбэк через очередь того потока, который его поставил; запаковка идёт в
  рабочем потоке, который сообщения не качает, а грузить этим GUI-поток
  значило бы тащить Qt в core.
* Хук снимается не сразу: замер показал, что Enter прилетает в район
  завершения процесса, ±0,2 с. Держим ещё LINGER_SEC, чтобы не разоружиться
  за мгновение до выстрела.

Ограничение: если окно в фокусе запущено от администратора, а сам QTS —
нет, Windows не пустит наш хук к этому окну (UIPI). Тогда Enter дойдёт;
лечится запуском QTS с теми же правами.
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

WH_KEYBOARD_LL = 13
WM_QUIT = 0x0012
_KEY_MESSAGES = (0x0100, 0x0101, 0x0104, 0x0105)   # KEYDOWN/KEYUP/SYSKEYDOWN/SYSKEYUP
LLKHF_INJECTED = 0x10
VK_RETURN = 0x0D

# Сколько держать хук после конца запаковки, секунды.
LINGER_SEC = 3.0

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


_HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int,
                               wintypes.WPARAM, wintypes.LPARAM)

# Типы обязательны: без них дескриптор хука обрезается до 32 бит и выглядит
# как отказ, хотя хук на самом деле стоит.
_user32.SetWindowsHookExW.restype = wintypes.HHOOK
_user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC,
                                      wintypes.HINSTANCE, wintypes.DWORD]
_user32.UnhookWindowsHookEx.restype = wintypes.BOOL
_user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
_user32.CallNextHookEx.restype = ctypes.c_long
_user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int,
                                   wintypes.WPARAM, wintypes.LPARAM]
_user32.GetMessageW.restype = ctypes.c_int
_user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                wintypes.UINT, wintypes.UINT]
_user32.PostThreadMessageW.restype = wintypes.BOOL
_user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]

_state = threading.Lock()
_depth = 0              # сколько запаковок сейчас держат хук
_thread: threading.Thread | None = None
_tid = 0                # поток хука, ему шлём WM_QUIT
_ready = threading.Event()
_free_at = 0.0          # с какого момента можно снимать хук
dropped = 0             # сколько подставленных Enter погашено — для диагностики


def _on_key(code: int, wparam: int, lparam: int) -> int:
    try:
        if code == 0 and wparam in _KEY_MESSAGES:
            data = ctypes.cast(lparam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
            if data.vkCode == VK_RETURN and data.flags & LLKHF_INJECTED:
                global dropped
                dropped += 1
                return 1        # дальше по цепочке и в окно не уйдёт
    except Exception:  # noqa: BLE001 — колбэк Windows не должен бросать
        pass                    # сбой разбора не должен глотать живые клавиши
    return _user32.CallNextHookEx(None, code, wparam, lparam)


def _loop() -> None:
    """Ставит хук и качает сообщения, пока не придёт WM_QUIT."""
    global _tid
    # ссылку на колбэк держим здесь: если её соберёт сборщик мусора, Windows
    # позовёт освобождённый код
    callback = _HOOKPROC(_on_key)
    hook = _user32.SetWindowsHookExW(WH_KEYBOARD_LL, callback, None, 0)
    _tid = _kernel32.GetCurrentThreadId()
    _ready.set()
    if not hook:
        return                  # без прав на хук просто работаем как раньше
    msg = wintypes.MSG()
    while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        pass                    # своих окон нет, разбирать нечего
    _user32.UnhookWindowsHookEx(hook)


def armed() -> bool:
    """Стоит ли хук прямо сейчас."""
    return _thread is not None and _thread.is_alive()


def arm() -> None:
    """Включает защиту. Вложенные вызовы считаются."""
    global _depth, _thread
    with _state:
        _depth += 1
        if _thread is not None and _thread.is_alive():
            return
        _ready.clear()
        _thread = threading.Thread(target=_loop, name="keyguard", daemon=True)
        _thread.start()
    _ready.wait(2.0)            # чтобы disarm сразу после arm нашёл поток


def disarm() -> None:
    """Выключает защиту — но не раньше, чем через LINGER_SEC."""
    global _depth, _free_at
    with _state:
        _depth = max(0, _depth - 1)
        if _depth:
            return
        _free_at = time.monotonic() + LINGER_SEC
    threading.Timer(LINGER_SEC, _release).start()


def _release() -> None:
    """Снимает хук, если за время ожидания не началась новая запаковка."""
    global _thread, _tid
    with _state:
        if _depth or time.monotonic() < _free_at:
            return              # успели вооружиться заново — хук остаётся
        thread, tid = _thread, _tid
        if thread is None or not tid:
            return
        _thread, _tid = None, 0
    _user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
    thread.join(2.0)
