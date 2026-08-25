"""Ярлык быстрого запуска пресета на рабочем столе.

Ярлык несёт только имя пресета: «KR_QTS.exe --launch <пресет>». Всё остальное
делает приложение, и это принципиально — запуск у нас не «дёрнуть exe с
аргументами», а десяток шагов подготовки: перепаковка изменённых модов,
junction-ссылки, права админок, время входа в миссии. Ярлык с готовой
командной строкой пропустил бы всё это, и сервер поднялся бы сломанным.

Ярлык создаётся напрямую через IShellLinkW — системный интерфейс Windows,
работающий с широкими строками. Прошлый способ, WScript.Shell через
PowerShell, оказался негодным: этот старый ANSI-механизм переводит имя файла
в кодовую страницу системы. На английской Windows русские буквы превращались
в «?», а «?» в имени файла запрещён — ярлык не создавался вовсе. Проверено:
имя «Ünïcode 日本語 кот» файловая система принимает, а WScript.Shell на нём
падает.

Заодно исчез запуск postороннего процесса: PowerShell для одного ярлыка
поднимался почти секунду.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import POINTER, byref, c_void_p, wintypes
from pathlib import Path

# Символы, которые нельзя ставить в имя файла Windows.
_BAD = '<>:"/\\|?*'

_CLSID_SHELL_LINK = "{00021401-0000-0000-C000-000000000046}"
_IID_SHELL_LINK_W = "{000214F9-0000-0000-C000-000000000046}"
_IID_PERSIST_FILE = "{0000010B-0000-0000-C000-000000000046}"
_CLSCTX_INPROC_SERVER = 1

# Номера методов в таблице интерфейса. Первые три у любого COM-интерфейса —
# QueryInterface, AddRef, Release, поэтому свои методы начинаются с третьего.
_SET_DESCRIPTION = 7
_SET_WORKING_DIR = 9
_SET_ARGUMENTS = 11
_SET_PATH = 20
_PERSIST_SAVE = 6


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def desktop() -> Path:
    """Рабочий стол текущего пользователя."""
    import os
    profile = os.environ.get("USERPROFILE", "")
    return Path(profile) / "Desktop" if profile else Path.home() / "Desktop"


def app_target() -> tuple[str, str]:
    """Что запускать и с какой рабочей папкой.

    Из собранной версии — сам exe. Из исходников — интерпретатор с main.py:
    ярлык на разработческий запуск тоже иногда нужен.
    """
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return str(exe), str(exe.parent)
    root = Path(__file__).resolve().parent.parent
    return str(Path(sys.executable).resolve()), str(root)


def _safe_name(name: str) -> str:
    out = "".join("_" if c in _BAD else c for c in name).strip(" .")
    return out or "preset"


def _guid(text: str) -> _GUID:
    g = _GUID()
    ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), byref(g))
    return g


def _method(ptr: c_void_p, index: int, *argtypes):
    """Метод COM-объекта по номеру в таблице интерфейса.

    Прототип объявляем как HRESULT: ctypes сам поднимет OSError, если метод
    вернёт ошибку, и разбирать коды вручную не придётся.
    """
    vtable = ctypes.cast(ptr, POINTER(POINTER(c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)
    return proto(vtable[index])


def _wide(ptr: c_void_p, index: int, text: str) -> None:
    """Вызов метода вида Set…(LPCWSTR) — все наши сеттеры такие."""
    _method(ptr, index, ctypes.c_wchar_p)(ptr, ctypes.c_wchar_p(text))


def create(preset_stem: str, title: str, folder: Path | None = None) -> tuple[Path, str]:
    """Создаёт ярлык. Возвращает (путь, ошибка); ошибка пустая при успехе."""
    target, workdir = app_target()
    args = f'--launch "{preset_stem}"'
    if not getattr(sys, "frozen", False):
        # из исходников запускаем через main.py — он и разберёт аргумент
        args = f'"{Path(workdir) / "main.py"}" {args}'
    path = (folder or desktop()) / f"{_safe_name(title)}.lnk"

    ole32 = ctypes.oledll.ole32
    # S_FALSE означает «уже была инициализирована этим потоком» — не ошибка,
    # но и разынициализировать в этом случае нельзя: чужую работу оборвём.
    started = False
    try:
        ole32.CoInitialize(None)
        started = True
    except OSError:
        pass
    link = c_void_p()
    try:
        ole32.CoCreateInstance(byref(_guid(_CLSID_SHELL_LINK)), None,
                               _CLSCTX_INPROC_SERVER,
                               byref(_guid(_IID_SHELL_LINK_W)), byref(link))
        try:
            _wide(link, _SET_PATH, target)
            _wide(link, _SET_ARGUMENTS, args)
            _wide(link, _SET_WORKING_DIR, workdir)
            _wide(link, _SET_DESCRIPTION, title)
            persist = c_void_p()
            _method(link, 0, POINTER(_GUID), POINTER(c_void_p))(
                link, byref(_guid(_IID_PERSIST_FILE)), byref(persist))
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                _method(persist, _PERSIST_SAVE, ctypes.c_wchar_p, wintypes.BOOL)(
                    persist, ctypes.c_wchar_p(str(path)), True)
            finally:
                _method(persist, 2)(persist)        # Release
        finally:
            _method(link, 2)(link)                  # Release
    except OSError as e:
        return path, str(e)
    finally:
        if started:
            ctypes.windll.ole32.CoUninitialize()
    if not path.is_file():
        return path, "ярлык не создался"
    return path, ""
