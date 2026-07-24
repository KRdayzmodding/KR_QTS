"""Структура KR_Debug в корне клиента/сервера.

KR_Debug/
├── <имя>.cfg      — серверные конфиги
├── profile/       — профили серверов (по имени пресета)
├── mpmissions/    — миссии
└── MODS/          — junction-ссылки на все подключаемые моды

Правило имён: только [A-Za-z0-9_-]. Конфиг, профиль и миссия пресета
носят одно имя.
"""
from __future__ import annotations

import re
from pathlib import Path

from .presets import MODE_DIAG
from .settings import Settings, APP_DIR

DEBUG_DIR = "KR_Debug"
PROFILE_SUBDIR = "profile"
MISSIONS_SUBDIR = "mpmissions"
MODS_SUBDIR = "MODS"          # junction-ссылки на подключаемые моды
MODS_DL_SUBDIR = "mods_dl"    # скачанные с GitHub моды (реальные файлы)

TEMPLATE_CFG = APP_DIR / "data" / "serverDZ_template.cfg"

_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")

# actual.* — шаблоны карт; имя пресета не должно с ними пересекаться
RESERVED_NAMES = {"actual"}


def valid_name(name: str) -> bool:
    """Только латиница, цифры, дефис и подчёркивание — никакой кириллицы."""
    return bool(_NAME_RE.fullmatch(name or ""))


def name_conflict(name: str, world: str = "", current_key: str = "") -> str:
    """Возвращает текст проблемы с финальным именем пресета или пустую строку.

    Одно имя на разных картах допустимо (финальные имена различаются
    суффиксом карты); дубликат пары имя+карта — нет. Сравнение без учёта
    регистра: файловая система Windows не различает Test и test.
    """
    from .i18n import tr
    from .presets import ServerPreset
    low = (name or "").lower()
    if low in RESERVED_NAMES:
        return tr("preset.name_reserved",
                  "Имя «{n}» зарезервировано под шаблоны карт.", n=name)
    key = f"{low}|{(world or '').lower()}"
    for other in ServerPreset.load_all():
        other_key = f"{other.name.lower()}|{other.world.lower()}"
        if other_key == key and other_key != current_key.lower():
            return tr("preset.name_taken",
                      "Пресет «{n}» для этой карты уже существует.", n=other.name)
    return ""


def preset_key(name: str, world: str) -> str:
    return f"{(name or '').lower()}|{(world or '').lower()}"


def mode_root(settings: Settings, branch: str, mode: str) -> str:
    return settings.client_root(branch) if mode == MODE_DIAG else settings.server_root(branch)


def debug_dir(settings: Settings, branch: str, mode: str) -> Path:
    root = mode_root(settings, branch, mode)
    return Path(root) / DEBUG_DIR if root else Path("")


def ensure_layout(base: Path) -> None:
    for sub in (PROFILE_SUBDIR, MISSIONS_SUBDIR, MODS_SUBDIR):
        (base / sub).mkdir(parents=True, exist_ok=True)


def mods_link_dir(root: str) -> Path:
    return Path(root) / DEBUG_DIR / MODS_SUBDIR


def downloads_base(settings: Settings) -> Path:
    return Path(settings.downloads_dir) if settings.downloads_dir else APP_DIR / "downloads"


def mods_dl_dir(settings: Settings) -> Path:
    """Единое хранилище скачанных модов — общее для всех клиентов и серверов.

    Во все корни моды попадают junction-ссылками через KR_Debug/MODS.
    """
    return downloads_base(settings) / "mods"


def templates_dir(settings: Settings) -> Path:
    """Единое хранилище шаблонов карт actual.<world> — качаются один раз,
    миссии пресетов копируются отсюда в mpmissions нужного корня."""
    return downloads_base(settings) / "templates"


def delete_preset_files(settings: Settings, branch: str, mode: str,
                        server_config: str, profiles: str, mission: str) -> list[str]:
    """Удаляет файлы пресета из KR_Debug. Возвращает список удалённого.

    Трогает только «голые» имена (наша схема); легаси-пути и шаблоны
    actual.* не удаляются.
    """
    import shutil
    base = debug_dir(settings, branch, mode)
    removed: list[str] = []
    if not str(base) or not base.is_dir():
        return removed

    def bare(value: str) -> bool:
        return bool(value) and len(Path(value).parts) == 1

    try:
        if bare(server_config):
            cfg = base / server_config
            if cfg.is_file():
                cfg.unlink()
                removed.append(str(cfg))
        if bare(profiles):
            prof = base / PROFILE_SUBDIR / profiles
            if prof.is_dir():
                shutil.rmtree(prof)
                removed.append(str(prof))
        if bare(mission) and not mission.startswith("actual."):
            m = base / MISSIONS_SUBDIR / mission
            if m.is_dir():
                shutil.rmtree(m)
                removed.append(str(m))
    except OSError:
        pass  # занято процессом — оставшееся пользователь удалит вручную
    return removed


