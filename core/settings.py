"""Глобальные настройки приложения (config/settings.json)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = APP_DIR / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
PRESETS_DIR = CONFIG_DIR / "presets"
MOD_PRESETS_DIR = CONFIG_DIR / "mod_presets"
MOD_SOURCES_FILE = CONFIG_DIR / "mod_sources.json"

STABLE = "stable"
EXPERIMENTAL = "experimental"


@dataclass
class Settings:
    language: str = "ru"
    first_run_done: bool = False

    # Корневые папки установок
    client_stable: str = ""
    client_exp: str = ""
    server_stable: str = ""
    server_exp: str = ""

    # Инструменты
    mikero_tools: str = ""      # папка Mikero (внутри bin/pboProject.exe) или прямой путь к exe
    dayz_tools: str = ""        # папка DayZ Tools

    # Steam Workshop: папки content/221100 (может быть несколько библиотек)
    workshop_dirs: list[str] = field(default_factory=list)

    # Админские настройки (для модов-админок; интеграция — в будущих версиях)
    admin_steamids: list[str] = field(default_factory=list)
    admin_password: str = ""

    # Запаковка
    pack_flags: str = "-P -K"   # доп. флаги pboProject
    clean_meta: bool = True     # удалять *.meta в сорсах перед сборкой

    # Общая папка загрузок (моды карт с GitHub); пусто — <папка программы>/downloads
    downloads_dir: str = ""

    # Папки с локальными модами (@папки собственных сборок)
    local_mods_dirs: list[str] = field(default_factory=list)

    # Steam Web API ключ (steamcommunity.com/dev/apikey) — для зависимостей модов;
    # пусто — зависимости читаются со страницы воркшопа
    steam_api_key: str = ""

    def client_root(self, branch: str) -> str:
        return self.client_exp if branch == EXPERIMENTAL else self.client_stable

    def server_root(self, branch: str) -> str:
        return self.server_exp if branch == EXPERIMENTAL else self.server_stable

    def pbo_project_exe(self) -> str:
        p = Path(self.mikero_tools)
        if p.suffix.lower() == ".exe":
            return str(p)
        for cand in (p / "bin" / "pboProject.exe", p / "pboProject.exe"):
            if cand.is_file():
                return str(cand)
        return str(p / "bin" / "pboProject.exe")

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls) -> "Settings":
        if SETTINGS_FILE.is_file():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
                return cls(**{k: v for k, v in data.items() if k in known})
            except (OSError, json.JSONDecodeError, TypeError):
                pass
        return cls()
