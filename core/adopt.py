"""Опознание уже запущенных клиента и сервера DayZ.

Менеджер можно закрыть и открыть заново, а сервер живёт своей жизнью — это
сделано намеренно, отдельный процесс не должен умирать вместе с окном. Но
новый экземпляр менеджера про него ничего не знал: показывал «остановлен»,
предлагал запустить и молчал про занятый порт. Человек либо поднимал второй
сервер поверх первого, либо шёл убивать процесс через диспетчер задач.

Опознаём по командной строке. Она читается у процессов того же пользователя —
а сервер и клиент запускает само приложение, — и содержит всё нужное:

    -server -config=... -profiles=KR_Debug\\profile\\<пресет> -port=2302
    -connect=127.0.0.1:2302

Пути в ней относительные, считать их надо от рабочей папки процесса. По
профилю опознаётся не просто «наш сервер», а конкретный пресет; по порту —
клиент, который к нему подключён.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path

import psutil

# Имена, под которыми DayZ работает клиентом или сервером. Diag-сборка служит и
# тем и другим, отличается флагом -server.
_EXE_NAMES = {"dayz_x64.exe", "dayzdiag_x64.exe", "dayzserver_x64.exe"}

SERVER, CLIENT = "server", "client"


@dataclass
class Running:
    """Найденный процесс DayZ."""
    pid: int
    side: str                  # SERVER | CLIENT
    exe: str = ""
    started: float = 0.0
    port: int = 0
    profiles: str = ""         # абсолютный путь, если удалось вычислить
    preset: str = ""           # имя пресета, если опознан
    args: list[str] = field(default_factory=list)

    @property
    def mine(self) -> bool:
        """Наш ли это процесс — то есть нашлось ли, к какому пресету он относится."""
        return bool(self.preset)


def _arg(args: list[str], prefix: str) -> str:
    for a in args:
        if a.lower().startswith(prefix):
            return a[len(prefix):]
    return ""


def _processes() -> list[psutil.Process]:
    out = []
    for p in psutil.process_iter(["name"]):
        if (p.info["name"] or "").lower() in _EXE_NAMES:
            out.append(p)
    return out


def find(preset_profiles: dict[str, str] | None = None,
         preset_ports: dict[str, int] | None = None) -> list[Running]:
    """Все живые процессы DayZ; опознанные помечены именем пресета.

    preset_profiles — {имя пресета: абсолютный путь к папке профиля},
    preset_ports — {имя пресета: порт}. Оба нужны только для опознания: без них
    процессы всё равно найдутся, просто останутся чужими.
    """
    profiles = {str(Path(v)).lower(): k for k, v in (preset_profiles or {}).items() if v}
    ports = {v: k for k, v in (preset_ports or {}).items() if v}
    out: list[Running] = []
    for p in _processes():
        try:
            args = p.cmdline()
            cwd = p.cwd()
            exe = p.exe()
            started = p.create_time()
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            # чаще всего процесс от администратора, а мы — нет; показать факт
            # запуска всё равно честнее, чем промолчать
            with contextlib.suppress(psutil.Error):
                out.append(Running(pid=p.pid, side=SERVER,
                                   exe=(p.info["name"] or "")))
            continue

        name = Path(exe).name.lower()
        is_server = "-server" in (a.lower() for a in args) or name == "dayzserver_x64.exe"
        rec = Running(pid=p.pid, side=SERVER if is_server else CLIENT,
                      exe=exe, started=started, args=args)

        if is_server:
            raw = _arg(args, "-profiles=")
            if raw:
                # путь в командной строке относительный — от рабочей папки
                full = Path(raw) if Path(raw).is_absolute() else Path(cwd) / raw
                rec.profiles = str(full)
                rec.preset = profiles.get(str(full).lower(), "")
            with contextlib.suppress(ValueError):
                rec.port = int(_arg(args, "-port=") or 0)
        else:
            conn = _arg(args, "-connect=")
            with contextlib.suppress(ValueError):
                rec.port = int(conn.rsplit(":", 1)[-1]) if ":" in conn else 0
            rec.preset = ports.get(rec.port, "")
        out.append(rec)
    return out
