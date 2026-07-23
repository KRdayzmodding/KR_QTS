"""Пресеты сервера и пресеты модов + импорт из старых батников."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .settings import PRESETS_DIR, MOD_PRESETS_DIR, STABLE

MODE_DEDICATED = "dedicated"
MODE_DIAG = "diag"


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_")
    return s or "preset"


@dataclass
class ServerPreset:
    name: str = "Новый пресет"
    mode: str = MODE_DIAG                  # dedicated | diag
    branch: str = STABLE                   # ветка по умолчанию
    client_use_diag: bool = False          # в dedicated-режиме клиент = DayZDiag

    # Пути (относительно корня клиента или абсолютные)
    server_config: str = ""
    mission: str = ""
    profiles: str = ""
    port: int = 2302

    # Параметры запуска: имя -> значение (только явно выставленные)
    params_server: dict = field(default_factory=dict)
    params_client: dict = field(default_factory=dict)
    extra_server: str = ""                 # доп. аргументы свободным текстом
    extra_client: str = ""

    # Моды: имена из реестра модов; порядок = порядок загрузки
    mods: list[str] = field(default_factory=list)          # -mod (клиент + сервер)
    server_mods: list[str] = field(default_factory=list)   # -serverMod

    # Состояние галок запуска
    launch_server: bool = True
    launch_client: bool = True

    def path(self) -> Path:
        return PRESETS_DIR / f"{_slug(self.name)}.json"

    def save(self) -> None:
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        self.path().write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def delete(self) -> None:
        try:
            self.path().unlink(missing_ok=True)
        except OSError:
            pass

    @classmethod
    def from_dict(cls, data: dict) -> "ServerPreset":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def load_all(cls) -> list["ServerPreset"]:
        out = []
        if PRESETS_DIR.is_dir():
            for f in sorted(PRESETS_DIR.glob("*.json")):
                try:
                    out.append(cls.from_dict(json.loads(f.read_text(encoding="utf-8"))))
                except (OSError, json.JSONDecodeError, TypeError):
                    continue
        return out


@dataclass
class ModPreset:
    """Именованный набор модов — шаблон для быстрого применения к пресету сервера."""
    name: str = "Набор модов"
    mods: list[str] = field(default_factory=list)
    server_mods: list[str] = field(default_factory=list)

    def save(self) -> None:
        MOD_PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        (MOD_PRESETS_DIR / f"{_slug(self.name)}.json").write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load_all(cls) -> list["ModPreset"]:
        out = []
        if MOD_PRESETS_DIR.is_dir():
            for f in sorted(MOD_PRESETS_DIR.glob("*.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    out.append(cls(name=data.get("name", f.stem),
                                   mods=data.get("mods", []),
                                   server_mods=data.get("server_mods", [])))
                except (OSError, json.JSONDecodeError):
                    continue
        return out


# ---------------------------------------------------------------- импорт батников

_BAT_VARS = {
    "MODS": ("mods",),
    "SEVERSIDEMODS": ("server_mods",),
    "SERVERSIDEMODS": ("server_mods",),
    "SERVERCFG": ("server_config",),
    "SERVERDZCFG": ("server_config",),
    "MISSION": ("mission",),
    "MISSIONPATH": ("mission",),
    "PROFILES": ("profiles",),
}


def import_bat(path: Path) -> ServerPreset | None:
    """Разбирает старый батник запуска и строит из него пресет."""
    try:
        text = path.read_text(encoding="cp1251", errors="replace")
    except OSError:
        return None

    preset = ServerPreset(name=path.stem)
    found_any = False

    for m in re.finditer(r'SET\s+"?(\w+)=([^"\r\n]*)"?', text, re.IGNORECASE):
        var, value = m.group(1).upper(), m.group(2).strip()
        if var in ("MODS", "SEVERSIDEMODS", "SERVERSIDEMODS"):
            mods = [x.strip() for x in value.split(";") if x.strip()]
            setattr(preset, _BAT_VARS[var][0], mods)
            found_any = True
        elif var in _BAT_VARS:
            setattr(preset, _BAT_VARS[var][0], value)
            found_any = True
        elif var == "LOCALHOST" and ":" in value:
            try:
                preset.port = int(value.rsplit(":", 1)[1])
            except ValueError:
                pass

    if not found_any:
        return None

    low = text.lower()
    if "dayzdiag_x64.exe" in low and "-server" in low:
        preset.mode = MODE_DIAG
    elif "dayzserver_x64.exe" in low:
        preset.mode = MODE_DEDICATED
        preset.client_use_diag = "dayzdiag_x64.exe" in low

    # Типовые ключи из батников переносим в параметры
    for pname, target in (
        ("filePatching", "filepatching"), ("battleye", "battleye"),
        ("newErrorsAreWarnings", "newerrorsarewarnings"), ("doActionLog", "doactionlog"),
    ):
        m = re.search(rf"-{target}(?:=(\d))?", low)
        if m:
            val = m.group(1)
            preset.params_server[pname] = bool(int(val)) if val is not None else True
    m = re.search(r"-scrdef=(\w+)", low)
    if m:
        preset.params_server["scrDef"] = m.group(1).upper()
    if "-dologs" in low:
        preset.params_server["doLogs"] = True
    if "-nopause" in low:
        preset.params_server["noPause"] = True
        preset.params_client["noPause"] = True

    # Клиенту — те же diag-флаги, что были в строке клиента (упрощённо: копия серверных)
    for k in ("filePatching", "battleye", "newErrorsAreWarnings"):
        if k in preset.params_server:
            preset.params_client[k] = preset.params_server[k]

    return preset


def import_bats_from_dir(directory: Path) -> list[ServerPreset]:
    out = []
    if directory.is_dir():
        for f in sorted(directory.glob("*.bat")):
            p = import_bat(f)
            if p:
                out.append(p)
    return out
