"""Реестр модов: Steam Workshop + локальные, junction-подключение, .bikey."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .settings import Settings, MOD_SOURCES_FILE

SOURCE_STEAM = "steam"
SOURCE_LOCAL = "local"


@dataclass
class ModInfo:
    name: str                 # отображаемое имя, оно же имя @папки при подключении
    path: str                 # реальная папка мода
    source: str               # steam | local
    workshop_id: str = ""
    has_keys: bool = False
    duplicate_of_steam: str = ""   # id, если локальный мод дублирует воркшопный
    sources: list[str] = field(default_factory=list)  # папки сорсов (для запаковки)

    @property
    def folder_name(self) -> str:
        n = self.name if self.name.startswith("@") else "@" + self.name
        # символы, недопустимые в имени папки Windows
        return re.sub(r'[<>:"/\\|?*]', "_", n)


def _read_meta_name(mod_dir: Path) -> str:
    """Имя стим-мода из meta.cpp (запасной вариант — mod.cpp)."""
    for fname in ("meta.cpp", "mod.cpp"):
        f = mod_dir / fname
        if f.is_file():
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                m = re.search(r'name\s*=\s*"([^"]+)"', text)
                if m:
                    return m.group(1).strip()
            except OSError:
                pass
    return ""


def _is_link(p: Path) -> bool:
    """True для junction/symlink."""
    try:
        return p.is_junction() or p.is_symlink()  # Python 3.12+: is_junction
    except AttributeError:
        try:
            return p.is_symlink() or bool(p.stat(follow_symlinks=False).st_reparse_tag)
        except (OSError, AttributeError):
            return False


class ModRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.mods: dict[str, ModInfo] = {}   # ключ — folder_name без учёта регистра

    # ------------------------------------------------------------- сканирование

    def scan(self) -> list[ModInfo]:
        self.mods = {}
        sources_map = self._load_sources_map()

        # 1. Steam Workshop
        for wdir in self.settings.workshop_dirs:
            wpath = Path(wdir)
            if not wpath.is_dir():
                continue
            for item in wpath.iterdir():
                if not item.is_dir():
                    continue
                name = _read_meta_name(item) or item.name
                mod = ModInfo(
                    name=name, path=str(item), source=SOURCE_STEAM,
                    workshop_id=item.name, has_keys=(item / "keys").is_dir() or (item / "Keys").is_dir(),
                )
                self.mods[mod.folder_name.lower()] = mod

        # 2. Локальные @папки в корнях клиента и сервера (junction пропускаем —
        #    это наши же ссылки на воркшоп или на другие локальные моды)
        roots = [self.settings.client_stable, self.settings.client_exp,
                 self.settings.server_stable, self.settings.server_exp]
        for root in roots:
            rpath = Path(root) if root else None
            if not rpath or not rpath.is_dir():
                continue
            for item in rpath.iterdir():
                if not item.name.startswith("@") or not item.is_dir() or _is_link(item):
                    continue
                key = item.name.lower()
                dup = ""
                if key in self.mods and self.mods[key].source == SOURCE_STEAM:
                    dup = self.mods[key].workshop_id  # локальный приоритетнее, помечаем дубль
                mod = ModInfo(
                    name=item.name.lstrip("@"), path=str(item), source=SOURCE_LOCAL,
                    has_keys=(item / "keys").is_dir() or (item / "Keys").is_dir(),
                    duplicate_of_steam=dup,
                )
                self.mods[key] = mod

        # 3. Привязка сорсов
        for key, mod in self.mods.items():
            if key in sources_map:
                mod.sources = sources_map[key]

        return self.all()

    def all(self) -> list[ModInfo]:
        return sorted(self.mods.values(), key=lambda m: m.name.lower())

    def get(self, name: str) -> ModInfo | None:
        n = name if name.startswith("@") else "@" + name
        return self.mods.get(n.lower())

    # ------------------------------------------------------------- сорсы модов

    def _load_sources_map(self) -> dict[str, list[str]]:
        if MOD_SOURCES_FILE.is_file():
            try:
                return json.loads(MOD_SOURCES_FILE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def save_sources(self) -> None:
        MOD_SOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {k: m.sources for k, m in self.mods.items() if m.sources}
        MOD_SOURCES_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------- подключение

    def ensure_available(self, mod: ModInfo, root: str) -> tuple[bool, str]:
        """Гарантирует, что мод доступен из корня root под именем @Имя.

        Если мод лежит в другом месте — создаёт junction. Возвращает (ok, сообщение).
        """
        rpath = Path(root)
        link = rpath / mod.folder_name
        target = Path(mod.path)

        if link.exists():
            try:
                if link.resolve() == target.resolve():
                    return True, ""
            except OSError:
                pass
            if _is_link(link):
                # битая или чужая ссылка — пересоздаём
                try:
                    link.rmdir()
                except OSError as e:
                    return False, f"{link}: {e}"
            else:
                # настоящая папка с таким именем уже есть — используем её
                return True, ""
        try:
            res = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if res.returncode != 0:
                return False, (res.stderr or res.stdout).strip()
        except OSError as e:
            return False, str(e)
        return True, ""

    def copy_keys(self, mod: ModInfo, server_root: str) -> None:
        """Копирует .bikey мода в keys сервера (для verifySignatures)."""
        dest = Path(server_root) / "keys"
        if not dest.is_dir():
            dest = Path(server_root) / "Keys"
        if not dest.is_dir():
            return
        for kdir in (Path(mod.path) / "keys", Path(mod.path) / "Keys"):
            if kdir.is_dir():
                for key in kdir.glob("*.bikey"):
                    try:
                        shutil.copy2(key, dest / key.name)
                    except OSError:
                        pass
