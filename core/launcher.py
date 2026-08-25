"""Сборка командных строк и запуск сервера/клиента с умным ожиданием готовности."""
from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Iterable
from pathlib import Path

import psutil
from PySide6.QtCore import QObject, QThread, Signal

from . import packer, packlog, winhide
from .i18n import tr
from .mods import ModInfo, ModRegistry
from .params import specs_for, SERVER, CLIENT
from .presets import ServerPreset, MODE_DIAG
from .settings import Settings

PROC_NAMES = {"dayz_x64.exe", "dayzdiag_x64.exe", "dayzserver_x64.exe"}

READY_TIMEOUT = 180  # секунд ждём, пока сервер займёт UDP-порт
# Секунд ждём, пока лаунчер BattlEye поднимет сам клиент. Он ставит службу,
# показывает соглашение при первом запуске и только потом стартует игру.
CLIENT_WAIT = 60


def dayz_running() -> bool:
    """Запущен ли хоть один процесс DayZ (сервер/клиент/диаг).

    Правки cfg и чистка профиля во время работы сервера либо не подхватятся
    (файлы прочитаны при старте), либо потеряются — он перезапишет их своими.
    """
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() in PROC_NAMES:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


SERVER_EXE_NAME = "dayzserver_x64.exe"
CLIENT_EXE_NAME = "dayz_x64.exe"
DIAG_EXE_NAME = "dayzdiag_x64.exe"
# Лаунчер BattlEye: поднимает службу BE и уже сам запускает клиент.
BE_LAUNCHER_NAME = "DayZ_BE.exe"


def _proc_kind(proc: psutil.Process) -> str | None:
    """server | client | None (не наш процесс).

    В diag-режиме сервер и клиент — один и тот же DayZDiag_x64.exe, отличается
    только аргумент -server, поэтому по имени их не разделить. Если командную
    строку прочитать не удалось, возвращаем None: лучше не тронуть чужой
    процесс, чем случайно убить работающий сервер.
    """
    try:
        name = (proc.name() or "").lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    if name == SERVER_EXE_NAME:
        return "server"
    if name == CLIENT_EXE_NAME:
        return "client"
    if name != DIAG_EXE_NAME:
        return None
    try:
        return "server" if any(a.lower() == "-server" for a in proc.cmdline()) else "client"
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def kill_kinds(kinds: Iterable[str]) -> int:
    """Гасит процессы DayZ только указанных видов ({"server"} / {"client"}).

    Нужно, чтобы запуск клиента не ронял уже работающий сервер: раньше перед
    каждым стартом безусловно звался kill_all(). Когда просят оба вида, имя
    процесса и так однозначно — командную строку не читаем.
    """
    kinds = set(kinds)
    if not kinds:
        return 0
    both = {"server", "client"} <= kinds
    victims = []
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() not in PROC_NAMES:
                continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if both or _proc_kind(p) in kinds:
            victims.append(p)
    for p in victims:
        try:
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if victims:
        psutil.wait_procs(victims, timeout=5)
    return len(victims)


def kill_pid(pid: int | None) -> bool:
    """Гасит один процесс по pid — чтобы остановить только сервер или только
    клиент, не трогая второй. True, если процесс был жив и убит."""
    if not pid:
        return False
    try:
        proc = psutil.Process(pid)
        proc.kill()
        proc.wait(timeout=5)
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
        return False


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


def rel_to(path: str, root: str) -> str:
    """Путь относительно корня игры/сервера.

    Миссия, моды, профиль и серверный конфиг передаются в DayZ именно
    относительными: рабочей папкой процесса мы и так задаём корень, а
    абсолютные пути раздували командную строку вдвое — в каждый мод повторно
    вписывался весь путь до корня.

    Относительный путь невозможен только между разными дисками — там
    ничего не поделать, оставляем как есть.
    """
    if not path:
        return path
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return path


