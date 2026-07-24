"""Каталог миссий (GitHub), установленные миссии в mpmissions, проверка версий."""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .presets import MODE_DIAG
from .settings import Settings, APP_DIR

CATALOG_FILE = APP_DIR / "data" / "missions_catalog.json"
META_NAME = ".krsm_mission.json"
_UA = {"User-Agent": "KR-ServerManager (github.com/KRdayzmodding/KR_ServerManager)"}


@dataclass
class CatalogEntry:
    id: str
    title: str
    world: str
    repo: str
    branch: str
    path: str


@dataclass
class InstalledMission:
    name: str          # имя папки, например myserver.chernarusplus
    world: str         # суффикс после последней точки
    path: str
    meta: dict = field(default_factory=dict)  # содержимое .krsm_mission.json, если есть

    @property
    def from_catalog(self) -> bool:
        return bool(self.meta.get("catalog_id"))


def load_catalog() -> list[CatalogEntry]:
    try:
        data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        return [CatalogEntry(**{k: m[k] for k in
                                ("id", "title", "world", "repo", "branch", "path")})
                for m in data.get("missions", [])]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return []


def mpmissions_dir(settings: Settings, branch: str, mode: str) -> Path:
    """Папка миссий: корень клиента для diag, корень сервера для dedicated."""
    root = settings.client_root(branch) if mode == MODE_DIAG else settings.server_root(branch)
    return Path(root) / "mpmissions" if root else Path("")


def resolve_mission(value: str, settings: Settings, branch: str, mode: str) -> str:
    """Значение миссии из пресета -> абсолютный путь.

    Голое имя папки -> <корень режима>/mpmissions/<имя>;
    относительный путь -> от корня клиента (совместимость со старыми пресетами).
    """
    if not value:
        return ""
    p = Path(value)
    if p.is_absolute():
        return str(p)
    if len(p.parts) == 1:
        base = mpmissions_dir(settings, branch, mode)
        return str(base / value) if str(base) else value
    return str(Path(settings.client_root(branch)) / p)


def installed_missions(directory: Path) -> list[InstalledMission]:
    out: list[InstalledMission] = []
    if not directory or not directory.is_dir():
        return out
    for item in sorted(directory.iterdir()):
        if not item.is_dir() or "." not in item.name:
            continue
        meta = {}
        mf = item / META_NAME
        if mf.is_file():
            try:
                meta = json.loads(mf.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        out.append(InstalledMission(
            name=item.name, world=item.name.rsplit(".", 1)[1],
            path=str(item), meta=meta,
        ))
    return out


def write_meta(mission_dir: Path, entry: CatalogEntry, sha: str | None,
               resolved_path: str) -> None:
    (mission_dir / META_NAME).write_text(json.dumps({
        "catalog_id": entry.id, "repo": entry.repo, "branch": entry.branch,
        "path": resolved_path, "sha": sha or "",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ GitHub API

def _api_json(url: str, timeout: int = 15):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def resolve_entry_path(entry: CatalogEntry) -> str:
    """Подставляет {latestV} — старшую папку вида V5.9 в корне репозитория."""
    if "{latestV}" not in entry.path:
        return entry.path
    items = _api_json(f"https://api.github.com/repos/{entry.repo}/contents/?ref={entry.branch}")
    best, best_key = None, ()
    for it in items:
        if it.get("type") != "dir":
            continue
        m = re.fullmatch(r"[Vv](\d+(?:\.\d+)*)", it.get("name", ""))
        if m:
            key = tuple(int(x) for x in m.group(1).split("."))
            if key > best_key:
                best, best_key = it["name"], key
    if not best:
        raise RuntimeError(f"В {entry.repo} не найдено папок версий V*")
    return entry.path.replace("{latestV}", best)


def latest_sha(entry: CatalogEntry, resolved_path: str) -> str | None:
    """SHA последнего коммита, затронувшего путь миссии (None при недоступности API)."""
    try:
        from urllib.parse import quote
        commits = _api_json(
            f"https://api.github.com/repos/{entry.repo}/commits"
            f"?sha={entry.branch}&path={quote(resolved_path)}&per_page=1")
        return commits[0]["sha"] if commits else None
    except Exception:  # noqa: BLE001 — лимит API/сеть не должны ломать загрузку
        return None


def zip_url(entry: CatalogEntry) -> str:
    return f"https://codeload.github.com/{entry.repo}/zip/refs/heads/{entry.branch}"
