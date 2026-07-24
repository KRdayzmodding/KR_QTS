"""Реестр модов: Steam Workshop + локальные, junction-подключение, .bikey."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .settings import Settings, MOD_SOURCES_FILE

SOURCE_STEAM = "steam"
SOURCE_LOCAL = "local"
SOURCE_GITHUB = "github"  # скачан приложением в KR_Debug/mods_dl


@dataclass
class ModInfo:
    name: str                 # отображаемое имя, оно же имя @папки при подключении
    path: str                 # реальная папка мода
    source: str               # steam | local | github
    group: str = ""           # группа в дереве: Steam / GitHub / имя папки
    workshop_id: str = ""
    has_keys: bool = False
    duplicate_of_steam: str = ""   # id, если локальный мод дублирует воркшопный
    sources: list[str] = field(default_factory=list)  # папки сорсов (для запаковки)
    problem: str = ""          # причина невалидности (нет addons/.pbo и т.п.), пусто — всё ок
    size_bytes: int = 0        # суммарный размер папки мода на диске
    pbo_names: list[str] = field(default_factory=list)  # имена .pbo в addons

    @property
    def valid(self) -> bool:
        return not self.problem

    @property
    def pbo_count(self) -> int:
        return len(self.pbo_names)

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


def format_size(n: int) -> str:
    size = float(n)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ГБ"


def scan_mod_stats(mod_dir: Path) -> tuple[list[str], int]:
    """Имена .pbo в addons (топ-уровень) и суммарный размер всей папки мода."""
    pbo_names: list[str] = []
    try:
        for child in mod_dir.iterdir():
            if child.is_dir() and child.name.lower() == "addons":
                pbo_names = sorted(f.name for f in child.iterdir()
                                   if f.is_file() and f.suffix.lower() == ".pbo")
                break
    except OSError:
        pass
    total = 0
    try:
        for root, _dirs, files in os.walk(mod_dir):
            for fn in files:
                try:
                    total += os.path.getsize(os.path.join(root, fn))
                except OSError:
                    pass
    except OSError:
        pass
    return pbo_names, total


def validate_mod_dir(p: Path) -> str:
    """Проверка правил локального мода. Возвращает текст проблемы или пустую строку.

    Правила: имя с @, внутри папка addons с .pbo, никаких не-ASCII символов.
    """
    from .i18n import tr
    if not p.name.startswith("@"):
        return tr("mods.val_at", "{n}: имя папки должно начинаться с @", n=p.name)
    if not all(ord(c) < 128 for c in p.name):
        return tr("mods.val_ascii",
                  "{n}: в имени папки недопустимы русские символы", n=p.name)
    addons = None
    for child in p.iterdir() if p.is_dir() else []:
        if child.is_dir() and child.name.lower() == "addons":
            addons = child
            break
    if addons is None:
        return tr("mods.val_addons", "{n}: внутри нет папки addons", n=p.name)
    if not any(f.suffix.lower() == ".pbo" for f in addons.iterdir() if f.is_file()):
        return tr("mods.val_pbo", "{n}: в addons нет ни одного .pbo", n=p.name)
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
                pbo_names, size_bytes = scan_mod_stats(item)
                mod = ModInfo(
                    name=name, path=str(item), source=SOURCE_STEAM, group="Steam",
                    workshop_id=item.name, has_keys=(item / "keys").is_dir() or (item / "Keys").is_dir(),
                    pbo_names=pbo_names, size_bytes=size_bytes,
                )
                self.mods[mod.folder_name.lower()] = mod

        # 2. Локальные @папки в корнях клиента и сервера (junction пропускаем —
        #    это наши же ссылки на воркшоп или на другие локальные моды),
        #    настроенные папки локальных модов и скачанные с GitHub
        from .layout import mods_dl_dir
        roots = [self.settings.client_stable, self.settings.client_exp,
                 self.settings.server_stable, self.settings.server_exp]
        scan_dirs: list[tuple[Path, str, str]] = []   # (папка, источник, группа)
        for root in roots:
            if root and Path(root).is_dir():
                scan_dirs.append((Path(root), SOURCE_LOCAL, Path(root).name))
        singles: list[tuple[Path, str, str]] = []     # одиночные @папки-моды
        for d in self.settings.local_mods_dirs:
            p = Path(d) if d else None
            if not p or not p.is_dir():
                continue
            if p.name.startswith("@"):
                singles.append((p, SOURCE_LOCAL, p.parent.name))
            else:
                scan_dirs.append((p, SOURCE_LOCAL, p.name))
        dl = mods_dl_dir(self.settings)
        if dl.is_dir():
            scan_dirs.append((dl, SOURCE_GITHUB, "GitHub"))

        def _add_local(item: Path, source: str, group: str) -> None:
            key = item.name.lower()
            dup = ""
            if key in self.mods and self.mods[key].source == SOURCE_STEAM:
                dup = self.mods[key].workshop_id  # локальный приоритетнее, помечаем дубль
            pbo_names, size_bytes = scan_mod_stats(item)
            self.mods[key] = ModInfo(
                name=item.name.lstrip("@"), path=str(item), source=source, group=group,
                has_keys=(item / "keys").is_dir() or (item / "Keys").is_dir(),
                duplicate_of_steam=dup,
                problem=validate_mod_dir(item),  # проверяется при каждом скане
                pbo_names=pbo_names, size_bytes=size_bytes,
            )

        for rpath, source, group in scan_dirs:
            for item in rpath.iterdir():
                # is_dir() уже возвращает False для битых ссылок — отдельно
                # проверять _is_link не нужно, а рабочие junction-ссылки на
                # реальные сборки (частый способ организовать локальные моды)
                # пропускать не должны
                if not item.name.startswith("@") or not item.is_dir():
                    continue
                _add_local(item, source, group)
        for item, source, group in singles:
            if item.is_dir():
                _add_local(item, source, group)

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
        """Гарантирует junction на мод в <root>/KR_Debug/MODS/@Имя.

        Все моды (и Steam, и локальные) подключаются через эту папку,
        чтобы не захламлять корень игры/сервера. Возвращает (ok, сообщение).
        """
        from .layout import mods_link_dir
        link_dir = mods_link_dir(root)
        try:
            link_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return False, str(e)
        link = link_dir / mod.folder_name
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
