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
    time_login: int = -1   # TimeLogin в db/globals.xml миссии; -1 — не трогать

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

    @property
    def world(self) -> str:
        return self.mission.rsplit(".", 1)[1] if "." in self.mission else ""

    def file_stem(self) -> str:
        """Имя файла пресета: <имя>_<карта> — одно имя допустимо на разных картах."""
        return _slug(f"{self.name}_{self.world}" if self.world else self.name)

    def path(self) -> Path:
        return PRESETS_DIR / f"{self.file_stem()}.json"

    def save(self) -> None:
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        new_path = self.path()
        new_path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # имя или карта изменились — файл переехал, старый убираем
        src = getattr(self, "_src", None)
        if src and Path(src) != new_path:
            try:
                Path(src).unlink(missing_ok=True)
            except OSError:
                pass
        self._src = new_path

    def delete(self) -> None:
        try:
            Path(getattr(self, "_src", self.path())).unlink(missing_ok=True)
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
                    p = cls.from_dict(json.loads(f.read_text(encoding="utf-8")))
                    p._src = f  # откуда загружен — для переезда файла при переименовании
                    out.append(p)
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

@dataclass
class ImportReport:
    """Что удалось распознать в батнике — показывается пользователю перед импортом."""
    preset: "ServerPreset"
    has_config: bool = False
    has_mission: bool = False
    has_profiles: bool = False
    n_mods: int = 0
    n_server_mods: int = 0
    client_found: bool = False


_EXE_RE = re.compile(
    r'(?:^|\s)(?:start\s+(?:"[^"]*"\s+)?)?"?(?P<exe>[^"\s]*?(?P<kind>dayzserver_x64|dayzdiag_x64|dayz_x64)\.exe)"?(?P<rest>[^\r\n]*)',
    re.IGNORECASE,
)
_ARG_RE = re.compile(r'-(?P<name>[A-Za-z]\w*)(?:=(?P<val>"[^"]*"|\S+))?')
_SET_RE = re.compile(r'^\s*@?SET\s+"?(?P<var>[\w~]+)=(?P<val>[^"\r\n]*)"?\s*$',
                     re.IGNORECASE | re.MULTILINE)


def _read_bat(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1251", errors="replace")


def _expand_vars(line: str, variables: dict[str, str], bat_dir: Path) -> str:
    """Подставляет %ПЕРЕМЕННЫЕ% (имена любые) и %~dp0."""
    line = re.sub(r"%~dp0", lambda _m: str(bat_dir) + "\\", line, flags=re.IGNORECASE)
    for _ in range(10):  # переменные могут ссылаться друг на друга
        def repl(m: re.Match) -> str:
            return variables.get(m.group(1).upper(), m.group(0))
        new = re.sub(r"%(\w+)%", repl, line)
        if new == line:
            break
        line = new
    return line


def _split_mods(value: str) -> list[str]:
    return [x.strip() for x in value.strip().strip('"').split(";") if x.strip()]


def _parse_launch_args(rest: str) -> dict[str, str | None]:
    """Аргументы строки запуска: имя (в нижнем регистре) -> значение или None."""
    out: dict[str, str | None] = {}
    for m in _ARG_RE.finditer(rest):
        val = m.group("val")
        if val is not None:
            val = val.strip('"')
        out[m.group("name").lower()] = val
    return out


def _apply_params(args: dict[str, str | None], target_params: dict, extra: list[str]) -> None:
    """Раскладывает аргументы по справочнику параметров; незнакомое — в extra."""
    from .params import PARAMS, FLAG, SWITCH, INT
    known = {s.name.lower(): s for s in PARAMS}
    handled = {"server", "connect", "port", "mod", "servermod", "config",
               "mission", "profiles"}
    for name, val in args.items():
        if name in handled:
            continue
        spec = known.get(name)
        if spec is None:
            extra.append(f"-{name}" + (f"={val}" if val is not None else ""))
            continue
        if spec.ptype == FLAG:
            if val is None or val != "0":
                target_params[spec.name] = True
        elif spec.ptype == SWITCH:
            target_params[spec.name] = (val != "0") if val is not None else True
        elif spec.ptype == INT:
            try:
                target_params[spec.name] = int(val)
            except (TypeError, ValueError):
                pass
        else:
            if val:
                target_params[spec.name] = val


def import_bat(path: Path) -> ImportReport | None:
    """Разбирает батник по строкам запуска экзешников.

    Не полагается на имена переменных: собирает все SET, подставляет их в
    строку запуска и парсит готовые аргументы -config/-mission/-mod и т.д.
    """
    text = _read_bat(path)
    if text is None:
        return None

    variables = {m.group("var").upper(): m.group("val").strip()
                 for m in _SET_RE.finditer(text)}

    server_args: dict[str, str | None] | None = None
    server_kind = ""
    client_args: dict[str, str | None] | None = None
    client_kind = ""

    for raw_line in text.splitlines():
        line = raw_line.strip()
        low = line.lower()
        if not line or low.startswith(("rem", "@rem", "::")) or "taskkill" in low:
            continue
        m = _EXE_RE.search(_expand_vars(line, variables, path.parent))
        if not m:
            continue
        kind = m.group("kind").lower()
        args = _parse_launch_args(m.group("rest"))
        if kind == "dayzserver_x64" or "server" in args:
            if server_args is None:
                server_args, server_kind = args, kind
        else:
            if client_args is None:
                client_args, client_kind = args, kind

    if server_args is None and client_args is None:
        return None

    preset = ServerPreset(name=path.stem)
    report = ImportReport(preset=preset)

    if server_args is not None:
        preset.mode = MODE_DIAG if server_kind == "dayzdiag_x64" else MODE_DEDICATED
        preset.server_config = server_args.get("config") or ""
        preset.mission = server_args.get("mission") or ""
        preset.profiles = server_args.get("profiles") or ""
        if server_args.get("port"):
            try:
                preset.port = int(server_args["port"])
            except ValueError:
                pass
        preset.mods = _split_mods(server_args.get("mod") or "")
        preset.server_mods = _split_mods(server_args.get("servermod") or "")
        extra: list[str] = []
        _apply_params(server_args, preset.params_server, extra)
        preset.extra_server = " ".join(extra)

    if client_args is not None:
        report.client_found = True
        preset.client_use_diag = client_kind == "dayzdiag_x64"
        connect = client_args.get("connect") or ""
        if ":" in connect:
            try:
                preset.port = int(connect.rsplit(":", 1)[1])
            except ValueError:
                pass
        if server_args is None:
            # батник только с клиентом: моды и режим берём из строки клиента
            preset.mods = _split_mods(client_args.get("mod") or "")
            if preset.client_use_diag:
                preset.mode = MODE_DIAG
            preset.launch_server = False
        extra_c: list[str] = []
        _apply_params(client_args, preset.params_client, extra_c)
        preset.extra_client = " ".join(extra_c)
    else:
        preset.launch_client = False

    report.has_config = bool(preset.server_config)
    report.has_mission = bool(preset.mission)
    report.has_profiles = bool(preset.profiles)
    report.n_mods = len(preset.mods)
    report.n_server_mods = len(preset.server_mods)
    return report


def import_bats_from_dir(directory: Path) -> list[ImportReport]:
    out = []
    if directory.is_dir():
        for f in sorted(directory.glob("*.bat")):
            r = import_bat(f)
            if r:
                out.append(r)
    return out
