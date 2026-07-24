"""Сборка командных строк и запуск сервера/клиента с умным ожиданием готовности."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QObject, QThread, Signal

from . import packer
from .i18n import tr
from .mods import ModRegistry
from .params import specs_for, SERVER, CLIENT
from .presets import ServerPreset, MODE_DIAG
from .settings import Settings

PROC_NAMES = {"dayz_x64.exe", "dayzdiag_x64.exe", "dayzserver_x64.exe"}

READY_TIMEOUT = 180  # секунд ждём, пока сервер займёт UDP-порт


def kill_all() -> int:
    """Убивает все процессы DayZ. Возвращает количество убитых."""
    n = 0
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() in PROC_NAMES:
                p.kill()
                n += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if n:
        psutil.wait_procs(
            [p for p in psutil.process_iter(["name"])
             if (p.info["name"] or "").lower() in PROC_NAMES],
            timeout=5,
        )
    return n


def resolve_path(value: str, client_root: str) -> str:
    """Пути пресета хранятся относительно корня клиента; в командную строку — абсолютные."""
    if not value:
        return ""
    p = Path(value)
    return str(p) if p.is_absolute() else str(Path(client_root) / p)


def _params_args(preset: ServerPreset, target: str) -> list[str]:
    values = preset.params_server if target == SERVER else preset.params_client
    args = []
    for spec in specs_for(target, preset.mode == MODE_DIAG):
        if spec.name in values:
            a = spec.to_arg(values[spec.name])
            if a:
                args.append(a)
    return args


def _mods_arg(names: list[str], registry: ModRegistry) -> str:
    folders = []
    for n in names:
        mod = registry.get(n)
        folders.append(mod.folder_name if mod else (n if n.startswith("@") else "@" + n))
    return ";".join(folders)


def build_server_command(preset: ServerPreset, settings: Settings, branch: str,
                         registry: ModRegistry) -> tuple[str, list[str], str]:
    """Возвращает (exe, args, cwd) для сервера."""
    client_root = settings.client_root(branch)
    if preset.mode == MODE_DIAG:
        exe = str(Path(client_root) / "DayZDiag_x64.exe")
        cwd = client_root
        args = ["-server"]
    else:
        cwd = settings.server_root(branch)
        exe = str(Path(cwd) / "DayZServer_x64.exe")
        args = []

    from .missions import resolve_mission
    args += [
        f"-config={resolve_path(preset.server_config, client_root)}",
        f"-mission={resolve_mission(preset.mission, settings, branch, preset.mode)}",
        f"-profiles={resolve_path(preset.profiles, client_root)}",
        f"-port={preset.port}",
    ]
    if preset.mods:
        args.append(f"-mod={_mods_arg(preset.mods, registry)}")
    if preset.server_mods:
        args.append(f"-serverMod={_mods_arg(preset.server_mods, registry)}")
    args += _params_args(preset, SERVER)
    args += preset.extra_server.split()
    return exe, args, cwd


def build_client_command(preset: ServerPreset, settings: Settings, branch: str,
                         registry: ModRegistry) -> tuple[str, list[str], str]:
    """Возвращает (exe, args, cwd) для клиента."""
    client_root = settings.client_root(branch)
    use_diag = preset.mode == MODE_DIAG or preset.client_use_diag
    exe = str(Path(client_root) / ("DayZDiag_x64.exe" if use_diag else "DayZ_x64.exe"))
    args = [f"-connect=127.0.0.1:{preset.port}"]
    if preset.mods:
        args.append(f"-mod={_mods_arg(preset.mods, registry)}")
    args += _params_args(preset, CLIENT)
    args += preset.extra_client.split()
    return exe, args, client_root


def port_is_free(port: int) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _server_ready(proc: psutil.Process, port: int) -> bool:
    """Сервер готов, когда занял свой UDP-порт."""
    try:
        conns = proc.net_connections(kind="inet")
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    except AttributeError:  # psutil < 6
        conns = proc.connections(kind="inet")
    return any(c.laddr and c.laddr.port == port for c in conns)


class LaunchWorker(QThread):
    """Последовательность запуска в отдельном потоке.

    Шаги: перепаковка устаревших модов -> kill -> junction -> ключи ->
    сервер -> ожидание готовности -> клиент.
    """
    log = Signal(str, str)          # message, level: info|warning|error
    server_started = Signal(int)    # pid
    client_started = Signal(int)    # pid
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, preset: ServerPreset, settings: Settings, branch: str,
                 registry: ModRegistry, parent: QObject | None = None):
        super().__init__(parent)
        self.preset = preset
        self.settings = settings
        self.branch = branch
        self.registry = registry

    def run(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001 — любая ошибка должна дойти до UI
            self.failed.emit(str(e))

    def _run(self) -> None:
        p, s, reg = self.preset, self.settings, self.registry
        client_root = s.client_root(self.branch)

        selected = [reg.get(n) for n in (p.mods + p.server_mods)]
        selected = [m for m in selected if m]

        # 1. Перепаковка устаревших локальных модов
        for mod, stale in packer.stale_mods(selected):
            for src in stale:
                self.log.emit(tr("launch.packing", "Запаковка: {src}", src=src), "info")
                ok, output = packer.pack_source(s, mod, src, lambda m: self.log.emit(m, "info"))
                if not ok:
                    self.log.emit(output[-4000:], "error")
                    self.failed.emit(tr("launch.pack_failed",
                                        "Ошибка запаковки {mod}. Запуск отменён.", mod=mod.name))
                    return
                self.log.emit(tr("launch.packed", "Готово: {mod}", mod=mod.name), "info")

        # 2. Убираем старые процессы
        killed = kill_all()
        if killed:
            self.log.emit(tr("launch.killed", "Завершено старых процессов: {n}", n=killed), "info")

        # 3. Junction для модов
        roots = [client_root]
        if p.mode != MODE_DIAG:
            roots.append(s.server_root(self.branch))
        for mod in selected:
            for root in roots:
                # серверные моды в корень клиента не обязательны, но не мешают
                ok, err = reg.ensure_available(mod, root)
                if not ok:
                    self.failed.emit(tr("launch.junction_failed",
                                        "Не удалось подключить мод {mod}: {err}",
                                        mod=mod.name, err=err))
                    return

        # 4. Ключи для dedicated
        if p.mode != MODE_DIAG:
            for mod in selected:
                reg.copy_keys(mod, s.server_root(self.branch))

        # 5. Сервер
        server_proc = None
        if p.launch_server:
            exe, args, cwd = build_server_command(p, s, self.branch, reg)
            self.log.emit(tr("launch.server_cmd", "Сервер: {cmd}",
                             cmd=exe + " " + " ".join(args)), "info")
            server_proc = subprocess.Popen([exe] + args, cwd=cwd)
            self.server_started.emit(server_proc.pid)

            # 6. Ожидание готовности
            ps_proc = psutil.Process(server_proc.pid)
            t0 = time.monotonic()
            ready = False
            while time.monotonic() - t0 < READY_TIMEOUT:
                if server_proc.poll() is not None:
                    self.failed.emit(tr("launch.server_died",
                                        "Сервер завершился при запуске (код {code}). Смотрите RPT-лог.",
                                        code=server_proc.returncode))
                    return
                if _server_ready(ps_proc, p.port):
                    ready = True
                    break
                time.sleep(0.5)
            if ready:
                self.log.emit(tr("launch.server_ready",
                                 "Сервер готов, порт {port} занят за {sec} с.",
                                 port=p.port, sec=int(time.monotonic() - t0)), "info")
            else:
                self.log.emit(tr("launch.server_slow",
                                 "Сервер не занял порт за {sec} с — запускаю клиент на свой страх.",
                                 sec=READY_TIMEOUT), "warning")

        # 7. Клиент
        if p.launch_client:
            exe, args, cwd = build_client_command(p, s, self.branch, reg)
            self.log.emit(tr("launch.client_cmd", "Клиент: {cmd}",
                             cmd=exe + " " + " ".join(args)), "info")
            client_proc = subprocess.Popen([exe] + args, cwd=cwd)
            self.client_started.emit(client_proc.pid)

        self.finished_ok.emit()
