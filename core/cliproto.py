"""Протокол внешнего управления: что летает по каналу и что значит код возврата.

Одна строка JSON в запрос, одна в ответ. Канал уже есть — это тот же именованный
канал одиночной копии (\\\\.\\pipe\\KR_QTS_<юзер>), по которому вторая копия
просит первую показаться. На Windows он открывается обычным open(), поэтому
клиенту не нужен ни Qt, ни PySide: в C# это NamedPipeClientStream, в PowerShell
то же самое, в Python — стандартная библиотека.

Правила, которые делают протокол расширяемым, а не хрупким:

* версия в каждом ответе — обновление QTS не ломает чужой инструмент молча;
* идентификатор запроса возвращается в ответе — можно слать несколько подряд;
* неизвестная команда — ошибка со списком, а не молчание;
* новые поля только необязательные, старые не удаляются.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass

API = 1

# Коды возврата отвечают ровно на один вопрос: поднялось или нет. Ошибки
# скриптов на них не влияют никогда — они едут в отчёте отдельным списком,
# и что с ними делать, решает тот, кто запускал.
EXIT_OK = 0
EXIT_ARGS = 1            # не понял аргументы
EXIT_NOT_READY = 2       # нет пресета или программа не настроена
EXIT_PACK = 3            # запаковка не удалась
EXIT_SERVER = 4          # сервер не поднялся за отведённое время
EXIT_CLIENT = 5          # клиент не поднялся
EXIT_CRASHED = 6         # упало уже после старта
EXIT_NO_ENGINE = 7       # не удалось связаться с QTS и не удалось его поднять

EXIT_NAMES = {
    EXIT_OK: "всё запрошенное поднялось",
    EXIT_ARGS: "не понял аргументы",
    EXIT_NOT_READY: "нет пресета или программа не настроена",
    EXIT_PACK: "запаковка не удалась",
    EXIT_SERVER: "сервер не поднялся за отведённое время",
    EXIT_CLIENT: "клиент не поднялся",
    EXIT_CRASHED: "упало уже после старта",
    EXIT_NO_ENGINE: "не удалось связаться с QTS",
}

# Коды ошибок — для программ. Текст рядом — для людей; разбирать текст
# программе нельзя, он меняется вместе с переводом.
E_ARGS = "bad_args"
E_UNKNOWN_CMD = "unknown_command"
E_NO_PRESET = "no_preset"
E_NOT_CONFIGURED = "not_configured"
E_BUSY = "busy"
E_INTERNAL = "internal"


def request(cmd: str, payload: dict | None = None, rid: int = 1) -> str:
    body = {"v": API, "id": rid, "cmd": cmd}
    if payload:
        body.update(payload)
    return json.dumps(body, ensure_ascii=False)


def ok(rid: int, report: dict | None = None, code: int = EXIT_OK) -> str:
    return json.dumps({"v": API, "id": rid, "ok": True, "exit": code,
                       "report": report or {}}, ensure_ascii=False)


def fail(rid: int, code: str, text: str, hint: str = "",
         exit_code: int = EXIT_ARGS) -> str:
    err = {"code": code, "text": text}
    if hint:
        err["hint"] = hint
    return json.dumps({"v": API, "id": rid, "ok": False, "exit": exit_code,
                       "error": err}, ensure_ascii=False)


def decode(line: str) -> dict:
    """Строка канала в словарь. Не наше — не притворяемся, что поняли."""
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def plain(obj) -> dict:
    """Датакласс в словарь для отправки. Вложенные разбираются сами."""
    return asdict(obj) if is_dataclass(obj) else dict(obj)
