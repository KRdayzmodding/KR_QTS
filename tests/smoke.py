"""Страховочный прогон перед переделкой интерфейса.

Не заменяет ручную проверку, а ловит то, что глазами не увидишь: разъехавшиеся
словари, потерянные подстановки, экран, который перестал собираться после
переименования поля, и окно, переросшее бюджет высоты.

Зависимостей не добавляет, окна на экране не показывает: работает через
offscreen-платформу Qt. Запуск:

    python tests/smoke.py

Возвращает 0, если всё сошлось, и 1 при первой же неудаче — чтобы прогон можно
было повесить на хук перед коммитом.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

LANGS = ("ru", "en", "de")
PLACEHOLDER = re.compile(r"{([a-zA-Z_][a-zA-Z0-9_]*)}")
DIALOG_MAX_H = 620      # бюджет из docs/UX.md, раздел 11
DIALOG_MAX_W = 900      # шире окно бесполезно: до краёв не дотянуться
PAGE_MAX_W = 840        # ширина содержимого при окне 1060 минус панель навигации

# Экраны, которые в бюджет пока не укладываются. Это не «сломалось», а «ещё не
# переделано»: список сокращается по мере работы и должен дойти до пустого.
# Пока запись здесь — прогон о ней сообщает, но не считает провалом.
KNOWN_WIDE: set[str] = set()

# Страницы живут внутри главного окна и делят ширину с панелью навигации.
# Отдельные окна (логи, запаковка) к этому бюджету отношения не имеют: их
# растягивают на пол-экрана, и это нормально.
PAGES = {"страница настроек", "редактор конфига"}

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(("  ok  " if ok else "  НЕТ ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        _failures.append(name)
    return ok


# ------------------------------------------------------------------ словари

def dictionaries() -> None:
    print("Словари:")
    data = {c: json.loads((ROOT / "lang" / f"{c}.json").read_text(encoding="utf-8"))
            for c in LANGS}
    base = set(data["ru"])
    for c in LANGS[1:]:
        missing = base - set(data[c])
        extra = set(data[c]) - base
        check(f"{c}: состав ключей совпадает с ru",
              not missing and not extra,
              f"нет {len(missing)}, лишних {len(extra)}" if (missing or extra) else "")

    bad = []
    for key, ru in data["ru"].items():
        if not isinstance(ru, str):
            continue
        want = set(PLACEHOLDER.findall(ru))
        for c in LANGS[1:]:
            other = data[c].get(key)
            if isinstance(other, str) and set(PLACEHOLDER.findall(other)) != want:
                bad.append(f"{key} ({c})")
    check("подстановки {..} совпадают во всех языках", not bad,
          ", ".join(bad[:5]) + (" и др." if len(bad) > 5 else ""))

    # ключ, которого нет в словаре, покажется английским текстом по умолчанию —
    # для русского интерфейса это ошибка, а не запасной вариант
    used = set()
    for f in list((ROOT / "ui").glob("*.py")) + list((ROOT / "core").glob("*.py")):
        used |= set(re.findall(r'tr\(\s*"([^"]+)"', f.read_text(encoding="utf-8")))
    lost = sorted(used - base)
    check("все ключи из кода есть в ru.json", not lost,
          ", ".join(lost[:5]) + (" и др." if len(lost) > 5 else ""))


# -------------------------------------------------------------------- экраны

def screens(lang: str = "ru") -> None:
    print(f"Экраны ({lang}):")
    from PySide6.QtWidgets import QApplication
    # приложение одно на весь прогон: второй QApplication Qt не допускает
    if QApplication.instance() is None:
        QApplication([])

    from core import i18n
    from core.presets import ServerPreset
    from core.settings import Settings
    i18n.load(lang)
    s = Settings.load()
    preset = ServerPreset(name="smoke_test", mission="smoke.chernarusplus")

    from ui.cfg_editor import CfgEditor
    from ui.custom_map_dialog import CustomMapDialog
    from ui.mission_picker import MapPicker
    from ui.packlog_window import PackLogWindow
    from ui.pboproject_dialog import PboProjectDialog
    from ui.preflight_dialog import PreflightDialog
    from ui.settings_page import SettingsPage
    from ui.steamid_list import SteamIdList
    from ui.times_list import TimesList
    from ui.log_window import LogWindow
    from ui.preset_editor import AdvancedPresetDialog, LazyPresetWizard
    from core.preflight import Problem

    cases = {
        "страница настроек": lambda: SettingsPage(s),
        "редактор конфига": CfgEditor,
        "выбор карты": MapPicker,
        "своя карта": lambda: CustomMapDialog(None),
        "настройки pboProject": lambda: PboProjectDialog(s.pack_flags, s.clean_meta),
        "предстартовая проверка": lambda: PreflightDialog(
            [Problem("x", "критично", True), Problem("y", "предупреждение", False)]),
        "список времён": TimesList,
        "список SteamID": lambda: SteamIdList([]),
        "окно логов": lambda: LogWindow("Логи сервера"),
        "логи запаковки": lambda: PackLogWindow("packing"),
        "редактор пресета": lambda: AdvancedPresetDialog(preset, s),
        "мастер пресета": lambda: LazyPresetWizard(s),
    }
    built = {}
    for name, factory in cases.items():
        try:
            w = factory()
            w.adjustSize()
            built[name] = w
            check(f"собирается: {name}", True)
        except Exception as e:      # noqa: BLE001 — прогон должен дойти до конца
            check(f"собирается: {name}", False, f"{type(e).__name__}: {e}")

    # Бюджет разный: диалог человек открывает поверх работы и закрывает, а
    # страница живёт внутри главного окна и делит его ширину с навигацией.
    # Немецкий длиннее русского примерно на десятую часть, и раскладка, которая
    # держится на фиксированной ширине, раздувается именно на нём — поэтому
    # каждый язык считается отдельно.
    from PySide6.QtWidgets import QDialog
    for name, w in built.items():
        if not w.isWindow():
            continue
        h, wd = w.sizeHint().height(), w.sizeHint().width()
        if isinstance(w, QDialog):
            check(f"{lang}/{name}: {wd}x{h} в бюджете {DIALOG_MAX_W}x{DIALOG_MAX_H}",
                  h <= DIALOG_MAX_H and wd <= DIALOG_MAX_W)
        elif name in PAGES:
            # Печатаем и уложившиеся: иначе «ничего не сказано» неотличимо от
            # «проверка не запускалась», а список известных превышений должен
            # на глазах пустеть, а не молча.
            note = " (известно, ждёт переделки)" if name in KNOWN_WIDE else ""
            check(f"{lang}/{name}: ширина {wd} px не больше {PAGE_MAX_W}",
                  wd <= PAGE_MAX_W or name in KNOWN_WIDE,
                  "" if wd <= PAGE_MAX_W else f"требует {wd} px{note}")


def external() -> None:
    """Внешнее управление: грамматика и справка.

    Здесь же, а не только отдельным запуском: справка строится из справочника
    параметров, и новый параметр без описания должен ломать общий прогон, а не
    обнаруживаться потом в консоли у человека.
    """
    print("Внешнее управление:")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import cli as cli_tests                       # tests/cli.py
    from core import cliargs, clihelp, i18n
    cli_tests._fails.clear()
    import modupd as upd_tests                    # tests/modupd.py
    upd_tests._fails.clear()
    for fn in (upd_tests.test_which_mods, upd_tests.test_stale, upd_tests.test_wait,
               upd_tests.test_command, upd_tests.test_no_steamcmd,
               upd_tests.test_replace, upd_tests.test_unverified,
               upd_tests.test_gate):
        fn()
    from core import steam_state as _st
    upd_tests.modupdate.steam_state.workshop_state = _st.workshop_state
    check("моды: проверка актуальности перед запуском",
          not upd_tests._fails, "; ".join(upd_tests._fails))

    import cfg as cfg_tests                       # tests/cfg.py
    cfg_tests._fails.clear()
    for fn in (cfg_tests.test_specs, cfg_tests.test_read, cfg_tests.test_change,
               cfg_tests.test_add, cfg_tests.test_remove, cfg_tests.test_apply):
        fn()
    from core import servercfg
    check(f"конфиг: {len(servercfg.SPECS)} известных ключей",
          not cfg_tests._fails, "; ".join(cfg_tests._fails))

    for fn in (cli_tests.test_basic, cli_tests.test_params, cli_tests.test_mods,
               cli_tests.test_pack_and_wait, cli_tests.test_help,
               cli_tests.test_specs, cli_tests.test_plan_three_cases,
               cli_tests.test_apply):
        fn()
    check(f"грамматика: {len(cliargs.all_specs())} аргументов",
          not cli_tests._fails, "; ".join(cli_tests._fails))

    for lang in LANGS:
        i18n.load(lang)
        pages = [clihelp.render(t) for t in ("",) + clihelp.TOPICS]
        check(f"{lang}/справка строится", all(len(p) > 40 for p in pages))
    caps = clihelp.capabilities()
    check("capabilities отдаёт все аргументы",
          len(caps["args"]) == len(cliargs.all_specs()))


def main() -> int:
    dictionaries()
    external()
    for lang in LANGS:
        screens(lang)
    print()
    if _failures:
        print(f"не сошлось: {len(_failures)}")
        for f in _failures:
            print("   ", f)
        return 1
    print("всё сошлось")
    return 0


if __name__ == "__main__":
    sys.exit(main())
