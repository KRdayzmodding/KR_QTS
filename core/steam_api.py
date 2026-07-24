"""Зависимости воркшоп-модов (Required Items).

С ключом Steam Web API — официальный IPublishedFileService/GetDetails
(includechildren); без ключа — разбор секции RequiredItems страницы воркшопа.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

_UA = {"User-Agent": "KR-ServerManager (github.com/KRdayzmodding/KR_ServerManager)"}


def _get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def deps_via_api(workshop_id: str, api_key: str) -> list[str]:
    """Зависимости через официальный API (children). Бросает исключение при сбое."""
    params = urllib.parse.urlencode({
        "key": api_key, "includechildren": "true", "publishedfileids[0]": workshop_id,
    })
    data = json.loads(_get(
        f"https://api.steampowered.com/IPublishedFileService/GetDetails/v1/?{params}"))
    details = data.get("response", {}).get("publishedfiledetails", [])
    if not details:
        return []
    return [str(c["publishedfileid"]) for c in details[0].get("children", [])]


def deps_via_page(workshop_id: str) -> list[str]:
    """Зависимости из секции Required Items страницы воркшопа (без ключа)."""
    html = _get(f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}")
    m = re.search(r'id="RequiredItems"(.*?)</div>\s*</div>', html, re.DOTALL)
    if not m:
        return []
    return list(dict.fromkeys(re.findall(r"filedetails/\?id=(\d+)", m.group(1))))


def get_dependencies(workshop_id: str, api_key: str = "") -> list[str]:
    """ID модов, от которых зависит workshop_id. Ключ есть — API, нет — страница."""
    if api_key:
        try:
            return deps_via_api(workshop_id, api_key)
        except Exception:  # noqa: BLE001 — неверный ключ/сеть: падаем на скрейп
            pass
    try:
        return deps_via_page(workshop_id)
    except Exception:  # noqa: BLE001 — сеть недоступна: считаем, что зависимостей нет
        return []


def resolve_dependencies_deep(workshop_id: str, api_key: str = "",
                              max_depth: int = 5) -> list[str]:
    """Рекурсивные зависимости (без дублей и циклов), в порядке обнаружения."""
    seen: dict[str, None] = {}
    frontier = [workshop_id]
    for _ in range(max_depth):
        nxt = []
        for wid in frontier:
            for dep in get_dependencies(wid, api_key):
                if dep not in seen and dep != workshop_id:
                    seen[dep] = None
                    nxt.append(dep)
        if not nxt:
            break
        frontier = nxt
    return list(seen)
