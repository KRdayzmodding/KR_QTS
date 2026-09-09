"""Предстартовая проверка конфигурации: критичные и некритичные проблемы."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import packer
from .i18n import tr
from .launcher import port_is_free
from .mods import ModRegistry
from .presets import ServerPreset, MODE_DIAG
from .servercfg import ServerCfg, needs_reencode
from .settings import Settings

CRITICAL = "critical"
WARNING = "warning"


@dataclass
class Problem:
    check_id: str
    severity: str
    message: str


def run_checks(preset: ServerPreset, settings: Settings, branch: str,
               registry: ModRegistry) -> list[Problem]:
    """Возвращает список найденных проблем (пустой список — всё в порядке)."""
    problems: list[Problem] = []

    def crit(cid: str, msg: str) -> None:
        problems.append(Problem(cid, CRITICAL, msg))

    def warn(cid: str, msg: str) -> None:
        problems.append(Problem(cid, WARNING, msg))

    client_root = settings.client_root(branch)
    server_root = settings.server_root(branch)

    # Корни и экзешники
    if not client_root or not Path(client_root).is_dir():
        crit("client_root", tr("check.client_root",
             "Папка клиента не найдена: {p}", p=client_root or "—"))
        return problems  # без корня клиента дальше проверять нечего

    if preset.mode == MODE_DIAG:
        if not (Path(client_root) / "DayZDiag_x64.exe").is_file():
            crit("diag_exe", tr("check.diag_exe",
                 "DayZDiag_x64.exe не найден в {p}", p=client_root))
    else:
        if not server_root or not Path(server_root).is_dir():
            crit("server_root", tr("check.server_root",
                 "Папка сервера не найдена: {p}", p=server_root or "—"))
        elif not (Path(server_root) / "DayZServer_x64.exe").is_file():
            crit("server_exe", tr("check.server_exe",
                 "DayZServer_x64.exe не найден в {p}", p=server_root))

    if preset.launch_client:
        exe = "DayZDiag_x64.exe" if (preset.mode == MODE_DIAG or preset.client_use_diag) else "DayZ_x64.exe"
        if not (Path(client_root) / exe).is_file():
            crit("client_exe", tr("check.client_exe",
                 "{exe} не найден в {p}", exe=exe, p=client_root))

    # Пути пресета
    from .layout import resolve_config, resolve_profiles
    cfg = resolve_config(preset.server_config, settings, branch, preset.mode)
    if not cfg or not Path(cfg).is_file():
        crit("config", tr("check.config", "Серверный конфиг не найден: {p}", p=cfg or "—"))
    elif needs_reencode(Path(cfg)):
        warn("config_enc", tr("check.config_enc",
             "Кодировка конфига не UTF-8 без BOM — будет исправлена автоматически."))

    from .missions import mpmissions_dir, resolve_mission
    mission = resolve_mission(preset.mission, settings, branch, preset.mode)
    if not mission or not Path(mission).is_dir():
        crit("mission", tr("check.mission", "Папка миссии не найдена: {p}", p=mission or "—"))

    # Отдельно — миссия, записанная в самом конфиге. Сервер грузит именно её:
    # template из class Missions, а не поле пресета. Эти два значения расходятся,
    # стоит поменять миссию в редакторе конфига, и тогда проверка поля пресета
    # смотрит не туда — сервер молча падает на старте.
    if cfg and Path(cfg).is_file():
        try:
            tpl = next((v.value for v in ServerCfg(Path(cfg)).variables()
                        if v.name == "template"), "")
        except OSError:
            tpl = ""
        if tpl:
            folder = mpmissions_dir(settings, branch, preset.mode) / tpl
            if not folder.is_dir():
                crit("cfg_mission", tr(
                    "check.cfg_mission",
                    "Миссия «{m}» из конфига сервера не установлена: нет папки {p}",
                    m=tpl, p=str(folder)))

    profiles = resolve_profiles(preset.profiles, settings, branch, preset.mode)
    if not profiles:
        warn("profiles", tr("check.profiles_empty",
             "Папка профиля не указана — сервер будет писать логи в папку по умолчанию."))
    elif not Path(profiles).is_dir():
        warn("profiles_missing", tr("check.profiles_missing",
             "Папка профиля не существует и будет создана: {p}", p=profiles))

    # Моды
    for name in preset.mods + preset.server_mods:
        mod = registry.get(name)
        if not mod:
            crit("mod_" + name, tr("check.mod_missing", "Мод не найден: {m}", m=name))
        elif not Path(mod.path).is_dir():
            crit("mod_" + name, tr("check.mod_gone",
                 "Папка мода исчезла: {m} ({p})", m=name, p=mod.path))
    selected = [m for m in (registry.get(n) for n in preset.mods + preset.server_mods) if m]
    # Устаревшие сорсы сами по себе не повод останавливать человека вопросом:
    # перепаковку он уже включил в настройках, и спрашивать каждый запуск
    # «точно перепаковать?» — значит требовать подтверждения тому, что он
    # только что попросил делать всегда. Что именно пакуется, видно по ходу
    # дела в таблице запаковки. А вот отсутствие pboProject — настоящий
    # тупик: паковать нечем, и сервер поднимется со старыми pbo.
    if settings.repack_before_launch:
        stale_names = [mod.name for mod, _ in packer.stale_mods(selected)]
        if stale_names:
            exe, tool = settings.pbo_project_exe(), "pboProject"
            if not Path(exe).is_file():
                crit("packer", tr("check.packer_missing",
                     "Моды {mods} требуют запаковки, но {tool} не найден: {p}",
                     mods=", ".join(stale_names), tool=tool, p=exe))

    # Моды из мастерской: устаревший мод — это сервер, который ведёт себя не
    # так, как написано в его скриптах, и понять это по логам невозможно.
    from . import modupdate
    left = modupdate.stale(selected)
    if left:
        names = ", ".join(s.mod.name for s in left)
        if not getattr(settings, "mod_update_before_launch", True):
            warn("mods_stale", tr(
                "check.mods_stale",
                "Моды не актуальны: {mods}. Обновление перед запуском выключено — "
                "сервер поднимется со старыми версиями.", mods=names))
        elif getattr(settings, "mod_update_method", "wait") == modupdate.STEAMCMD:
            exe = getattr(settings, "steamcmd_exe", "")
            if not exe or not Path(exe).is_file():
                crit("steamcmd", tr(
                    "check.steamcmd",
                    "Моды требуют обновления ({mods}), но SteamCMD не найден: {p}",
                    mods=names, p=exe or "—"))

    # Порт
    if preset.launch_server and not port_is_free(preset.port):
        warn("port", tr("check.port",
             "UDP-порт {port} занят — возможно, сервер уже запущен (старые процессы будут завершены).",
             port=preset.port))

    # Обычный клиент запускается лаунчером BattlEye — без него сервер с
    # включённым BE выкинет игрока уже после входа в мир
    if preset.launch_client and preset.mode != MODE_DIAG and not preset.client_use_diag:
        from .launcher import BE_LAUNCHER_NAME
        root = settings.client_root(branch)
        if root and not (Path(root) / BE_LAUNCHER_NAME).is_file():
            warn("be_missing", tr("check.be_missing",
                 "Рядом с клиентом нет DayZ_BE.exe — BattlEye не запустится, и сервер "
                 "выкинет игрока. Проверьте целостность файлов игры."))

    # Режим diag и BattlEye
    if preset.mode == MODE_DIAG and preset.params_server.get("battleye", None) is not False:
        warn("battleye", tr("check.battleye",
             "Diag-режим обычно требует battleye=0 — проверьте параметры, если сервер не стартует."))

    return problems


def has_critical(problems: list[Problem]) -> bool:
    return any(p.severity == CRITICAL for p in problems)
