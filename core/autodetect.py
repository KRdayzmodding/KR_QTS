"""Автопоиск путей: Steam-библиотеки (реестр + libraryfolders.vdf), Mikero, DayZ Tools."""
from __future__ import annotations

import re
from pathlib import Path

# Имена папок установок в steamapps/common
CLIENT_STABLE_DIRS = ("DayZ",)
CLIENT_EXP_DIRS = ("DayZ Exp", "DayZ Experimental")
SERVER_STABLE_DIRS = ("DayZServer", "DayZ Server")
SERVER_EXP_DIRS = ("DayZ Server Exp", "DayZ Experimental Server")
DAYZ_TOOLS_DIRS = ("DayZ Tools",)

DAYZ_APPID = "221100"

MIKERO_CANDIDATES = (
    r"C:\Program Files (x86)\Mikero\DePboTools",
    r"C:\Program Files\Mikero\DePboTools",
)


def steam_root() -> Path | None:
    try:
        import winreg
        for hive, key in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        ):
            try:
                with winreg.OpenKey(hive, key) as k:
                    name = "SteamPath" if hive == winreg.HKEY_CURRENT_USER else "InstallPath"
                    val, _ = winreg.QueryValueEx(k, name)
                    p = Path(val)
                    if p.is_dir():
                        return p
            except OSError:
                continue
    except ImportError:
        pass
    return None


def steam_libraries() -> list[Path]:
    """Все Steam-библиотеки (папки, содержащие steamapps)."""
    root = steam_root()
    if not root:
        return []
    libs = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                p = Path(m.group(1).replace("\\\\", "\\"))
                if p.is_dir() and p not in libs:
                    libs.append(p)
        except OSError:
            pass
    return libs


def _find_install(names: tuple[str, ...], exe: str) -> str:
    for lib in steam_libraries():
        common = lib / "steamapps" / "common"
        for name in names:
            p = common / name
            if (p / exe).is_file():
                return str(p)
    return ""


def detect_all() -> dict:
    """Возвращает найденные пути; пустая строка/список — не найдено."""
    workshop = []
    for lib in steam_libraries():
        w = lib / "steamapps" / "workshop" / "content" / DAYZ_APPID
        if w.is_dir():
            workshop.append(str(w))

    mikero = ""
    for cand in MIKERO_CANDIDATES:
        if (Path(cand) / "bin" / "pboProject.exe").is_file():
            mikero = cand
            break

    return {
        "client_stable": _find_install(CLIENT_STABLE_DIRS, "DayZ_x64.exe"),
        "client_exp": _find_install(CLIENT_EXP_DIRS, "DayZ_x64.exe"),
        "server_stable": _find_install(SERVER_STABLE_DIRS, "DayZServer_x64.exe"),
        "server_exp": _find_install(SERVER_EXP_DIRS, "DayZServer_x64.exe"),
        "dayz_tools": _find_install(DAYZ_TOOLS_DIRS, "DayZTools.exe") or _find_install(DAYZ_TOOLS_DIRS, "Bin\\WorkbenchLauncher.exe") or _find_dir(DAYZ_TOOLS_DIRS),
        "mikero_tools": mikero,
        "workshop_dirs": workshop,
    }


def _find_dir(names: tuple[str, ...]) -> str:
    for lib in steam_libraries():
        common = lib / "steamapps" / "common"
        for name in names:
            if (common / name).is_dir():
                return str(common / name)
    return ""
