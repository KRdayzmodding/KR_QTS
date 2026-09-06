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
KNOWN_WIDE = {"редактор конфига"}

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
        elif name in PAGES and wd > PAGE_MAX_W:
            note = " (известно, ждёт переделки)" if name in KNOWN_WIDE else ""
            check(f"{lang}/{name}: ширина {wd} px не больше {PAGE_MAX_W}",
                  name in KNOWN_WIDE, f"требует {wd} px{note}")


def main() -> int:
    dictionaries()
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