# ------------------------------------------------------------- резолв путей

def _resolve(value: str, settings: Settings, branch: str, mode: str,
             subdir: str) -> str:
    """Голое имя -> KR_Debug/<subdir>/<имя>; иначе легаси-правила."""
    if not value:
        return ""
    p = Path(value)
    if p.is_absolute():
        return str(p)
    if len(p.parts) == 1:
        base = debug_dir(settings, branch, mode)
        if str(base):
            return str(base / subdir / value) if subdir else str(base / value)
    # старые пресеты: путь относительно корня клиента
    return str(Path(settings.client_root(branch)) / p)


def resolve_config(value: str, settings: Settings, branch: str, mode: str) -> str:
    return _resolve(value, settings, branch, mode, "")


def resolve_profiles(value: str, settings: Settings, branch: str, mode: str) -> str:
    return _resolve(value, settings, branch, mode, PROFILE_SUBDIR)


def resolve_mission(value: str, settings: Settings, branch: str, mode: str) -> str:
    return _resolve(value, settings, branch, mode, MISSIONS_SUBDIR)


# ------------------------------------------------------------- создание файлов

def preset_base_name(name: str, mission_name: str = "") -> str:
    """Имя файлов пресета: <имя>_<карта> (карта — суффикс миссии)."""
    world = mission_name.rsplit(".", 1)[1] if "." in mission_name else ""
    return f"{name}_{world}" if world else name


def create_preset_files(settings: Settings, branch: str, mode: str,
                        name: str, mission_name: str = "") -> tuple[str, str]:
    """Создаёт KR_Debug/<имя>_<карта>.cfg (из шаблона) и KR_Debug/profile/<имя>_<карта>.

    Возвращает значения для пресета: (config, profiles) — голые имена.
    Существующий cfg не перезаписывается.
    """
    base = debug_dir(settings, branch, mode)
    if not str(base):
        raise RuntimeError("Не задан корень игры/сервера в настройках")
    ensure_layout(base)
    fname = preset_base_name(name, mission_name)

    cfg_path = base / f"{fname}.cfg"
    if not cfg_path.exists():
        try:
            template = TEMPLATE_CFG.read_text(encoding="utf-8")
        except OSError:
            template = 'hostname = "{NAME}";\n'
        text = template.replace("{NAME}", name).replace(
            "{MISSION}", mission_name or "dayzOffline.chernarusplus")
        cfg_path.write_bytes(text.encode("utf-8"))  # UTF-8 без BOM

    (base / PROFILE_SUBDIR / fname).mkdir(parents=True, exist_ok=True)
    return f"{fname}.cfg", fname


def clear_mission_storage(settings: Settings, branch: str, mode: str,
                          mission_value: str) -> int:
    """Удаляет папки storage_* в миссии пресета (обнуление БД). Возвращает число удалённых."""
    import shutil
    mission = resolve_mission(mission_value, settings, branch, mode)
    n = 0
    if mission and Path(mission).is_dir():
        for st in Path(mission).glob("storage_*"):
            try:
                shutil.rmtree(st)
                n += 1
            except OSError:
                pass
    return n


def clear_profile(settings: Settings, branch: str, mode: str,
                  profiles_value: str) -> int:
    """Полностью чистит содержимое папки профиля (сама папка остаётся)."""
    import shutil
    prof = resolve_profiles(profiles_value, settings, branch, mode)
    n = 0
    if prof and Path(prof).is_dir():
        for item in Path(prof).iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
                n += 1
            except OSError:
                pass
    return n


def rename_preset_files(settings: Settings, branch: str, mode: str,
                        old: str, new: str, world: str) -> None:
    """Переименование пресета: тянет за собой cfg, профиль и миссию ЕГО карты.

    Только файлы пары <old>_<world> — у пресетов с тем же именем на других
    картах свои файлы, их не трогаем.
    """
    base = debug_dir(settings, branch, mode)
    if not str(base) or not base.is_dir() or not world:
        return
    pairs = [
        (base / f"{old}_{world}.cfg", base / f"{new}_{world}.cfg"),
        (base / PROFILE_SUBDIR / f"{old}_{world}", base / PROFILE_SUBDIR / f"{new}_{world}"),
        (base / MISSIONS_SUBDIR / f"{old}.{world}", base / MISSIONS_SUBDIR / f"{new}.{world}"),
    ]
    for src, dst in pairs:
        try:
            if src.exists() and not dst.exists():
                src.rename(dst)
        except OSError:
            pass  # занято процессом и т.п. — не критично, файлы создадутся заново
