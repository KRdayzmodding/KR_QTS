"""Запуск приложения вместе с Windows.

Через ключ реестра Run, а не через ярлык в папке «Автозагрузка»: ярлык
пользователь видит и может унести, а потом гадать, почему настройка в
программе включена, а запуска нет. Ключ — единственное место, и состояние
галки всегда читается оттуда же, куда пишется.

HKEY_CURRENT_USER, а не LOCAL_MACHINE: прав администратора это не требует,
а сервер и так запускается от текущего пользователя.
"""
from __future__ import annotations

import sys
import winreg
from pathlib import Path

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "KR Quick Test Server"


def target() -> str:
    """Команда, которую пропишем в автозагрузку.

    Из собранной версии — сам exe. Из исходников — интерпретатор с main.py:
    разработческий автозапуск тоже иногда нужен, и молча ничего не делать
    хуже, чем честно прописать python.
    """
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    root = Path(__file__).resolve().parent.parent
    return f'"{Path(sys.executable).resolve()}" "{root / "main.py"}"'


def enabled() -> bool:
    """Прописан ли автозапуск прямо сейчас — читаем реестр, не настройки.

    Настройку могли перенести с другой машины, а ключ живёт на этой; правда
    здесь именно за реестром.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except OSError:
        return False


def current_value() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            return str(winreg.QueryValueEx(key, VALUE_NAME)[0])
    except OSError:
        return ""


def apply(on: bool) -> tuple[bool, str]:
    """Включает или выключает автозапуск. (успех, ошибка).

    При включении значение переписываем всегда: программу могли перенести в
    другую папку, и старый путь вёл бы в никуда — Windows на такое молчит.
    """
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            if on:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, target())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass      # не было — и не надо
    except OSError as e:
        return False, str(e)
    return True, ""
