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


def get_time_updated(workshop_id: str) -> int:
    """Unix-время последнего обновления воркшоп-айтема.

    ISteamRemoteStorage/GetPublishedFileDetails — публичный эндпоинт,
    ключ Steam Web API не нужен.
    """
    data = urllib.parse.urlencode({
        "itemcount": "1", "publishedfileids[0]": workshop_id,
    }).encode()
    req = urllib.request.Request(
        "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
        data=data, headers=_UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.loads(r.read().decode("utf-8", errors="replace"))
    details = body.get("response", {}).get("publishedfiledetails", [])
    if not details:
        return 0
    return int(details[0].get("time_updated", 0))


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


def parse_collection_id(text: str) -> str:
    """Извлекает id коллекции/мода из ссылки Steam Workshop или принимает голый id."""
    text = text.strip()
    if text.isdigit():
        return text
    m = re.search(r"[?&]id=(\d+)", text)
    return m.group(1) if m else ""


def get_collection_children(collection_id: str) -> list[str]:
    """ID модов, входящих в коллекцию Workshop (порядок — как в коллекции).

    ISteamRemoteStorage/GetCollectionDetails — публичный эндпоинт, ключ не нужен.
    """
    data = urllib.parse.urlencode({
        "collectioncount": "1", "publishedfileids[0]": collection_id,
    }).encode()
    req = urllib.request.Request(
        "https://api.steampowered.com/ISteamRemoteStorage/GetCollectionDetails/v1/",
        data=data, headers=_UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.loads(r.read().decode("utf-8", errors="replace"))
    details = body.get("response", {}).get("collectiondetails", [])
    if not details or details[0].get("result") != 1:
        return []
    return [str(c["publishedfileid"]) for c in details[0].get("children", [])]


def get_published_file_names(workshop_ids: list[str]) -> dict[str, str]:
    """Названия воркшоп-айтемов по списку id — для отображения недостающих
    модов коллекции (в реестре их нет, названия взять больше неоткуда)."""
    if not workshop_ids:
        return {}
    params = {"itemcount": str(len(workshop_ids))}
    for i, wid in enumerate(workshop_ids):
        params[f"publishedfileids[{i}]"] = wid
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
        data=data, headers=_UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.loads(r.read().decode("utf-8", errors="replace"))
    return {str(d.get("publishedfileid")): d.get("title", "")
           for d in body.get("response", {}).get("publishedfiledetails", [])}


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