def _params_args(preset: ServerPreset, target: str) -> list[str]:
    values = preset.params_server if target == SERVER else preset.params_client
    args = []
    for spec in specs_for(target, preset.mode == MODE_DIAG):
        if spec.name in values:
            a = spec.to_arg(values[spec.name])
            if a:
                args.append(a)
    return args


def _mods_arg(names: list[str], registry: ModRegistry, root: str,
              settings: Settings) -> str:
    """Пути junction-ссылок в настроенной папке модов, относительно корня."""
    from .layout import mods_link_dir
    base = mods_link_dir(root, settings)
    folders = []
    for n in names:
        mod = registry.get(n)
        folder = mod.folder_name if mod else (n if n.startswith("@") else "@" + n)
        folders.append(rel_to(str(base / folder), root))
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

    from .layout import resolve_config, resolve_profiles, resolve_mission
    args += [
        f"-config={rel_to(resolve_config(preset.server_config, settings, branch, preset.mode), cwd)}",
        f"-mission={rel_to(resolve_mission(preset.mission, settings, branch, preset.mode), cwd)}",
        f"-profiles={rel_to(resolve_profiles(preset.profiles, settings, branch, preset.mode), cwd)}",
        f"-port={preset.port}",
    ]
    if preset.mods:
        args.append(f"-mod={_mods_arg(preset.mods, registry, cwd, settings)}")
    if preset.server_mods:
        args.append(f"-serverMod={_mods_arg(preset.server_mods, registry, cwd, settings)}")
    args += _params_args(preset, SERVER)
    args += preset.extra_server.split()
    return exe, args, cwd


def build_client_command(preset: ServerPreset, settings: Settings, branch: str,
                         registry: ModRegistry) -> tuple[str, list[str], str]:
    """Возвращает (exe, args, cwd) для клиента."""
    client_root = settings.client_root(branch)
    use_diag = preset.mode == MODE_DIAG or preset.client_use_diag
    if use_diag:
        exe = str(Path(client_root) / "DayZDiag_x64.exe")
    else:
        # Обычный клиент поднимаем через лаунчер BattlEye, а не сам exe: BE
        # запускается только им. Прямой запуск DayZ_x64 оставляет службу BE
        # лежать, и сервер с включённым BattlEye выкидывает игрока с «Game
        # restart required» — секунд через сорок после входа в мир.
        #
        # Аргументы лаунчер передаёт игре как есть, сам exe брать не указываем:
        # он записан в BattlEye\BELauncher.ini (64BitExe) и всегда верный.
        be = Path(client_root) / BE_LAUNCHER_NAME
        exe = str(be if be.is_file() else Path(client_root) / "DayZ_x64.exe")
    args = [f"-connect=127.0.0.1:{preset.port}"]
    if preset.mods:
        args.append(f"-mod={_mods_arg(preset.mods, registry, client_root, settings)}")
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


def _script_logs(profiles: str) -> set[str]:
    """Снимок script-логов в папке профиля — что было до запуска."""
    if not profiles or not Path(profiles).is_dir():
        return set()
    return {str(f) for f in Path(profiles).glob("script_*.log")}


