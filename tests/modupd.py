"""Проверка актуальности модов перед запуском: python tests/modupd.py

Steam здесь не нужен: состояние подменяется, а всё остальное — чистая логика.
Проверяем ровно то, из-за чего сервер поднимался бы со старым модом.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import modupdate, steam_state
from core.mods import ModInfo, SOURCE_LOCAL, SOURCE_STEAM

_fails: list[str] = []


def check(cond: bool, what: str) -> None:
    if not cond:
        _fails.append(what)


class FakeSettings:
    def __init__(self, **kw):
        self.mod_update_before_launch = True
        self.mod_update_method = modupdate.WAIT
        self.mod_update_timeout_min = 1
        self.steamcmd_exe = ""
        self.steam_login = ""
        self.__dict__.update(kw)


def mods():
    return [
        ModInfo(name="CF", path="x", source=SOURCE_STEAM, workshop_id="111"),
        ModInfo(name="VPP", path="y", source=SOURCE_STEAM, workshop_id="222"),
        ModInfo(name="KR_Core", path="z", source=SOURCE_LOCAL),
    ]


def fake_state(outdated=(), downloading=(), installed=()):
    """Подменяет ответ Steam на заданный."""
    ws = steam_state.WorkshopState()
    ws.outdated = set(outdated)
    ws.downloading = set(downloading)
    ws.installed = {i: 1 for i in installed}
    modupdate.steam_state.workshop_state = lambda _appid: ws


def test_which_mods() -> None:
    check([m.name for m in modupdate.steam_mods(mods())] == ["CF", "VPP"],
          "локальные моды не проверяются — у них нет версии в мастерской")


def test_stale() -> None:
    fake_state()
    check(modupdate.stale(mods()) == [], "всё свежее — никого не задерживаем")

    fake_state(outdated={"222"})
    left = modupdate.stale(mods())
    check([s.mod.name for s in left] == ["VPP"], "устаревший мод найден")
    check(left[0].reason == modupdate.OUTDATED, "причина названа")

    fake_state(downloading={"111"})
    left = modupdate.stale(mods())
    check(left[0].reason == modupdate.DOWNLOADING,
          "качающийся мод не годится для запуска")

    # Недокачанный важнее устаревшего: файлы прямо сейчас неполные.
    fake_state(outdated={"111"}, downloading={"111"})
    check(modupdate.stale(mods())[0].reason == modupdate.DOWNLOADING,
          "у мода в обоих списках причина — «качается»")


def test_wait() -> None:
    fake_state()
    ok, err = modupdate.wait_for_steam(mods(), timeout=1)
    check(ok and not err, "ждать нечего — проходим сразу")

    fake_state(outdated={"111"})
    said = []
    ok, err = modupdate.wait_for_steam(mods(), on_wait=said.append, timeout=0.2)
    check(not ok, "не дождались — запуск не разрешаем")
    check("CF" in err, "в отказе названо, чего именно ждали")
    check(len(said) == 1, "сказали один раз, а не на каждом опросе")

    fake_state(outdated={"111"})
    ok, err = modupdate.wait_for_steam(mods(), stop=lambda: True, timeout=30)
    check(not ok and "отмен" in err.lower(), "просьбу прервать слышим")


def test_command() -> None:
    got = modupdate.build_command(r"C:\s\steamcmd.exe", "kram", ["111", "222"])
    check(got[:3] == [r"C:\s\steamcmd.exe", "+login", "kram"], "вход первым")
    check(got.count("+workshop_download_item") == 2, "оба мода одной командой")
    check(got[-1] == "+quit", "выход последним")
    check(modupdate.build_command("x", "", ["1"])[2] == "anonymous",
          "без имени — анонимный вход")
    check(str(modupdate.content_dir(r"C:\s\steamcmd.exe")).endswith(
        r"steamapps\workshop\content\221100"), "качает рядом с собой")


def test_no_steamcmd() -> None:
    fake_state(outdated={"111"})
    ok, err = modupdate.download(r"C:\нет\steamcmd.exe", "", mods()[:1])
    check(not ok and "SteamCMD" in err, "нет SteamCMD — честный отказ, а не тишина")


def test_replace() -> None:
    root = Path(tempfile.mkdtemp())
    src, dst = root / "src", root / "dst"
    (src / "addons").mkdir(parents=True)
    (src / "addons" / "new.pbo").write_text("новое", encoding="utf-8")
    (dst / "addons").mkdir(parents=True)
    (dst / "addons" / "old.pbo").write_text("старое", encoding="utf-8")
    (dst / "meta.cpp").write_text("старое", encoding="utf-8")

    ok, err = modupdate.replace_contents(src, dst)
    check(ok, f"перенос не удался: {err}")
    check((dst / "addons" / "new.pbo").is_file(), "новые файлы на месте")
    check(not (dst / "addons" / "old.pbo").exists(), "старые файлы убраны")
    check(not (dst / "meta.cpp").exists(), "старый мусор в корне мода убран")
    check(dst.is_dir(), "саму папку не сносим — на неё может стоять ссылка")


def test_gate() -> None:
    """Общий вход: пока моды не в порядке, запуск не разрешается."""
    fake_state()
    ok, err = modupdate.bring_up_to_date(mods(), FakeSettings())
    check(ok and not err, "всё свежее — запуск разрешён без ожидания")

    fake_state(outdated={"111"})
    ok, err = modupdate.bring_up_to_date(
        mods(), FakeSettings(mod_update_method=modupdate.STEAMCMD,
                             steamcmd_exe=r"C:\нет\steamcmd.exe"))
    check(not ok, "устаревший мод без SteamCMD — запуск не разрешён")


def main() -> int:
    keep = steam_state.workshop_state
    try:
        for fn in (test_which_mods, test_stale, test_wait, test_command,
                   test_no_steamcmd, test_replace, test_gate):
            fn()
    finally:
        modupdate.steam_state.workshop_state = keep
    if _fails:
        print(f"НЕ ПРОШЛО ({len(_fails)}):")
        for f in _fails:
            print("  -", f)
        return 1
    print("обновление модов: всё сошлось")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
