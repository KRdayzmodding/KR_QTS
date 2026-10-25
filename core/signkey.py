"""Ключ подписи PBO: чем его завести и где он лежит.

Подпись нужна серверу с verifySignatures: он принимает только те моды, чей
.bisign сходится с .bikey в своей папке keys. Пара ключей делается один раз на
проект и живёт годами — поэтому здесь нет ничего, кроме «создать» и «найти».

Создаёт ключи чужая программа: DSCreateKey из DayZ Tools (родная для движка)
или krbuild-cli, если DayZ Tools не установлены. Своего генератора мы не
пишем: формат ключа — чужой, а проверять его правильность нам нечем.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .settings import Settings

# Имя удостоверяющего: буквы, цифры, подчёркивание и дефис. Пробел и кириллица
# ломают не нас, а сервер — он ищет файл по имени из подписи, и любая
# неожиданность в нём превращается в «мод не подписан».
NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,32}$")

PRIVATE_SUFFIX = ".biprivatekey"
PUBLIC_SUFFIX = ".bikey"


def dscreatekey(settings: Settings) -> str:
    """Путь к DSCreateKey.exe из DayZ Tools; пусто — не найден."""
    for root in (settings.dayz_tools, settings.dayz_tools_exp):
        if not root:
            continue
        exe = Path(root) / "Bin" / "DsUtils" / "DSCreateKey.exe"
        if exe.is_file():
            return str(exe)
    return ""


def can_create(settings: Settings) -> str:
    """Почему нельзя создать ключ. Пусто — можно."""
    if dscreatekey(settings):
        return ""
    from . import krbuild
    if not krbuild.missing(settings):
        return ""
    return ("нужны DayZ Tools (в них DSCreateKey) или настроенный Project Builder — "
            "ключи делает одна из этих программ")


def create(settings: Settings, name: str, folder: str) -> tuple[bool, str]:
    """Создаёт пару ключей. Возвращает (успех, путь к .biprivatekey или текст).

    Готовый файл не перезаписываем: ключ подписывает всё, что уже роздано, и
    потерять его молча — значит разом сделать недействительными все подписи,
    сделанные до этого.
    """
    name = (name or "").strip()
    if not NAME_RE.match(name):
        return False, ("Имя ключа: латиница, цифры, дефис и подчёркивание, "
                       "до 32 знаков")
    where = Path(folder or "")
    if not str(where):
        return False, "Не выбрана папка для ключа"
    private = where / (name + PRIVATE_SUFFIX)
    if private.exists():
        return False, f"Такой ключ уже есть: {private}"
    try:
        where.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, str(e)

    exe = dscreatekey(settings)
    if exe:
        # DSCreateKey кладёт пару в текущую папку и имени файла не принимает —
        # поэтому папку задаём рабочим каталогом процесса.
        args, cwd = [exe, name], str(where)
    else:
        from . import krbuild
        why = krbuild.missing(settings)
        if why:
            return False, can_create(settings)
        args, cwd = [krbuild.exe_path(settings), "--create-key", name,
                     str(where)], None
    try:
        res = subprocess.run(args, cwd=cwd, timeout=60, capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    if not private.is_file():
        out = (res.stderr or res.stdout or "").strip()
        return False, out or f"программа отработала, но ключа нет: {private}"
    return True, str(private)


def public_of(private: str) -> str:
    """Открытый ключ рядом с закрытым; пусто — его нет.

    Он и нужен серверу: закрытым подписывают, открытый кладут в keys.
    """
    p = Path(private or "")
    if not str(p):
        return ""
    pub = p.with_suffix(PUBLIC_SUFFIX)
    return str(pub) if pub.is_file() else ""