def scripts_ready(known: set[str], profiles: str = "") -> bool:
    """Собрал ли сервер скрипты миссии.

    Признак — строка про расход памяти слоя 5_Mission в script-логе этой
    сессии. Слой компилируется последним, так что до него дело доходит, только
    когда всё остальное уже поднялось. Файлы из known — прошлые сессии, их не
    смотрим: там 5_Mission есть всегда, и ожидание завершилось бы мгновенно.
    """
    from . import scriptmem
    for path in _script_logs(profiles) - known if profiles else set():
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            u = scriptmem.parse(line)
            if u and u.layer == scriptmem.READY_LAYER:
                return True
    return False


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
    pack_plan = Signal(list)        # имена pbo, которые предстоит собрать
    pack_status = Signal(str, str, int, int, int)  # pbo, состояние, мс, warnings, errors
    server_started = Signal(int)    # pid
    server_ready = Signal()         # порт занят — сервер принимает клиент
    client_started = Signal(int)    # pid
    finished_ok = Signal()
    failed = Signal(str)
    cancelled = Signal()            # запуск оборван по просьбе — не ошибка

    def __init__(self, preset: ServerPreset, settings: Settings, branch: str,
                 registry: ModRegistry, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.preset = preset
        self.settings = settings
        self.branch = branch
        self.registry = registry
        self._abort = threading.Event()

    def cancel(self) -> None:
        """Просьба оборвать запуск. Зовут из потока интерфейса.

        Оборвать можно только между шагами: посреди запаковки нельзя — pboProject
        уже пишет pbo, и брошенный на середине файл хуже потерянной минуты.
        Поэтому текущая запаковка доходит до конца, а вот сервер после неё уже
        не поднимется. Процессы, которые успели стартовать, гасит окно: ему
        виднее, какой способ выбран в настройках и что уже поднялось.
        """
        self._abort.set()

    def _await_client(self, since: float) -> int | None:
        """PID игры, поднятой лаунчером BattlEye. None — не дождались.

        Ищем по имени процесса: лаунчер запускает игру не как своего ребёнка,
        и связи «родитель — потомок» здесь нет. Старые клиенты к этому моменту
        уже убиты (шаг 2), так что первый же найденный — наш.
        """
        while time.monotonic() - since < CLIENT_WAIT:
            if self._abort.is_set():
                return None
            for proc in psutil.process_iter(["name"]):
                try:
                    if (proc.info["name"] or "").lower() == CLIENT_EXE_NAME:
                        return proc.pid
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            time.sleep(0.5)
        return None

    def _stop_asked(self) -> bool:
        if not self._abort.is_set():
            return False
        self.cancelled.emit()
        return True

    def run(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001 — любая ошибка должна дойти до UI
            self.failed.emit(str(e))

    def _run(self) -> None:
        p, s, reg = self.preset, self.settings, self.registry
        client_root = s.client_root(self.branch)

        # get() возвращает None для мода, которого нет в реестре, — такие
        # отсеиваем сразу, дальше по коду список считается полным
        selected: list[ModInfo] = [m for m in (reg.get(n) for n in
                                               (p.mods + p.server_mods)) if m]

        # 1. Убираем старые процессы — только тех видов, что сейчас запускаем.
        #    Иначе перезапуск одного клиента ронял бы работающий сервер.
        #    Делаем это до запаковки, а не после: запущенная игра держит pbo
        #    открытыми, и перепаковать их нельзя. Свои прошлые процессы мы всё
        #    равно собирались убить — значит, надо раньше.
        killed = kill_kinds({k for k, on in (("server", p.launch_server),
                                             ("client", p.launch_client)) if on})
        if killed:
            self.log.emit(tr("launch.killed", "Завершено старых процессов: {n}", n=killed), "info")

        if self._stop_asked():
            return

        # 2. Перепаковка устаревших локальных модов (только если включено в настройках)
        if s.repack_before_launch and dayz_running():
            # Осталась живая сторона — например, перезапускаем один клиент при
            # работающем сервере. Она держит pbo, перепаковка упёрлась бы в
            # занятый файл и отменила бы весь запуск. Молчать нельзя: человек
            # должен понимать, что стартует со старыми pbo.
            self.log.emit(tr("launch.pack_skipped",
                             "Перепаковка пропущена: запущенная игра держит PBO. "
                             "Запуск идёт с тем, что собрано."), "warning")
        elif s.repack_before_launch:
            plan = packer.stale_mods(selected)
            # весь список объявляем заранее — сколько PBO предстоит собрать
            # должно быть видно сразу, а не по мере готовности
            self.pack_plan.emit([packer.pbo_for_source(m, src).name
                                 for m, stale in plan for src in stale])
            if plan:
                # Раньше состав перепаковки человек видел в окне предстартовой
                # проверки. Окно убрано — но след в журнале нужен: по нему
                # потом понятно, что именно пересобиралось перед этим запуском.
                self.log.emit(tr("launch.repacking", "Перепаковка ({n}): {mods}",
                                 n=sum(len(st) for _, st in plan),
                                 mods=", ".join(m.name for m, _ in plan)), "info")
            for mod, stale in plan:
                mod_failed = False
                for src in stale:
                    name = packer.pbo_for_source(mod, src).name
                    self.pack_status.emit(name, "packing", -1, 0, 0)
                    t0 = time.monotonic()
                    ok, output = packer.pack_source_auto(
                        s, mod, src,
                        on_wait=lambda n=name: self.log.emit(
                            tr("launch.pack_queued",
                               "{pbo}: ждём, пока освободится pboProject", pbo=n), "info"))
                    w, e = packlog.counts(Path(src).name)
                    self.pack_status.emit(name, "ok" if ok else "fail",
                                          int((time.monotonic() - t0) * 1000), w, e)
                    if not ok:
                        if output:
                            self.log.emit(output[-4000:], "error")
                        mod_failed = True
                        break
                if mod_failed:
                    self.failed.emit(tr("launch.pack_failed",
                                        "Ошибка запаковки {mod}. Запуск отменён.", mod=mod.name))
                    return

        if self._stop_asked():
            return

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

        # 4.5. TimeLogin/TimeLogout в db/globals.xml миссии — общее значение
        #      (применяется перед запуском, переживает пересоздание миссии)
        if p.time_login >= 0:
            from pathlib import Path as _P
            from .layout import resolve_mission
            from .missions import set_global_var
            mission_path = resolve_mission(p.mission, s, self.branch, p.mode)
            if mission_path and _P(mission_path).is_dir():
                # молча: значение задано в пресете, и повторять его в журнале
                # при каждом запуске незачем
                set_global_var(_P(mission_path), "TimeLogin", str(p.time_login))
                set_global_var(_P(mission_path), "TimeLogout", str(p.time_login))

        # 4.6. Права админок (COT/VPP) в папке профиля — до старта сервера,
        #      иначе мод создаст свои файлы с заглушкой и перечитает их только
        #      при следующем запуске
        from .admin_tools import apply as apply_admin_rights, sync_vpp_password_flag
        from .layout import resolve_profiles as _rp
        if s.admin_steamids or s.admin_password:
            profile_dir = _rp(p.profiles, s, self.branch, p.mode)
            for tool, added in apply_admin_rights(profile_dir, selected,
                                                  s.admin_steamids, s.admin_password):
                if added:
                    self.log.emit(tr("launch.admin_rights",
                                     "{tool}: выданы права админа ({n})",
                                     tool=tool.title, n=len(added)), "info")

        # 4.7. vppDisablePassword в cfg — по факту наличия пароля в настройках
        from .layout import resolve_config as _rc
        flag = sync_vpp_password_flag(_rc(p.server_config, s, self.branch, p.mode),
                                      s.admin_password)
        if flag is not None:
            self.log.emit(tr("launch.vpp_password_flag",
                             "serverDZ.cfg: vppDisablePassword = {v}", v=flag), "info")

        if self._stop_asked():
            return

        # 4.8. Своя запаковка позади, но чужая могла начаться со страницы модов
        #      или из списка сорсов. Сервер, стартовавший посреди неё, прочитает
        #      наполовину записанный pbo и упадёт на непонятном месте.
        if not packer.wait_idle(on_wait=lambda: self.log.emit(
                tr("launch.pack_wait_other",
                   "Идёт запаковка мода — ждём её окончания перед стартом"), "info")):
            self.failed.emit(tr("launch.pack_wait_failed",
                                "Запаковка не завершилась — запуск отменён."))
            return

        # 5. Сервер
        server_proc = None
        if p.launch_server:
            # командную строку в журнал не пишем: она длиннее ширины окна,
            # обрезается на середине и вытесняет всё остальное
            exe, args, cwd = build_server_command(p, s, self.branch, reg)
            # снимок логов до старта: ждать готовности надо по файлу этой
            # сессии, иначе прошлый лог с 5_Mission засчитается сразу
            from .layout import resolve_profiles as _rp2
            prof_dir = _rp2(p.profiles, s, self.branch, p.mode)
            server_logs = _script_logs(prof_dir)
            # Способ первый: просим Windows не показывать окно. Выполняется
            # на усмотрение самой программы, поэтому ниже есть и второй.
            hide = getattr(s, "hide_server_window", False)
            server_proc = subprocess.Popen(
                [exe] + args, cwd=cwd,
                startupinfo=winhide.startupinfo() if hide else None)
            self.server_started.emit(server_proc.pid)
            if hide:
                # Способ второй: найти окно по процессу и скрыть. По тому,
                # нашлось ли что скрывать, видно, сработал ли первый.
                n, secs = winhide.hide(server_proc.pid)
                self.log.emit(
                    tr("launch.window_hidden",
                       "Окно сервера скрыто (окон: {n}, через {t:.1f} с)", n=n, t=secs)
                    if n else
                    tr("launch.window_never_shown",
                       "Окно сервера не появилось — хватило просьбы при запуске"),
                    "info")

            # 6. Ожидание готовности сервера.
            #    Клиент не должен стартовать раньше: он тут же полезет
            #    подключаться, а сервер в это время ещё компилирует скрипты.
            #    Готовность — та же, по которой красятся индикаторы: занятый
            #    порт И скомпилированный слой 5_Mission (он последний).
            ps_proc = psutil.Process(server_proc.pid)
            t0 = time.monotonic()
            port_ok = mission_ok = False
            while time.monotonic() - t0 < READY_TIMEOUT:
                if self._abort.is_set():
                    # сам процесс не трогаем: способ завершения знает окно
                    self.cancelled.emit()
                    return
                if server_proc.poll() is not None:
                    self.failed.emit(tr("launch.server_died",
                                        "Сервер завершился при запуске (код {code}). Смотрите RPT-лог.",
                                        code=server_proc.returncode))
                    return
                port_ok = port_ok or _server_ready(ps_proc, p.port)
                mission_ok = mission_ok or scripts_ready(server_logs, prof_dir)
                if port_ok and mission_ok:
                    break
                time.sleep(0.5)
            # Сигналим в обоих случаях: процесс жив (иначе вышли бы по failed),
            # клиент всё равно запускается — кнопке незачем висеть в «Запускается».
            self.server_ready.emit()
            # про успех молчим — он виден по строке статуса «[запущен]»;
            # сообщаем только про нештатный случай
            if not (port_ok and mission_ok):
                missing = (tr("launch.wait_port", "не занял порт") if not port_ok
                           else tr("launch.wait_scripts", "не собрал скрипты миссии"))
                self.log.emit(tr("launch.server_slow",
                                 "Сервер {what} за {sec} с — запускаю клиент на свой страх.",
                                 what=missing, sec=READY_TIMEOUT), "warning")

        if self._stop_asked():
            return

        # 7. Клиент
        if p.launch_client:
            exe, args, cwd = build_client_command(p, s, self.branch, reg)
            t0 = time.monotonic()
            client_proc = subprocess.Popen([exe] + args, cwd=cwd)
            pid = client_proc.pid
            if Path(exe).name.lower() == BE_LAUNCHER_NAME.lower():
                self.log.emit(tr("launch.be_launcher",
                                 "Клиент поднимается через лаунчер BattlEye"), "info")
                # Лаунчер запускает игру и уходит; следить надо за самой игрой,
                # иначе окно решит, что клиент умер через пару секунд.
                found = self._await_client(t0)
                if found:
                    pid = found
                else:
                    self.log.emit(tr("launch.be_no_client",
                                     "Лаунчер BattlEye не поднял клиент за {sec} с — "
                                     "проверьте, установлена ли служба BattlEye "
                                     "(BattlEye/Install_BattlEye.bat, нужны права админа).",
                                     sec=CLIENT_WAIT), "warning")
            self.client_started.emit(pid)

        self.finished_ok.emit()
