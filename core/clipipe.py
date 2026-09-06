"""Связь с работающей копией QTS — только стандартной библиотекой.

QLocalServer на Windows это именованный канал \\\\.\\pipe\\<имя>, а такой канал
открывается обычным open(). Поэтому здесь нет ни Qt, ни PySide: тот же приём
повторяется в десяти строках на любом языке — NamedPipeClientStream в C#,
Get-Content/Set-Content в PowerShell, — и внешние инструменты не обязаны
зависеть от нашей библиотеки.

Имя канала обязано совпадать с тем, что открывает приложение
(ui/single_instance.py). Оно с именем пользователя: на общей машине у каждого
своя копия, и стучаться в чужую нельзя.
"""
from __future__ import annotations

import os
import time

_NAME = "KR_QTS_single_instance"     # то же, что в ui/single_instance.py


class EngineDown(Exception):
    """Достучаться не удалось: копия не запущена или ещё не открыла канал."""


def pipe_path(user: str = "") -> str:
    user = user or os.environ.get("USERNAME", "")
    return "\\\\.\\pipe\\" + (f"{_NAME}_{user}" if user else _NAME)


def send(line: str, user: str = "", tries: int = 1, pause: float = 0.4,
         timeout: float = 900.0) -> str:
    """Отправляет строку и возвращает ответную. Бросает EngineDown.

    Несколько попыток нужны не «на всякий случай», а после подъёма приложения:
    процесс уже стартовал, но канал откроет через секунду-другую, и первая
    попытка честно упрётся в его отсутствие.

    Ждать ответа приходится долго: запаковка с подъёмом сервера — это минуты, а
    не секунды. Поэтому потолок задаётся вызывающим, а не выбирается здесь.
    """
    path = pipe_path(user)
    last = None
    for attempt in range(max(1, tries)):
        try:
            with open(path, "r+b", buffering=0) as pipe:
                pipe.write(line.encode("utf-8") + b"\n")
                return _read_line(pipe, timeout)
        except OSError as e:
            last = e
            if attempt + 1 < tries:
                time.sleep(pause)
    raise EngineDown(str(last) if last else "канал недоступен")


def _read_line(pipe, timeout: float) -> str:
    """Ответ до перевода строки.

    Читаем по кусочкам, а не readline(): на именованном канале буферизованное
    чтение может застрять до закрытия канала другой стороной, а нам нужен
    ответ ровно тогда, когда он написан.
    """
    deadline = time.monotonic() + timeout
    buf = bytearray()
    while time.monotonic() < deadline:
        chunk = pipe.read(4096)
        if not chunk:
            time.sleep(0.05)
            continue
        buf += chunk
        if b"\n" in buf:
            break
    return buf.split(b"\n", 1)[0].decode("utf-8", "replace")


def alive(user: str = "") -> bool:
    """Работает ли копия. Открываем и сразу закрываем — ничего не посылая."""
    try:
        with open(pipe_path(user), "r+b", buffering=0):
            return True
    except OSError:
        return False
