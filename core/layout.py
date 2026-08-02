"""Где приложение держит свои файлы внутри корня клиента/сервера.

По умолчанию всё лежит в KR_Debug:

    KR_Debug/<имя>.cfg      — серверные конфиги
    KR_Debug/profile/       — профили серверов (по имени пресета)
    KR_Debug/mpmissions/    — миссии
    KR_Debug/MODS/          — junction-ссылки на все подключаемые моды

Но каждый из четырёх путей настраивается отдельно и независимо: у людей разные
привычки в именах — profile или profiles, mpmissions или mpmission, — и
навязывать своё написание незачем. Пустая строка означает сам корень.

Пути относительные и остаются такими до конца: в командную строку DayZ уходит
именно относительный путь, рабочей папкой процесса задан корень. Абсолютный
собирается только внутри приложения, чтобы потрогать файл.

Правило имён пресетов: только [A-Za-z0-9_-]. Конфиг, профиль и миссия пресета
носят одно имя.
"""
from __future__ import annotations

import re
from pathlib import Path

from .presets import MODE_DIAG
from .settings import Settings, APP_DIR, RES_DIR

# Виды файлов и поля настроек, задающие их расположение. Порядок — порядок
# строк в окне настройки.
CONFIG, PROFILE, MISSIONS, MODS = "config", "profile", "missions", "mods"

PATH_FIELDS: dict[str, str] = {
    CONFIG: "path_config",
    PROFILE: "path_profile",
    MISSIONS: "path_missions",
    MODS: "path_mods",
}

TEMPLATE_CFG = RES_DIR / "data" / "serverDZ_template.cfg"

# Первый символ — только буква: имя пресета уходит в имена папок миссии и
# профиля, в имя конфига и дальше в конфиг сервера, а идентификатор,
# начинающийся с цифры или знака, — источник проблем.
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")

# actual.* — шаблоны карт; имя пресета не должно с ними пересекаться
RESERVED_NAMES = {"actual"}


def valid_name(name: str) -> bool:
    """Только латиница, цифры, дефис и подчёркивание — никакой кириллицы.
    Первым символом — только буква."""
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


def rel_path(settings: Settings, kind: str) -> str:
    """Настроенный относительный путь для вида файлов. Пустой — сам корень."""
    return (getattr(settings, PATH_FIELDS[kind], "") or "").strip()


def kind_dir_in(root: str, settings: Settings, kind: str) -> Path:
    """Папка вида файлов внутри указанного корня."""
    if not root:
        return Path("")
    rel = rel_path(settings, kind)
    return Path(root) / rel if rel else Path(root)


def kind_dir(settings: Settings, branch: str, mode: str, kind: str) -> Path:
    """Папка вида файлов для режима: клиент для Diag, иначе сервер."""
    return kind_dir_in(mode_root(settings, branch, mode), settings, kind)


def ensure_layout(settings: Settings, branch: str, mode: str) -> None:
    """Создаёт все четыре папки. Совпадающие пути схлопнутся сами."""
    for kind in PATH_FIELDS:
        d = kind_dir(settings, branch, mode, kind)
        if str(d):
            d.mkdir(parents=True, exist_ok=True)


def mods_link_dir(root: str, settings: Settings) -> Path:
    return kind_dir_in(root, settings, MODS)


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
    removed: list[str] = []

    def bare(value: str) -> bool:
        return bool(value) and len(Path(value).parts) == 1

    def d(kind: str) -> Path:
        return kind_dir(settings, branch, mode, kind)

    try:
        if bare(server_config):
            cfg = d(CONFIG) / server_config
            if cfg.is_file():
                cfg.unlink()
                removed.append(str(cfg))
        if bare(profiles):
            prof = d(PROFILE) / profiles
            if prof.is_dir():
                shutil.rmtree(prof)
                removed.append(str(prof))
        if bare(mission) and not mission.startswith("actual."):
            m = d(MISSIONS) / mission
            if m.is_dir():
                shutil.rmtree(m)
                removed.append(str(m))
    except OSError:
        pass  # занято процессом — оставшееся пользователь удалит вручную
    return removed


# ------------------------------------------------------------- резолв путей

def _resolve(value: str, settings: Settings, branch: str, mode: str,
             kind: str) -> str:
    """Голое имя -> <папка вида>/<имя>; иначе легаси-правила."""
    if not value:
        return ""
    p = Path(value)
    if p.is_absolute():
        return str(p)
    if len(p.parts) == 1:
        base = kind_dir(settings, branch, mode, kind)
        if str(base):
            return str(base / value)
    # старые пресеты: путь относительно корня клиента
    return str(Path(settings.client_root(branch)) / p)


