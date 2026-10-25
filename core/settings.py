"""Глобальные настройки приложения (config/settings.json)."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

def _res_dir() -> Path:
    """Папка встроенных ресурсов: data, lang, иконка. Только чтение.

    В собранном виде PyInstaller распаковывает их к себе и кладёт путь в
    sys._MEIPASS; из исходников это просто корень проекта.
    """
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else Path(__file__).resolve().parent.parent


def _app_dir() -> Path:
    """Папка пользовательских данных: настройки, пресеты, загрузки.

    Из исходников — корень проекта, как было. В собранном виде она обязана
    лежать вне установки: папку программы обновление перезаписывает целиком, а
    в Program Files ещё и писать нельзя без прав администратора.

    Портативный режим: если рядом с exe есть папка config, работаем в ней —
    так приложение можно носить на флешке и держать несколько независимых
    копий. Иначе — %APPDATA%\\KR_QTS.
    """
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent.parent
    near_exe = Path(sys.executable).resolve().parent
    if (near_exe / "config").is_dir():
        return near_exe
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "KR_QTS" if appdata else near_exe


RES_DIR = _res_dir()
APP_DIR = _app_dir()
CONFIG_DIR = APP_DIR / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
PRESETS_DIR = CONFIG_DIR / "presets"
MOD_PRESETS_DIR = CONFIG_DIR / "mod_presets"
MOD_SOURCES_FILE = CONFIG_DIR / "mod_sources.json"
MOD_DEPENDENCIES_FILE = CONFIG_DIR / "mod_dependencies.json"
# ключ мода -> id воркшопа: помним по всем стим-модам, которые видели. Нужен,
# когда мод отписали: зависимость по ключу остаётся, а id взять уже неоткуда
MOD_WORKSHOP_IDS_FILE = CONFIG_DIR / "mod_workshop_ids.json"
MOD_FLAGS_FILE = CONFIG_DIR / "mod_flags.json"
MOD_FLAG_DEFS_FILE = CONFIG_DIR / "mod_flag_defs.json"

STABLE = "stable"
EXPERIMENTAL = "experimental"


CLIENT_EXE = "DayZ_x64.exe"
SERVER_EXE = "DayZServer_x64.exe"

# поле настроек -> исполняемый файл, по которому опознаётся установка
ROOT_EXES: dict[str, str] = {
    "client_stable": CLIENT_EXE,
    "client_exp": CLIENT_EXE,
    "server_stable": SERVER_EXE,
    "server_exp": SERVER_EXE,
}

# результаты check_path
PATH_OK = ""
PATH_MISSING = "missing"              # папки по пути нет
PATH_NOT_INSTALLED = "not_installed"  # папка есть, но программы в ней нет


def is_install(path: str, exe: str) -> bool:
    """Является ли папка установкой игры/сервера.

    Проверяется исполняемый файл, а не просто существование папки: после
    удаления игры из Steam каталог часто остаётся — Steam не удаляет его, если
    внутри есть чужое содержимое (наши симлинки filepatching, serverDZ.cfg,
    ban.txt, mpmissions). Такой остаток установкой не является.
    """
    return bool(path) and (Path(path) / exe).is_file()


def check_path(key: str, value: str) -> str:
    """Проверка пути из настроек: PATH_OK / PATH_MISSING / PATH_NOT_INSTALLED.

    Пустое поле ошибкой не считается — компонент просто не установлен, это
    нормальное состояние. Путь автоматически не стирается: папка может быть
    временно недоступна (внешний диск, сеть), и терять из-за этого настройку
    нельзя — пользователю показывается предупреждение.
    """
    if not value:
        return PATH_OK
    p = Path(value)
    if not p.is_dir():
        return PATH_MISSING
    exe = ROOT_EXES.get(key)
    if exe and not (p / exe).is_file():
        return PATH_NOT_INSTALLED
    return PATH_OK


def split_flags(text: str) -> list[str]:
    r"""Разбивает строку флагов запаковки на аргументы.

    Своё, а не shlex, потому что ни один его режим здесь не годится:

        shlex(posix=True)   +K=D:\keys\KR.biprivatekey -> +K=D:keysKR.biprivatekey
                            обратный слэш считается экранирующим, и путь
                            молча теряет разделители — pboProject получает
                            несуществующий файл и подпись не делается;
        shlex(posix=False)  +K="D:\my keys\KR.biprivatekey" -> два аргумента
                            кавычки группируют только в начале слова.

    Здесь: пробелы разделяют, кавычки группируют где угодно, обратный слэш —
    обычный знак. Кавычки в результат не попадают: это разметка строки, а не
    часть пути.
    """
    args: list[str] = []
    current: list[str] = []
    quoted = False
    for ch in text:
        if ch == '"':
            quoted = not quoted
        elif ch.isspace() and not quoted:
            if current:
                args.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        args.append("".join(current))
    return args


def find_pbo_project_exe(mikero_tools: str) -> str:
    """Путь к pboProject.exe по настройке mikero_tools (папка или сам .exe).

    Вынесено из Settings отдельной функцией — нужна и для ещё не сохранённого
    значения из формы настроек (проверка «pboProject реально установлен»).
    """
    p = Path(mikero_tools)
    if p.suffix.lower() == ".exe":
        return str(p)
    for cand in (p / "bin" / "pboProject.exe", p / "pboProject.exe"):
        if cand.is_file():
            return str(cand)
    return str(p / "bin" / "pboProject.exe")


# Найденные программы помним: обход папки стоит около 120 мс, а спрашивают
# путь на каждую сборку и на каждое открытие настроек.
_TOOL_CACHE: dict[tuple[str, str], str] = {}

# Куда не ходим: служебные папки репозитория и промежуточные сборки
# PyInstaller. В build/ лежат копии тех же exe, но несобранные до конца —
# на машине с репозиторием их шесть штук против двух настоящих.
_SKIP_DIRS = {".git", ".svn", "__pycache__", "node_modules", "build", "venv"}


def find_tool(root: str, name: str) -> str:
    """Ищет программу по имени внутри указанной папки.

    Человек указывает одну общую папку с инструментами, а не путь к каждому
    exe: у Project Builder консольная и оконная половины лежат в разных
    и знать эту раскладку — не его забота.

    Порядок: сам указанный exe -> привычные места -> обход вглубь. Из
    найденного выбираем то, что лежит в dist (настоящая раздача), а среди
    равных — самое свежее.
    """
    value = (root or "").strip()
    if not value:
        return ""
    p = Path(value)
    if p.suffix.lower() == ".exe":
        # указали конкретный exe: если спрашивают его же — отдаём, иначе
        # ищем соседа от его папки
        if p.name.lower() == name.lower():
            return str(p)
        # Сосед в той же папке — установка лежит плоско, все exe рядом.
        # Шаг через родителя нужен только старой раздаче, где у каждой
        # программы была своя подпапка.
        if (p.parent / name).is_file():
            return str(p.parent / name)
        p = p.parent.parent if p.parent.parent.is_dir() else p.parent
    key = (str(p), name.lower())
    cached = _TOOL_CACHE.get(key)
    if cached and Path(cached).is_file():
        return cached
    for quick in (p / name, p / "dist" / Path(name).stem / name):
        if quick.is_file():
            _TOOL_CACHE[key] = str(quick)
            return str(quick)
    if not p.is_dir():
        return ""
    found = _walk_for(p, name)
    if found:
        _TOOL_CACHE[key] = found
    return found


def _walk_for(root: Path, name: str, depth: int = 6) -> str:
    """Обход вглубь с отсевом служебных папок. Пусто — не нашли."""
    best: tuple[int, float, str] | None = None
    stack = [(root, 0)]
    target = name.lower()
    while stack:
        folder, level = stack.pop()
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir():
                    if (level < depth and entry.name.lower() not in _SKIP_DIRS
                            and not entry.name.startswith(".")):
                        stack.append((entry, level + 1))
                elif entry.name.lower() == target:
                    rank = 1 if "dist" in (q.lower() for q in entry.parts) else 0
                    stamp = entry.stat().st_mtime
                    if best is None or (rank, stamp) > (best[0], best[1]):
                        best = (rank, stamp, str(entry))
            except OSError:
                continue
    return best[2] if best else ""


# Консольная и оконная половины запаковщика в поставке «KR DevToolkit».
# С 25.10.2026 там единое правило имён: «Имя.exe» — командная строка,
# «Имя_GUI.exe» — окно. Прежние имена (ProjectBuilderCli.exe, krbuild-cli.exe)
# не ищем: те сборки сняты с поддержки, и найти старую вместо новой — значит
# молча паковать неизвестно чем. Пусть лучше скажет, что не нашёл.
PACKER_CLI_NAMES = ("ProjectBuilder.exe",)
PACKER_GUI_NAMES = ("ProjectBuilder_GUI.exe",)


# Запись установщика Dev Toolkit в реестре. Установка пользовательская, без
# прав администратора, поэтому ветка только HKCU. Идентификатор постоянный
# между версиями — это их договор с нами, а не найденная подробность.
TOOLKIT_UNINSTALL_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    r"\{6F0E3C47-2B7D-4C1A-9E55-8A1D3F6B2C90}_is1")


def _installed_toolkit() -> str:
    """Папка установки из реестра; пусто — не записана или не Windows."""
    try:
        import winreg
    except ImportError:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            TOOLKIT_UNINSTALL_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "InstallLocation")
    except OSError:
        return ""
    return str(value or "").strip()


def toolkit_home() -> str:
    """Куда установлен Dev Toolkit; пусто — не установлен.

    Сначала реестр: в установщике папку можно сменить, и тогда место по
    умолчанию пустое, а тулкит стоит где-то ещё. Место по умолчанию остаётся
    запасным — на случай, когда записи нет, а папка на месте: переставили
    руками, скопировали с другой машины.

    Спрашивать путь у человека не надо ни в том, ни в другом случае: это
    просьба сообщить нам то, что мы и так можем узнать.
    """
    found = _installed_toolkit()
    if found and (Path(found) / PACKER_CLI_NAMES[0]).is_file():
        return str(Path(found))
    base = os.environ.get("LOCALAPPDATA") or ""
    if not base:
        return ""
    home = Path(base) / "Programs" / "KR DevToolkit"
    return str(home) if home.is_dir() else ""


def toolkit_root(value: str) -> str:
    """Где искать инструменты: что указано в настройках, иначе установка."""
    return (value or "").strip() or toolkit_home()


def find_first_tool(root: str, names) -> str:
    """Первая из программ, которая нашлась в папке инструментов."""
    for name in names:
        found = find_tool(root, name)
        if found:
            return found
    return ""


def find_krbuild_cli(krbuild_exe: str) -> str:
    """Путь к консольной половине запаковщика по указанной папке."""
    return find_first_tool(krbuild_exe, PACKER_CLI_NAMES)


@dataclass
class Settings:
    language: str = "ru"
    first_run_done: bool = False
    project_prefix: str = ""   # префикс мододела/проекта — подставляется в hostname создаваемых серверов
    # Тёмная по умолчанию, а не «как в Windows»: программу держат открытой
    # рядом с игрой и редактором, а они тёмные — светлое окно посреди них
    # бьёт по глазам. Кому нужно иначе, меняет в настройках.
    theme: str = "dark"        # "light" | "dark" | "auto" (следовать теме Windows)

    # Корневые папки установок
    client_stable: str = ""
    client_exp: str = ""
    server_stable: str = ""
    server_exp: str = ""

    # Инструменты
    mikero_tools: str = ""      # папка Mikero (внутри bin/pboProject.exe) или прямой путь к exe
    dayz_tools: str = ""        # папка DayZ Tools
    dayz_tools_exp: str = ""    # папка DayZ Experimental Tools

    # Steam Workshop: папки content/221100 (может быть несколько библиотек)
    workshop_dirs: list[str] = field(default_factory=list)

    # Админские настройки (для модов-админок; интеграция — в будущих версиях)
    admin_steamids: list[str] = field(default_factory=list)
    admin_password: str = ""

    # Запаковка
    # Флаги pboProject. Знак обязателен у каждой опции (+ включено, - выключено):
    # голая буква читается парсером Mikero как путь. Исключение — формы с «=».
    # Отсутствие опции означает «взять текущее значение из настроек GUI», так
    # что задавать имеет смысл только осознанно выбранное.
    #
    # Чего здесь намеренно нет:
    #   -$ — управляет разрешением собирать pbo без префикса; при нём терялся
    #        $PBOPREFIX$ и мод паковался без префикса вообще;
    #   -W — в разных версиях это либо «warnings are errors», либо рабочий диск;
    #   +N — подробный лог, объём вывода огромен и заметно замедляет сборку;
    #   +R — не настройка пользователя, а обязательное условие, ставится в
    #        core/packer.py вместе с -E/-M.
    # -X — маски файлов, которые в pbo не попадают. «source» в списке не нужен:
    # папка ~source\ не инспектируется никогда. Следы обфускатора (.6w_pack,
    # .6w_obf, *_OBFCACHE) перечислены здесь для наглядности, но держатся не
    # этим списком: core/packer.py дописывает их к -X при каждой сборке, что
    # бы в настройках ни оказалось.
    pack_flags: str = (
        "-P -N +B -C -D -H -T +G -Q +Z -O -K "
        "-X=*.h,*.hpp,*.png,*.cpp,thumbs.db,*.dep,*.bak,*.log,*.pew,"
        "*.tga,*.bat,*.psd,*.cmd,*.mcr,*.fbx,*.max,*.blend,*.blend1,*.blend2,"
        "*.blend3,*.blend4,*.blend5,*.txa,.claude,"
        ".6w_pack,.6w_obf,.6w*,obfuscated_entities.json,*OBFCACHE*,"
        "hobf_pack.settings.json"
    )
    clean_meta: bool = True     # удалять *.meta в сорсах перед сборкой
    # Чем паковать: "pboproject" — Mikero, "krbuild" — [KR] Project Builder
    # программа из KR DevToolkit, зовём её exe). Движок выбирается один на
    # проект, а не на запуск: у обоих свой инкремент и общая папка temp, и
    # чередование заставило бы каждый пересобирать за другим.
    pack_tool: str = "pboproject"
    # Ключ подписи PBO (.biprivatekey). Один на проект и общий для обоих
    # движков: формат ключа чужой и одинаковый, а подписанные моды сервер
    # принимает по открытой половине из keys. Пусто — не подписываем.
    sign_key: str = ""
    # Папка Dev Toolkit. Пусто — Project Builder не настроен, выбор движка
    # предложит указать путь. В раздачу его не кладём: 61 МБ чужой программы.
    krbuild_exe: str = ""
    # Режим pboProject: "" — не перепаковывать, "normal" — инкрементально
    # (переиспользует temp), "full" — FullBuild, чистит temp и собирает всё
    pack_engine: str = "normal"
    repack_before_launch: bool = False   # перепаковывать изменённые локальные моды перед запуском

    # Общая папка загрузок (моды карт с GitHub); пусто — <папка программы>/downloads
    downloads_dir: str = ""

    # Папки с локальными модами (@папки собственных сборок)
    local_mods_dirs: list[str] = field(default_factory=list)

    # Положение мини-окна на экране — чтобы оно не прыгало в центр при каждом
    # сворачивании в трей; пусто — открыть там, где решит система
    mini_pos: list[int] = field(default_factory=list)

    # Папки скриптов на диске P:, подключённые ссылками для filepatching
    # (см. core/filepatch.py). Хранится исходный P:-путь, а не разрешённый:
    # цель вычисляется заново при каждой синхронизации.
    filepatch_links: list[str] = field(default_factory=list)

    # Моды, скрытые из списка вручную (ключ — folder_name.lower()); сама папка
    # мода/подписка на Steam остаётся нетронутой, мод просто не показывается
    excluded_mods: list[str] = field(default_factory=list)

    # Недавно выбранные папки сорсов — для боковой панели диалога выбора
    # (недативный Qt-диалог с мультивыбором своих «последних папок» не знает)
    recent_source_dirs: list[str] = field(default_factory=list)

    # Окна логов поверх остальных окон — раздельно для сервера и клиента:
    # поверх всего обычно держат одно из двух, второе в это время мешает
    # Окно сервера DayZ несёт ровно то же, что server_console.log, который мы
    # и так читаем. Прятать его можно без потери сведений, см. core/winhide.
    # Куда приложение кладёт свои файлы внутри корня клиента/сервера. Пути
    # относительные и независимые: у людей разные привычки в именах — profile
    # или profiles, mpmissions или mpmission. Пустая строка означает корень.
    # Одни и те же значения применяются ко всем четырём корням.
    path_config: str = "KR_Debug"
    path_profile: str = r"KR_Debug\profile"
    path_missions: str = r"KR_Debug\mpmissions"
    path_mods: str = r"KR_Debug\MODS"

    hide_server_window: bool = False
    # Как останавливать сервер и клиент: «soft» — попросить окна закрыться,
    # программа завершится своим порядком; «hard» — убить процесс сразу.
    # По умолчанию мягко: убийство обрывает сохранение на полуслове.
    stop_method: str = "soft"

    # Моды из мастерской перед запуском. Сервер, поднятый со старым модом,
    # ведёт себя необъяснимо, а недокачанный мод — это половина файлов;
    # проверка дешёвая (спрашиваем состояние самого Steam), поэтому включена.
    mod_update_before_launch: bool = True
    mod_update_method: str = "wait"      # wait — ждать Steam, steamcmd — качать
    mod_update_timeout_min: int = 30
    steamcmd_exe: str = ""
    # Только имя учётной записи: пароль SteamCMD запоминает сам после первого
    # ручного входа, и хранить его у себя нам незачем.
    steam_login: str = ""

    # RCon — разговор с работающим сервером (сообщения игрокам, список игроков).
    # Только для обычного сервера: в diag BattlEye выключен, а RCon живёт
    # внутри него. Остановить сервер этим нельзя — команды такой у DayZ нет,
    # см. core/rcon. Пароль лежит открытым текстом, потому что именно так его
    # читает BattlEye; он одноразовый и от локального тестового сервера.
    rcon_enabled: bool = True
    rcon_port: int = 2305
    rcon_password: str = ""      # пустой — создастся при первом запуске

    # Запуск вместе с Windows. Правда о состоянии — в реестре (см.
    # core/autostart), здесь лишь то, что человек выбрал в окне настроек:
    # ключ могли снять снаружи, и расхождение мы показываем честно.
    start_with_windows: bool = False
    # Каким показываться при запуске: window — обычным окном, tray — только
    # значком в трее, mini — мини-окном поверх остальных.
    start_mode: str = "window"
    # Что делает крестик главного окна. По умолчанию прячет программу в
    # мини-окно: в цикле отладки мода она нужна постоянно. Кому она нужна
    # только на время запуска, тому это мешает — крестик должен закрывать.
    close_quits: bool = False

    log_on_top_server: bool = False
    log_on_top_client: bool = False

    # Проверять новую версию на GitHub при запуске. Сетевой запрос на старте
    # без возможности отключить — то, за что справедливо ругают, поэтому галка.
    check_updates: bool = True
    # Высота списка модов в пикселях: человек тянет его за нижний край, и
    # подобранный размер должен пережить перезапуск.
    mods_list_height: int = 192
    # Ширина панели разделов: 48 — только значки, больше — с подписями.
    nav_width: int = 48
    # Размер главного окна. 0 — ещё не запоминали, открываем по умолчанию.
    window_w: int = 0
    window_h: int = 0
    window_max: bool = False
    # Отвечать ли на команды из канала (qtsctl, сторонние инструменты).
    # По умолчанию да: канал персональный, чужой пользователь до него не
    # достучится. Выключатель нужен тем, кто не хочет, чтобы программой можно
    # было управлять помимо окна.
    external_control: bool = True
    # Версия, чейнджлог которой пользователь уже открывал: пункт в навигации
    # останется, но окно само не откроется второй раз
    update_seen: str = ""

    # Пресет, с которым работали в прошлый раз (его file_stem). Пусто — ещё
    # не выбирали, тогда берётся первый по списку. Хранится здесь, а не в
    # самом пресете: это свойство рабочего места, а не сервера.
    last_preset: str = ""

    # Steam Web API ключ (steamcommunity.com/dev/apikey) — для зависимостей модов;
    # пусто — зависимости читаются со страницы воркшопа
    steam_api_key: str = ""

    def client_root(self, branch: str) -> str:
        return self.client_exp if branch == EXPERIMENTAL else self.client_stable

    def server_root(self, branch: str) -> str:
        return self.server_exp if branch == EXPERIMENTAL else self.server_stable

    def pbo_project_exe(self) -> str:
        return find_pbo_project_exe(self.mikero_tools)

    def krbuild_cli(self) -> str:
        """Путь к ProjectBuilder.exe; пусто — движок не настроен.

        Пустое поле — не «не настроено», а «где поставили, там и бери»:
        установщик кладёт тулкит в одно и то же место, и заставлять указывать
        его руками значило бы просить человека ввести известное.
        """
        root = toolkit_root(self.krbuild_exe)
        return find_krbuild_cli(root) if root else ""

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls) -> Settings:
        if SETTINGS_FILE.is_file():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
                return cls(**{k: v for k, v in data.items() if k in known})
            except (OSError, json.JSONDecodeError, TypeError):
                pass
        return cls()

    def lift_sign_key(self) -> bool:
        """Переносит ключ подписи из флагов pboProject в своё поле.

        Раньше он жил внутри строки флагов (+K=путь) и правился в окне
        настроек pboProject. Теперь это общая настройка: ключ один, а движков
        два. Старые настройки переносим один раз и молча — человек про эту
        перестановку знать не обязан, он просто видит путь там, где искал.
        """
        if self.sign_key or "K=" not in self.pack_flags:
            return False
        parts = split_flags(self.pack_flags)
        kept, found = [], ""
        for token in parts:
            head = token[1:3] if token[:1] in "+-" else token[:2]
            if head.upper() == "K=":
                found = token.partition("=")[2]
                continue
            kept.append(token)
        if not found:
            return False
        self.sign_key = found
        self.pack_flags = " ".join(kept)
        return True