def resolve_config(value: str, settings: Settings, branch: str, mode: str) -> str:
    return _resolve(value, settings, branch, mode, CONFIG)


def resolve_profiles(value: str, settings: Settings, branch: str, mode: str) -> str:
    return _resolve(value, settings, branch, mode, PROFILE)


def resolve_mission(value: str, settings: Settings, branch: str, mode: str) -> str:
    return _resolve(value, settings, branch, mode, MISSIONS)


# ------------------------------------------------------------- создание файлов

def preset_base_name(name: str, mission_name: str = "") -> str:
    """Имя файлов пресета: <имя>_<карта> (карта — суффикс миссии)."""
    world = mission_name.rsplit(".", 1)[1] if "." in mission_name else ""
    return f"{name}_{world}" if world else name


TEST_SUFFIX = "TEST"


def server_display_name(prefix: str, preset_name: str) -> str:
    """Название сервера для hostname: «[префикс] имя пресета TEST».

    TEST дописывается всегда. Раньше стояла защита от дубля — не дописывать,
    если слово уже есть в префиксе или имени, — и она же всё ломала: проверка
    шла по подстроке, а пресет с именем «test» здесь скорее правило, чем
    исключение. Выходило «[KR] test» вместо «[KR] test TEST», причём молча и
    только у части пресетов.

    Предсказуемость важнее аккуратности редкого случая: «[KR TEST] my TEST»
    выглядит избыточно, но человек хотя бы знает, что получит.
    """
    prefix, preset_name = prefix.strip(), preset_name.strip()
    parts = []
    if prefix:
        parts.append(f"[{prefix}]")
    if preset_name:
        parts.append(preset_name)
    parts.append(TEST_SUFFIX)
    return " ".join(parts)


def create_preset_files(settings: Settings, branch: str, mode: str,
                        name: str, mission_name: str = "") -> tuple[str, str]:
    """Создаёт KR_Debug/<имя>_<карта>.cfg (из шаблона) и KR_Debug/profile/<имя>_<карта>.

    Возвращает значения для пресета: (config, profiles) — голые имена.
    Существующий cfg не перезаписывается.
    """
    if not mode_root(settings, branch, mode):
        raise RuntimeError("Не задан корень игры/сервера в настройках")
    ensure_layout(settings, branch, mode)
    fname = preset_base_name(name, mission_name)

    cfg_path = kind_dir(settings, branch, mode, CONFIG) / f"{fname}.cfg"
    if not cfg_path.exists():
        try:
            template = TEMPLATE_CFG.read_text(encoding="utf-8")
        except OSError:
            template = 'hostname = "{NAME}";\n'
        # Название собирается здесь, а не в шаблоне: правило «[префикс] имя
        # TEST» требует проверки, нет ли слова TEST уже в префиксе или имени,
        # а подстановкой в шаблон такое не выразить.
        name_value = server_display_name(settings.project_prefix, name)
        text = template.replace("{NAME}", name_value).replace(
            "{MISSION}", mission_name or "dayzOffline.chernarusplus")
        cfg_path.write_bytes(text.encode("utf-8"))  # UTF-8 без BOM

    profile = kind_dir(settings, branch, mode, PROFILE) / fname
    profile.mkdir(parents=True, exist_ok=True)
    # структура админок готовится сразу: какие моды подключат — на этом шаге
    # ещё неизвестно, а лишние пустые папки безвредны, зато права/пароль уже
    # на месте и не придётся править файлы после первого запуска
    from .admin_tools import apply as apply_admin_rights
    apply_admin_rights(profile, None, settings.admin_steamids, settings.admin_password)
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
    if not mode_root(settings, branch, mode) or not world:
        return
    cfg = kind_dir(settings, branch, mode, CONFIG)
    prof = kind_dir(settings, branch, mode, PROFILE)
    miss = kind_dir(settings, branch, mode, MISSIONS)
    pairs = [
        (cfg / f"{old}_{world}.cfg", cfg / f"{new}_{world}.cfg"),
        (prof / f"{old}_{world}", prof / f"{new}_{world}"),
        (miss / f"{old}.{world}", miss / f"{new}.{world}"),
    ]
    for src, dst in pairs:
        try:
            if src.exists() and not dst.exists():
                src.rename(dst)
        except OSError:
            pass  # занято процессом и т.п. — не критично, файлы создадутся заново
