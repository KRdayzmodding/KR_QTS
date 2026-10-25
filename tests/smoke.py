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
PAGES = {"страница настроек"}
# Карточки внутри страниц: с них спрашивается минимальная ширина — влезть в
# узкое окно, а не желаемая, которую им всё равно задаёт страница.
CARDS = {"редактор конфига"}

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
    s.save = lambda *a, **k: None       # п.67: прогон в настройки не пишет
    preset = ServerPreset(name="smoke_test", mission="smoke.chernarusplus")

    from ui.custom_map_dialog import CustomMapDialog
    from ui.mission_picker import MapPicker
    from ui.packlog_window import PackLogWindow
    from ui.pboproject_dialog import PboProjectDialog
    from ui.signkey_dialog import SignKeyDialog
    from ui.preflight_dialog import PreflightDialog
    from ui.settings_page import SettingsPage
    from ui.steamid_list import SteamIdList
    from ui.times_list import TimesList
    from ui.log_window import LogWindow
    from ui.update_gate import UpdateGate
    from ui.preset_editor import AdvancedPresetDialog, LazyPresetWizard
    from core.preflight import Problem

    cases = {
        "страница настроек": lambda: SettingsPage(s),
        # Со строками: карточка строит их при первом показе, а мерить надо
        # именно её настоящий размер, а не пустую заготовку.
        "редактор конфига": _cfg_card_built,
        "выбор карты": MapPicker,
        "своя карта": lambda: CustomMapDialog(None),
        "настройки pboProject": lambda: PboProjectDialog(s.pack_flags, s.clean_meta),
        "создание ключа подписи": lambda: SignKeyDialog(s),
        "предстартовая проверка": lambda: PreflightDialog(
            [Problem("x", "критично", True), Problem("y", "предупреждение", False)]),
        "список времён": TimesList,
        "список SteamID": lambda: SteamIdList([]),
        "окно логов": lambda: LogWindow("Логи сервера"),
        "проверка обновлений": UpdateGate,
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
        elif name in CARDS:
            mw = w.minimumSizeHint().width()
            check(f"{lang}/{name}: минимум {mw} px не больше {PAGE_MAX_W}",
                  mw <= PAGE_MAX_W, "" if mw <= PAGE_MAX_W else f"требует {mw} px")
        elif name in PAGES:
            # Печатаем и уложившиеся: иначе «ничего не сказано» неотличимо от
            # «проверка не запускалась», а список известных превышений должен
            # на глазах пустеть, а не молча.
            note = " (известно, ждёт переделки)" if name in KNOWN_WIDE else ""
            check(f"{lang}/{name}: ширина {wd} px не больше {PAGE_MAX_W}",
                  wd <= PAGE_MAX_W or name in KNOWN_WIDE,
                  "" if wd <= PAGE_MAX_W else f"требует {wd} px{note}")


def flashes() -> None:
    """Виджет без родителя, которому сказали показаться, — окно верхнего уровня.

    На экране оно мигает и пропадает, когда виджет кладут в раскладку. Одна
    строка настроек — одна вспышка; при сборке главного окна их набралось 113,
    и выглядело это как рябь из окон при каждом запуске программы. Глазами
    такое не ловится: живут вспышки доли секунды. Поэтому считаем их сами.
    """
    print("Мигающие окна:")
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication([])

    class Catcher(QObject):
        def __init__(self):
            super().__init__()
            self.seen = []

        def eventFilter(self, obj, event):      # имя метода задаёт Qt
            if (event.type() == QEvent.Type.Show and isinstance(obj, QWidget)
                    and obj.isWindow()):
                self.seen.append(type(obj).__name__)
            return False

    catcher = Catcher()
    app.installEventFilter(catcher)
    from core.settings import Settings
    from ui.main_window import MainWindow
    live = Settings.load()
    live.save = lambda *a, **k: None    # п.67: окно запоминает выбор и размер
    win = MainWindow(live)
    for _ in range(20):
        app.processEvents()
    main_seen = list(catcher.seen)
    win.deleteLater()
    # Само главное окно показаться не успевает (show ему не говорили), так что
    # честный ответ — ноль. Считаем всё, что всплыло сверх него.
    # Отдельно — страница настроек с пустыми путями: кнопки «получить
    # недостающее» видны только в этом случае, и мигали именно они. На
    # заполненных настройках разработчика проверка их не касалась.
    from core.settings import Settings as _S
    from ui.settings_page import SettingsPage
    blank = _S()
    blank.save = lambda *a, **k: None   # п.67: страница пишет на диск сама
    catcher.seen.clear()
    page = SettingsPage(blank)
    for _ in range(5):
        app.processEvents()
    page.deleteLater()
    check(f"страница настроек с пустыми путями: всплыло окон {len(catcher.seen)}",
          not catcher.seen, ", ".join(sorted(set(catcher.seen))))

    extra = [n for n in main_seen if n != "MainWindow"]
    check(f"при сборке главного окна всплыло окон: {len(extra)}", not extra,
          ", ".join(sorted(set(extra))))
    app.removeEventFilter(catcher)
    _poke(win, app)


def wheel_rules() -> None:
    """Правило колеса не должно спотыкаться о вложенные списки.

    Оно ходит по дереву виджетов вверх, разыскивая страницу. Список сам по
    себе тоже область прокрутки, и внутри его строк бывают свои виджеты —
    один такой случай уронил программу прямо под курсором: «страницей»
    оказалось само дерево модов.
    """
    print("Правила колеса:")
    from PySide6.QtWidgets import QApplication, QScrollArea, QTreeWidget, QWidget
    from ui import nowheel
    QApplication.instance() or QApplication([])

    page = QScrollArea()
    inner = QWidget()
    page.setWidget(inner)
    tree = QTreeWidget(inner)
    nested = QScrollArea(tree.viewport())       # список внутри строки списка

    found = nowheel._outer_area(nested)
    check("страницей считается страница, а не список",
          found is page, f"нашлось: {type(found).__name__ if found else 'ничего'}")
    try:
        nowheel._anchor_of(nested, page)
        ok, detail = True, ""
    except Exception as e:      # noqa: BLE001 — прогон должен дойти до конца
        ok, detail = False, f"{type(e).__name__}: {e}"
    check("поиск карточки-якоря не падает", ok, detail)
    page.deleteLater()


def server_flag() -> None:
    """Признак «серверный» переживает нажатие.

    Обработчик галки просил окно перечитать пресеты, а то пересобирало дерево
    прямо внутри сигнала строки — Qt после возврата обращался к освобождённой
    памяти, и программа падала насмерть, без записи в журнал. Падение такого
    рода видно только по тому, что прогон не дошёл до конца.
    """
    print("Признак «серверный»:")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    import core.mods as mods_mod
    import core.presets as presets_mod
    from core.mods import ModRegistry
    from core.presets import ServerPreset
    from core.settings import Settings as _S
    from ui.mods_panel import COL_SERVER, ModsPanel
    app = QApplication.instance() or QApplication([])

    save_flags, apply_flag = ModRegistry.save_flags, presets_mod.apply_server_flag
    mods_mod.ModRegistry.save_flags = lambda self: None      # на диск не пишем
    presets_mod.apply_server_flag = lambda name, flag: ["smoke"]
    try:
        st = _S.load()
        reg = ModRegistry(st)
        reg.scan()
        preset = ServerPreset(name="smoke_flag", mission="smoke.chernarusplus")
        preset.save = lambda: None
        panel = ModsPanel()
        panel.set_context(reg, st)
        panel.preset = preset
        item = next(iter(panel._iter_mod_items()), None)
        mod = panel._item_mod(item) if item is not None else None
        if mod is None:
            check("есть хоть один мод для проверки", False)
            return
        was = mod.is_server
        item.setCheckState(COL_SERVER, Qt.CheckState.Checked if not was
                           else Qt.CheckState.Unchecked)
        for _ in range(5):
            app.processEvents()
        check(f"галка «серверный» у «{mod.name}» переключилась", mod.is_server != was)
        panel.deleteLater()
    finally:
        mods_mod.ModRegistry.save_flags = save_flags
        presets_mod.apply_server_flag = apply_flag


def settings_sections() -> None:
    """Разделы настроек свёрнуты и открываются по одному.

    Семь разделов в одну ленту — это две с половиной тысячи пикселей, по
    которым нужную строку искали прокруткой. Свёрнутые они дают оглавление;
    проверяем, что оглавление и правда свёрнуто и что внутри ничего не
    потерялось.
    """
    print("Разделы настроек:")
    from PySide6.QtWidgets import QApplication
    from core.settings import Settings as _S
    from ui.settings_page import SettingsPage
    app = QApplication.instance() or QApplication([])

    import time

    st = _S()
    st.save = lambda *a, **k: None
    page = SettingsPage(st)
    page.resize(840, 700)

    def settled() -> int:
        """Высота страницы, когда разделы перестали двигаться.

        Сворачиваются они своим ходом, и померенная сразу высота — ещё
        развёрнутая. Ждём по факту: на занятой машине фиксированной паузы
        не хватает, и проверка мигала бы.
        """
        last, quiet, end = -1, time.perf_counter(), time.perf_counter() + 10
        while time.perf_counter() < end:
            app.processEvents()
            now = page.widget().sizeHint().height() if page.widget() else 0
            if now != last:
                last, quiet = now, time.perf_counter()
            elif time.perf_counter() - quiet > 0.4:
                break
        return last

    check("разделов семь", len(page.sections) == 7, str(len(page.sections)))
    check("все свёрнуты", all(not c.is_open() for c in page.sections))
    check("у каждого в шапке сказано, что внутри",
          all(c.summary.text().strip() for c in page.sections))
    closed = settled()
    check(f"свёрнутая страница умещается в экран: {closed} px", closed <= 700,
          f"{closed} px")
    page.sections[0].set_open(True)
    check("раскрытый раздел выше свёрнутого", settled() > closed)
    # поля внутри живы: страница по-прежнему отдаёт свои значения
    check("значения читаются и из свёрнутых разделов",
          page._form_values().get("language") == st.language)
    page.deleteLater()


def one_window() -> None:
    """Повторное нажатие поднимает открытое окно, а не делает второе.

    Немодальные окна — скачивание шаблона, копирование миссии, чужие
    настройки — открываются по кнопке, и нажать её дважды ничто не мешает.
    Второе окно делает ту же работу над теми же файлами.
    """
    print("Одно окно на одно дело:")
    from PySide6.QtWidgets import QApplication, QWidget
    from ui.onewindow import show_once
    app = QApplication.instance() or QApplication([])

    class Owner:
        pass

    made: list[QWidget] = []

    def make() -> QWidget:
        w = QWidget()
        made.append(w)
        return w

    owner = Owner()
    first = show_once(owner, "дело", make)
    again = show_once(owner, "дело", make)
    check("второе нажатие не делает второго окна",
          len(made) == 1 and first is again, f"окон {len(made)}")
    other = show_once(owner, "другое дело", make)
    check("разные дела — разные окна", len(made) == 2 and other is not first)
    first.close()
    first.deleteLater()
    for _ in range(5):
        app.processEvents()
    third = show_once(owner, "дело", make)
    check("после закрытия открывается заново",
          len(made) == 3 and third is not first, f"окон {len(made)}")
    for w in made:
        w.close()
        w.deleteLater()

    # Чужую программу повторно не запускаем: решение принимается по живому
    # процессу, а не по тому, нашлось ли его окно.
    from ui.settings_page import SettingsPage
    from core.settings import Settings as _S
    st = _S()
    st.save = lambda *a, **k: None
    page = SettingsPage(st)

    class Fake:
        pid = 0

        def poll(self):
            return None         # как будто программа работает

    page._krbuild_proc = Fake()
    page.p_krbuild.edit.setText("")
    before = page._krbuild_proc
    page._open_krbuild_settings()
    check("при живой чужой программе вторая не запускается",
          page._krbuild_proc is before)
    page.deleteLater()


def toolkit_offer() -> None:
    """Нет тулкита — есть кнопка, которая его поставит.

    Выбрать движок «Project Builder» можно и без установленного тулкита:
    собрать им тогда нельзя, и единственное, что видит человек, — «не
    установлен». Следующий шаг должен быть там же, где отказ.
    """
    print("Предложение поставить тулкит:")
    import tempfile
    from pathlib import Path as _P
    import os as _os
    from PySide6.QtWidgets import QApplication
    from core.settings import Settings as _S
    from core import settings as _cs
    from core import toolkit_setup
    from ui.settings_page import SettingsPage
    QApplication.instance() or QApplication([])

    saved = _os.environ.get("LOCALAPPDATA")
    saved_reg = _cs._installed_toolkit
    _cs._installed_toolkit = lambda: ""
    try:
        # 1. тулкита нет нигде
        _os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
        st = _S()
        st.save = lambda *a, **k: None
        page = SettingsPage(st)
        page._show_krbuild_found()
        check("без тулкита кнопка установки видна",
              page.b_toolkit_get.isVisibleTo(page.krbuild_box))
        page.deleteLater()

        # 2. тулкит на месте — предлагать нечего
        home = _P(tempfile.mkdtemp()) / "Programs" / "KR DevToolkit"
        home.mkdir(parents=True)
        for name in ("ProjectBuilder.exe", "ProjectBuilder_GUI.exe"):
            (home / name).write_bytes(b"MZ")
        _os.environ["LOCALAPPDATA"] = str(home.parent.parent)
        st2 = _S()
        st2.save = lambda *a, **k: None
        page2 = SettingsPage(st2)
        page2._show_krbuild_found()
        check("с установленным тулкитом кнопки нет",
              not page2.b_toolkit_get.isVisibleTo(page2.krbuild_box))
        page2.deleteLater()
    finally:
        _cs._installed_toolkit = saved_reg
        if saved is None:
            _os.environ.pop("LOCALAPPDATA", None)
        else:
            _os.environ["LOCALAPPDATA"] = saved

    # Скачанный установщик — это exe, который мы потом запустим. Принимать
    # его можно только после сверки: оборванная загрузка и подмена по пути
    # выглядят на диске одинаково.
    import hashlib
    with tempfile.TemporaryDirectory() as tmp:
        body = b"MZ" + b"x" * 100
        good = hashlib.sha256(body).hexdigest()
        saved_dir = toolkit_setup.SETUP_DIR
        toolkit_setup.SETUP_DIR = _P(tmp)
        try:
            path = toolkit_setup.local_setup()
            path.write_bytes(body)
            check("сошедшийся установщик берётся с диска",
                  toolkit_setup.ready(
                      toolkit_setup.Setup(size=len(body),
                                          digest="sha256:" + good)) == str(path))
            check("чужая сумма отвергается",
                  toolkit_setup.ready(
                      toolkit_setup.Setup(size=len(body),
                                          digest="sha256:" + "0" * 64)) == "")
            check("недокачанный по размеру отвергается",
                  toolkit_setup.ready(toolkit_setup.Setup(size=len(body) + 1)) == "")
            check("без суммы и размера файлу не верим",
                  toolkit_setup.ready(toolkit_setup.Setup()) == "")
        finally:
            toolkit_setup.SETUP_DIR = saved_dir

    # Отказ GitHub не должен отменять установку: без размера останемся без
    # полоски, но ссылка на файл постоянная и работает сама по себе.
    import urllib.error
    import urllib.request
    real = urllib.request.urlopen

    def deaf(*a, **k):
        raise urllib.error.URLError("нет сети")

    urllib.request.urlopen = deaf
    try:
        blind = toolkit_setup.fetch_setup(timeout=1)
    finally:
        urllib.request.urlopen = real
    check("без ответа GitHub остаётся прямая ссылка",
          blind.url == toolkit_setup.SETUP_URL and blind.size == 0
          and blind.expected == "", blind.url)


def pack_section() -> None:
    """В разделе запаковки видны настройки только выбранного движка.

    Чужие настройки, висящие там, где их движок не используется, человек
    читает как «надо заполнить» — и заполняет. Поэтому проверяем не наличие
    полей, а то, что лишние скрыты.
    """
    print("Раздел запаковки:")
    from PySide6.QtWidgets import QApplication
    from core.settings import Settings as _S
    from ui.settings_page import SettingsPage
    QApplication.instance() or QApplication([])

    # Поиск программ по одной общей папке: запаковщик и его окно настроек
    # лежат рядом в поставке, а имена у них менялись — помнить это должен
    # не человек.
    import tempfile
    from pathlib import Path as _P
    with tempfile.TemporaryDirectory() as tmp:
        root = _P(tmp)
        for rel in ("dist/KR DevToolkit/ProjectBuilder.exe",
                    "dist/KR DevToolkit/ProjectBuilder_GUI.exe",
                    "build/KR DevToolkit/ProjectBuilder.exe"):
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"MZ")
        from core.settings import (PACKER_CLI_NAMES, PACKER_GUI_NAMES,
                                   find_first_tool, toolkit_root)
        bundle = root / "dist" / "KR DevToolkit"
        check("запаковщик находится по общей папке",
              find_first_tool(str(root), PACKER_CLI_NAMES)
              == str(bundle / "ProjectBuilder.exe"),
              find_first_tool(str(root), PACKER_CLI_NAMES))
        check("его окно настроек — там же",
              find_first_tool(str(root), PACKER_GUI_NAMES)
              == str(bundle / "ProjectBuilder_GUI.exe"),
              find_first_tool(str(root), PACKER_GUI_NAMES))
        check("промежуточная сборка из build не выигрывает",
              "build" not in find_first_tool(str(root), PACKER_CLI_NAMES))
        check("по указанному exe находится его сосед",
              find_first_tool(str(bundle / "ProjectBuilder.exe"),
                              PACKER_GUI_NAMES)
              == str(bundle / "ProjectBuilder_GUI.exe"))
        check("в чужой папке честно ничего не находится",
              find_first_tool(tempfile.gettempdir() + "\\нет-такой-папки",
                              PACKER_CLI_NAMES) == "")

        # Прежние имена не ищем вовсе: те сборки сняты с поддержки, и найти
        # старую вместо новой — значит паковать неизвестно чем.
        old_root = _P(tempfile.mkdtemp())
        for old_rel in ("dist/krbuild-cli/krbuild-cli.exe",
                        "dist/KR DevToolkit/ProjectBuilderCli.exe"):
            old_exe = old_root / old_rel
            old_exe.parent.mkdir(parents=True, exist_ok=True)
            old_exe.write_bytes(b"MZ")
        check("старая сборка не выдаётся за новую",
              find_first_tool(str(old_root), PACKER_CLI_NAMES) == "",
              find_first_tool(str(old_root), PACKER_CLI_NAMES))

    # Установщик кладёт все exe плоско в %LOCALAPPDATA%\Programs\KR DevToolkit
    # и обновляет их сам. Пустое поле в настройках означает «бери оттуда»:
    # требовать ввести известный путь — значит просить человека сообщить нам
    # то, что мы и так знаем.
    import os as _os
    with tempfile.TemporaryDirectory() as tmp:
        home = _P(tmp) / "Programs" / "KR DevToolkit"
        home.mkdir(parents=True)
        for name in ("ProjectBuilder.exe", "ProjectBuilder_GUI.exe"):
            (home / name).write_bytes(b"MZ")
        saved = _os.environ.get("LOCALAPPDATA")
        _os.environ["LOCALAPPDATA"] = tmp
        # Реестр тоже подменяем: на этой машине тулкит стоит по-настоящему, и
        # без подмены проверка смотрела бы на живую установку вместо своей.
        from core import settings as _cs
        saved_reg = _cs._installed_toolkit
        _cs._installed_toolkit = lambda: ""
        try:
            from core.settings import toolkit_home, toolkit_root
            from core import krbuild as _kb0
            check("установленный тулкит находится без настройки",
                  toolkit_home() == str(home), toolkit_home())
            check("пустое поле означает установку",
                  toolkit_root("") == str(home), toolkit_root(""))
            check("указанная папка важнее установки",
                  toolkit_root(tmp) == tmp, toolkit_root(tmp))
            blank = _S()
            blank.save = lambda *a, **k: None
            check("запаковщик берётся из установки при пустом поле",
                  blank.krbuild_cli() == str(home / "ProjectBuilder.exe"),
                  blank.krbuild_cli())
            check("окно настроек — оттуда же",
                  _kb0.gui_exe(blank) == str(home / "ProjectBuilder_GUI.exe"),
                  _kb0.gui_exe(blank))
            check("движок при этом готов к работе",
                  _kb0.missing(blank) == "", _kb0.missing(blank))
            # Версия — из tools/<Тулза>/current: это их договор, тот же файл
            # читает их запускалка. Лежащий рядом state.json внутренний, и
            # перепутать их значит однажды показать пустоту вместо версии.
            tools = home / "tools" / "ProjectBuilder"
            tools.mkdir(parents=True)
            (tools / "current").write_text("0.2.1", encoding="ascii")
            (home / "state.json").write_text(
                '{"tools": {"ProjectBuilder": {"version": "9.9.9"}}}',
                encoding="utf-8")
            check("версия берётся из договорного файла",
                  _kb0.version_of(blank.krbuild_cli()) == "0.2.1",
                  _kb0.version_of(blank.krbuild_cli()))
            check("окно считается той же версией",
                  _kb0.version_of(_kb0.gui_exe(blank)) == "0.2.1",
                  _kb0.version_of(_kb0.gui_exe(blank)))
            # Папку установки человек может сменить в установщике — тогда
            # место по умолчанию пустое, и верен только реестр.
            moved = _P(tempfile.mkdtemp()) / "KR DevToolkit"
            moved.mkdir()
            (moved / "ProjectBuilder.exe").write_bytes(b"MZ")
            _cs._installed_toolkit = lambda: str(moved) + "\\"
            check("установка не на своём месте находится по реестру",
                  toolkit_home() == str(moved), toolkit_home())
            _cs._installed_toolkit = lambda: str(moved / "нет-такой")
            check("запись в реестре без запаковщика не в счёт",
                  toolkit_home() == str(home), toolkit_home())
        finally:
            _cs._installed_toolkit = saved_reg
            if saved is None:
                _os.environ.pop("LOCALAPPDATA", None)
            else:
                _os.environ["LOCALAPPDATA"] = saved

    # Кнопка и строка состояния должны отвечать на введённое сейчас, а не на
    # сохранённое: иначе сразу после ввода пути одна половина окна говорит
    # «нашлось», а вторая «не найдено».
    from dataclasses import replace as _replace
    from core import krbuild as _kb
    with tempfile.TemporaryDirectory() as tmp:
        root = _P(tmp)
        for rel in ("dist/KR DevToolkit/ProjectBuilder.exe",
                    "dist/KR DevToolkit/ProjectBuilder_GUI.exe"):
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"MZ")
        fresh = _S()                      # в настройках пусто
        fresh.save = lambda *a, **k: None
        page = SettingsPage(fresh)
        page.p_krbuild.edit.setText(str(root))
        page._show_krbuild_found()
        typed = _replace(page.settings, krbuild_exe=page.p_krbuild.text().strip())
        # Сверяем со словарём: к этому месту прогона загружен тот язык,
        # который оставил предыдущий тест, и искать русское слово нельзя.
        from core.i18n import tr as _tr
        head = _tr("settings.krbuild_found", "Нашлось: {p}", p="").strip()
        check("строка под полем видит введённое",
              page.krbuild_found.text().startswith(head.rstrip(":").split("{")[0]),
              page.krbuild_found.text())
        runtime = root / "dist" / "KR DevToolkit" / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "versions.json").write_text(
            '{"ProjectBuilder": {"version": "0.3.0"}}', encoding="utf-8")
        check("у распакованной раздачи версия из runtime",
              _kb.version_of(typed.krbuild_cli()) == "0.3.0",
              _kb.version_of(typed.krbuild_cli()))
        check("окно настроек ищется по введённому",
              _kb.gui_exe(typed)
              == str(root / "dist" / "KR DevToolkit" / "ProjectBuilder_GUI.exe"),
              _kb.gui_exe(typed))
        page.deleteLater()

    st = _S()
    st.save = lambda *a, **k: None
    page = SettingsPage(st)
    check("выбор движка — первое, что в разделе",
          page.pack_tool is not None and hasattr(page, "pbo_box"))
    for tool, pbo_seen, kb_seen in (("pboproject", True, False),
                                    ("krbuild", False, True)):
        page.pack_tool.setCurrentIndex(page.pack_tool.findData(tool))
        QApplication.processEvents()
        check(f"{tool}: видны настройки своего движка",
              page.pbo_box.isVisibleTo(page) is pbo_seen
              and page.krbuild_box.isVisibleTo(page) is kb_seen,
              f"pbo={page.pbo_box.isVisibleTo(page)}, "
              f"krbuild={page.krbuild_box.isVisibleTo(page)}")
        check(f"{tool}: выбор сохраняется",
              page._form_values()["pack_tool"] == tool)
    page.deleteLater()


def sign_key() -> None:
    """Ключ подписи: одна дверь, перенос старого значения, защита от ошибок.

    Ключ раньше жил внутри строки флагов pboProject, и дверей к нему было
    две — поле в окне флагов и сама строка. Теперь источник один, и проверка
    следит, чтобы строка флагов про подпись ничего не решала.
    """
    print("Ключ подписи:")
    import tempfile
    from pathlib import Path as _P
    from core import signkey
    from core.packer import _with_sign_key
    from core.settings import Settings as _S

    st = _S()
    st.sign_key = ""
    flags = _with_sign_key(["-P", "+K", "+K=C:/старый.biprivatekey", "+Z"], st)
    check("без ключа подпись выключена",
          "-K" in flags and not any("K=" in f for f in flags), str(flags))
    st.sign_key = r"D:\keys\KR.biprivatekey"
    flags = _with_sign_key(["-P", "-K", "+Z"], st)
    check("с ключом подпись включена",
          f"+K={st.sign_key}" in flags and "-K" not in flags, str(flags))

    # перенос из старых настроек
    old = _S()
    old.pack_flags = '-P +B +K=D:\\keys\\OLD.biprivatekey -X=*.h'
    moved = old.lift_sign_key()
    check("старый ключ переехал из флагов",
          moved and old.sign_key == "D:\\keys\\OLD.biprivatekey"
          and "K=" not in old.pack_flags, f"{old.sign_key} | {old.pack_flags}")
    check("повторный перенос ничего не делает", not old.lift_sign_key())

    # разбор строки флагов не должен есть обратные слэши: на этом ключ
    # приходил к pboProject как «D:keysKR.biprivatekey» и подпись не делалась
    from core.settings import split_flags
    got = split_flags(r'-P +K=D:\keys\KR.biprivatekey -X=*.h')
    check("путь в флагах переживает разбор",
          got == ["-P", r"+K=D:\keys\KR.biprivatekey", "-X=*.h"], str(got))
    got = split_flags(r'-P +K="D:\my keys\KR.biprivatekey" -Z')
    check("путь с пробелом остаётся одним аргументом",
          got == ["-P", r"+K=D:\my keys\KR.biprivatekey", "-Z"], str(got))

    # имя ключа: пробелы и кириллица ломают не нас, а сервер
    with tempfile.TemporaryDirectory() as tmp:
        ok, text = signkey.create(_S(), "КР тест", tmp)
        check("негодное имя ключа отклоняется", not ok and "латиница" in text, text)
        ok, text = signkey.create(_S(), "KR", "")
        check("без папки ключ не создаётся", not ok, text)
        # существующий файл не перезаписываем: им подписано всё, что роздано
        (_P(tmp) / ("KR" + signkey.PRIVATE_SUFFIX)).write_text("x", encoding="utf-8")
        ok, text = signkey.create(_S(), "KR", tmp)
        check("существующий ключ не затирается", not ok and "уже есть" in text, text)


def krbuild_events() -> None:
    """Разбор событий второго упаковщика: находки, итог, отказ.

    KR Build — чужая программа, мы зовём её exe и читаем строки JSON. Своего
    в этом коде только разбор, и ломается он молча: перестали распознаваться
    находки — сборка «успешна», а pbo с ошибками. Поэтому гоняем на заглушке,
    которая печатает ровно оговорённую схему.
    """
    print("События KR Build:")
    import sys as _sys
    import tempfile
    from pathlib import Path as _P
    from core import krbuild

    stub = _P(tempfile.mkdtemp()) / "stub.py"
    stub.write_text(
        "import json, sys\n"
        # Как настоящая программа: при перенаправлении вывод в UTF-8. Иначе
        # Python отдаёт кодировку консоли, и русский текст приезжает мусором —
        # на этом и попалась первая версия проверки.
        "sys.stdout.reconfigure(encoding='utf-8')\n"
        "def say(**e):\n"
        "    e.setdefault('v', 1)\n"
        "    print(json.dumps(e, ensure_ascii=False), flush=True)\n"
        "mode = sys.argv[1]\n"
        "if mode == 'refused':\n"
        "    say(event='refused', text='мод уже собирается')\n"
        "    say(event='done', ok=False)\n"
        "    sys.exit(1)\n"
        "say(event='start', source='s', target='t')\n"
        "say(event='stage', stage='build', done=1, total=2)\n"
        "print('посторонняя строка не из протокола', flush=True)\n"
        "say(event='невиданное', что='то')\n"
        "if mode == 'errors':\n"
        "    say(event='finding', level='error', file='config.cpp', line=2,\n"
        "        col=23, text='ожидалась «;»', code='cfg.syntax')\n"
        "    say(event='done', ok=False, errors=1, warnings=0, log='x.log')\n"
        "    sys.exit(1)\n"
        "say(event='done', ok=True, packed=True, pbo='p.pbo', log='x.log')\n",
        encoding="utf-8")

    def run(mode: str):
        seen = []
        ok, text = krbuild._run([_sys.executable, "-I", str(stub), mode],
                                on_event=seen.append)
        return ok, text, seen

    ok, text, seen = run("ok")
    check("удачная сборка понята как удачная", ok, text)
    check("посторонние строки не ломают разбор",
          [e.get("event") for e in seen].count("done") == 1, str(len(seen)))
    check("неизвестное событие пропускается молча",
          any(e.get("event") == "невиданное" for e in seen))

    ok, text, _ = run("errors")
    check("ошибки сборки видны", not ok and "cfg.syntax" in text, text)
    check("в тексте есть место ошибки", "строка 2" in text and "столбец 23" in text,
          text)

    ok, text, _ = run("refused")
    check("отказ до начала понятен", not ok and "собирается" in text, text)

    # заодно: развилка движков выбирает нужную реализацию
    from core.packer import pack_source_auto
    from core.mods import ModInfo
    from core.settings import Settings as _S
    st = _S()
    st.pack_tool = "krbuild"
    st.krbuild_exe = ""
    mod = ModInfo(name="smoke", path=tempfile.mkdtemp(), source="local")
    # Прячем установку: с пустым полем движок берёт её, и проверка «честно
    # отказывается» иначе запустила бы настоящую сборку настоящей чужой
    # программой — на пустых папках, зато с настоящим логом на диске.
    import os as _os
    from core import settings as _cs
    saved = _os.environ.get("LOCALAPPDATA")
    saved_reg = _cs._installed_toolkit
    _os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
    _cs._installed_toolkit = lambda: ""
    try:
        ok, text = pack_source_auto(st, mod, tempfile.mkdtemp())
    finally:
        _cs._installed_toolkit = saved_reg
        if saved is None:
            _os.environ.pop("LOCALAPPDATA", None)
        else:
            _os.environ["LOCALAPPDATA"] = saved
    check("без тулкита движок честно отказывается",
          not ok and "Dev Toolkit" in text, text)


def last_preset() -> None:
    """Пресет, с которым работали, открывается и в следующий раз.

    Раньше список всегда вставал на первый по алфавиту, и человек каждый
    запуск переключался обратно. Пресеты здесь свои: настоящие трогать
    нельзя, а проверять надо именно выбор между несколькими.
    """
    print("Последний пресет:")
    from PySide6.QtWidgets import QApplication
    from core.presets import ServerPreset
    from core.settings import Settings as _S
    import ui.main_window as mw
    app = QApplication.instance() or QApplication([])

    def three():
        out = []
        for name in ("alpha", "beta", "gamma"):
            p = ServerPreset(name=name, mission=f"{name}.chernarusplus")
            p.save = lambda *a, **k: None
            out.append(p)
        return out

    was = mw.ServerPreset.load_all
    mw.ServerPreset.load_all = staticmethod(three)
    store = {"last": ""}
    try:
        def start():
            st = _S.load()
            st.last_preset = store["last"]
            st.save = lambda *a, **k: store.update(last=st.last_preset)
            win = mw.MainWindow(st)
            for _ in range(10):
                app.processEvents()
            return win

        win = start()
        win.launch_page.preset_combo.setCurrentIndex(2)
        for _ in range(5):
            app.processEvents()
        check("выбор запоминается", store["last"] == "gamma_chernarusplus",
              store["last"])
        win.close()
        win = start()
        check("следующий запуск открывает его же",
              win.current is not None and win.current.name == "gamma",
              win.current.name if win.current else "нет")
        win.close()
        store["last"] = "такого_пресета_нет"
        win = start()
        check("исчезнувший пресет не ломает запуск",
              win.current is not None and win.current.name == "alpha",
              win.current.name if win.current else "нет")
        win.close()
    finally:
        mw.ServerPreset.load_all = was


def window_size() -> None:
    """Первый запуск — минимальный размер, дальше — как оставили.

    Правило из ui-rules (п.87). Окно, открывшееся больше нужного, человек
    ужимает сам; начинать с меньшего честнее. Мусор в настройках (размер
    меньше минимума) не должен применяться — иначе первый же показ выглядит
    как поломка.
    """
    print("Размер главного окна:")
    from PySide6.QtWidgets import QApplication
    from core.settings import Settings as _S
    from ui import tokens
    from ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    mw, mh = tokens.WIN_MAIN_MIN

    def opened(w: int, h: int):
        st = _S.load()
        st.save = lambda *a, **k: None      # п.67: настройки не трогаем
        st.window_w, st.window_h, st.window_max = w, h, False
        win = MainWindow(st)
        win.show()
        for _ in range(10):
            app.processEvents()
        size = (win.width(), win.height())
        win.close()
        for _ in range(5):
            app.processEvents()
        return win, size

    win, size = opened(0, 0)
    check("первый запуск — минимальный размер", size == (mw, mh), str(size))
    win.resize(mw + 320, mh + 240)
    for _ in range(5):
        app.processEvents()
    kept = {}
    win.settings.save = lambda *a, **k: kept.update(w=win.settings.window_w,
                                                    h=win.settings.window_h)
    win._remember_size()
    check("при закрытии запоминается то, что на экране",
          (kept.get("w"), kept.get("h")) == (mw + 320, mh + 240), str(kept))
    _w2, size = opened(kept.get("w", 0), kept.get("h", 0))
    check("следующий запуск открывает запомненный размер",
          size == (mw + 320, mh + 240), str(size))
    _w3, size = opened(320, 240)
    check("размер меньше минимума не применяется", size == (mw, mh), str(size))


def contrast() -> None:
    """Текстовые цвета держат 4.5:1 на всех поверхностях, в обеих темах.

    Правило 36 из ui-rules: контраст проверять измерением, а не на глаз. На
    глаз и не видно — роль «muted» прожила так полгода и всплыла только
    когда её померили со стороны: 3,16 на карточке в тёмной теме и 3,06 на
    консоли в светлой. Теперь это не вопрос внимательности.
    """
    print("Контраст:")
    from ui import tokens

    def luminance(value: str) -> float:
        v = value.lstrip("#")
        chan = []
        for i in (0, 2, 4):
            c = int(v[i:i + 2], 16) / 255
            chan.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
        return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2]

    def ratio(fg: str, bg: str) -> float:
        a, b = luminance(fg), luminance(bg)
        hi, lo = max(a, b), min(a, b)
        return (hi + 0.05) / (lo + 0.05)

    # Роль проверяется против тех поверхностей, на которых её правда рисуют.
    # «raised» здесь нет: на нём нет текста вовсе, им закрашены точки ручки
    # перетаскивания (ui/resizer.py). Цвета разбора строки лога живут только
    # на консоли. Начнёт роль появляться где-то ещё — допиши сюда пару.
    pages = ("card", "window", "console_bg")
    pairs = [(role, pages) for role in
             ("text", "text_dim", "success", "warning", "error", "info")]
    pairs += [(role, ("console_bg",)) for role in
              ("log_time", "log_tag", "log_string", "log_number")]
    for theme, table in (("светлая", tokens._LIGHT), ("тёмная", tokens._DARK)):
        worst = min(((ratio(table[r], table[s]), r, s)
                     for r, surfaces in pairs for s in surfaces),
                    key=lambda x: x[0])
        check(f"{theme}: текст не ниже 4.5:1", worst[0] >= 4.5,
              f"хуже всего «{worst[1]}» на «{worst[2]}»: {worst[0]:.2f}")
        # «muted» текстом не бывает: это заливка значка состояния и точка
        # индикатора, к рисунку норма 3:1. Обе живут на карточке и подложке.
        worst = min(((ratio(table["muted"], table[s]), s)
                     for s in ("card", "window")), key=lambda x: x[0])
        check(f"{theme}: нетекстовый «muted» не ниже 3:1", worst[0] >= 3.0,
              f"на «{worst[1]}»: {worst[0]:.2f}")


def card_motion() -> None:
    """Карточка раскрывается без скачков: ни в начале хода, ни в конце.

    Было два скачка, и оба заметны. Первый: setEndValue у остановленной
    анимации сразу писал конечную высоту в свойство, и карточка на кадр
    распахивалась целиком. Второй: целевую высоту брали у подсказки размера,
    а та врёт — у «Настроек сервера» обещала 1098 px против настоящих 4103,
    и после хода карточка допрыгивала на три тысячи пикселей.
    """
    print("Ход карточек:")
    import time
    from PySide6.QtWidgets import QApplication
    from core.settings import Settings as _S
    from ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])

    st = _S.load()
    st.save = lambda *a, **k: None
    win = MainWindow(st)
    win.resize(1100, 700)
    win.show()

    def settle(ms: int = 1400) -> None:
        end = time.perf_counter() + ms / 1000
        while time.perf_counter() < end:
            app.processEvents()

    from PySide6.QtCore import QAbstractAnimation

    def still(card, cap: float = 15.0) -> None:
        """Ждёт, пока карточка перестанет двигаться.

        По факту, а не по таймеру: к ходу добавляются сборка содержимого и
        догон высоты, и на занятой машине фиксированной паузы не хватало —
        проверка падала не на поломке, а на медленном прогоне.
        """
        end = time.perf_counter() + cap
        last, quiet = -1, time.perf_counter()
        while time.perf_counter() < end:
            app.processEvents()
            moving = card._ani.state() != QAbstractAnimation.State.Stopped
            if moving or card.height() != last:
                last, quiet = card.height(), time.perf_counter()
            elif time.perf_counter() - quiet > 0.4:
                return

    # Карточки сворачиваются при сборке страницы своим же ходом: пока он идёт,
    # высота у них промежуточная, и мерить от неё нечего.
    settle(1200)

    for name, card in (("моды", win.launch_page.mods_card),
                       ("настройки сервера", win.launch_page.setup_card)):
        # Приводим к известному состоянию сами: карточки сворачиваются при
        # сборке страницы своим ходом, и на занятой машине он мог ещё идти —
        # тогда «свёрнутая высота» измерялась на полпути, и проверка падала
        # не на поломке, а на медленном прогоне.
        card.set_open(False)
        still(card)
        shut = card.height()
        seen: list[int] = []
        card._ani.valueChanged.connect(lambda v: seen.append(int(v)))
        card.set_open(True)
        still(card)
        check(f"«{name}»: ход начинается со свёрнутой высоты",
              bool(seen) and seen[0] <= shut + 8, f"первое значение {seen[:1]}")
        check(f"«{name}»: после хода карточка не прыгает",
              abs(card.height() - max(seen or [0])) <= 32,
              f"высота {card.height()}, доехали до {max(seen or [0])}")
        seen.clear()
        card.set_open(False)
        still(card)
        check(f"«{name}»: свернулась до шапки",
              abs(card.height() - shut) <= 8, f"высота {card.height()} против {shut}")
    win.close()
    settle(100)


def icon_cache() -> None:
    """Кэш разбора svg не замораживает цвет иконки при смене темы.

    Главный риск подмены чужих функций: иконка нарисуется цветом прошлой
    темы, и это тот случай, который глазами не ловится — цвета близкие,
    а виден он только там, куда сейчас не смотришь.
    """
    print("Кэш иконок:")
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import (FluentIcon as FIF, Theme, isDarkTheme,
                               setTheme)
    from ui import fasticons
    QApplication.instance() or QApplication([])
    fasticons.install()

    def drawn(icon) -> set:
        img = QImage(32, 32, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        icon.render(p, img.rect())
        p.end()
        return {img.pixel(x, y) for x in range(32) for y in range(32)
                if img.pixelColor(x, y).alpha() > 128}

    was = Theme.DARK if isDarkTheme() else Theme.LIGHT
    try:
        setTheme(Theme.LIGHT)
        light = drawn(FIF.SETTING)
        setTheme(Theme.DARK)
        dark = drawn(FIF.SETTING)
        setTheme(Theme.LIGHT)
        again = drawn(FIF.SETTING)
        check("иконка перекрашивается под тему", bool(light) and light != dark)
        check("возврат темы возвращает цвет", light == again)
    finally:
        setTheme(was)


def log_speed() -> None:
    """Логи льются пачкой и не теряют строк, обход папки не повторяется зря.

    Два места, где программа тратила время впустую. Вставка строки в
    текстовую область стоит около 390 мкс независимо от длины, и построчный
    цикл на тысячах строк — это секунды стоящего окна. Обход папки логов
    стоит stat() на файл и звался дважды в секунду каждым хвостом, а файлы
    там копятся месяцами. Проверяем не скорость (она на разных машинах
    разная), а то, что оба обхода остались одноразовыми.
    """
    print("Скорость логов:")
    import tempfile
    from pathlib import Path as _P
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import PlainTextEdit
    from core import logsource
    from ui.logview import append_html
    QApplication.instance() or QApplication([])

    # строки не теряются, в том числе пустые: пустой <div> блока не создаёт
    view = PlainTextEdit()
    lines = ["<span>первая</span>", "", "<span>третья</span>", "   ",
             "<span>пятая</span>"]
    calls = []
    real = view.appendHtml
    view.appendHtml = lambda h: (calls.append(h), real(h))[1]
    append_html(view, lines)
    check("вставка одна на всю пачку", len(calls) == 1, f"вызовов {len(calls)}")
    check("строк столько же, сколько дали",
          view.document().blockCount() == len(lines),
          f"блоков {view.document().blockCount()} из {len(lines)}")
    view.deleteLater()

    # обход папки логов: второй подряд вызов не ходит в файловую систему
    with tempfile.TemporaryDirectory() as tmp:
        d = _P(tmp)
        (d / "DayZ_x64_2026-01-01_00-00-00.RPT").write_text("a\n", encoding="utf-8")
        scans = []
        real_glob = _P.glob
        _P.glob = lambda self, pat: (scans.append(pat), real_glob(self, pat))[1]
        try:
            logsource.log_files(d)
            first = len(scans)
            logsource.log_files(d)
            check("повторный обход папки не делается", len(scans) == first,
                  f"обходов {len(scans)} против {first}")
            (d / "DayZ_x64_2026-01-01_01-00-00.RPT").write_text("b\n", encoding="utf-8")
            # NTFS обновляет время папки лениво, и обычный обход новый файл
            # может не увидеть до конца срока памяти. Там, где именно ждут
            # его появления, мы спрашиваем заново — это и проверяем.
            check("новый файл виден при свежем обходе",
                  len(logsource.log_files(d, fresh=True)) == 2)
        finally:
            _P.glob = real_glob


def close_button() -> None:
    """Крестик слушается настройки: прячет в мини-окно или закрывает.

    Проверка за два конца: само поведение окна и то, что страница настроек
    это поле вообще сохраняет. Забыть привязать новый тумблер к сохранению
    легче всего, а выглядит это как «галка не работает».
    """
    print("Крестик главного окна:")
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from core.settings import Settings as _S
    from ui.main_window import MainWindow
    from ui.settings_page import SettingsPage
    app = QApplication.instance() or QApplication([])

    st = _S.load()
    st.save = lambda *a, **k: None          # п.67: настоящие настройки не трогаем
    from ui.mini_window import MiniWindow
    quit_, show_ = QApplication.quit, MiniWindow.show_at_saved_pos
    # Мини-окно в прогоне не показываем: всплывшее окно — это п.68, да и
    # проверяем мы решение, а не умение Qt показать виджет.
    QApplication.quit = staticmethod(lambda: calls.append("quit"))
    MiniWindow.show_at_saved_pos = lambda self: calls.append("mini")
    try:
        for flag, expect in ((False, "mini"), (True, "quit")):
            calls: list[str] = []
            st.close_quits = flag
            win = MainWindow(st)
            win.closeEvent(QEvent(QEvent.Type.Close))
            app.processEvents()
            what = ("прячется в мини-окно" if expect == "mini"
                    else "закрывает программу")
            check(f"close_quits={flag}: {what}", calls == [expect], str(calls))
            win.deleteLater()
    finally:
        QApplication.quit, MiniWindow.show_at_saved_pos = quit_, show_

    # Настройки страницы — свои и с заглушённым save(): страница пишет на
    # диск при каждом изменении поля, и настоящий конфиг она бы затёрла
    # значениями по умолчанию. Один раз так и вышло — см. п.67 в ui-rules.
    blank = _S()
    blank.save = lambda *a, **k: None
    page = SettingsPage(blank)
    page.close_quits.setChecked(True)
    check("страница настроек сохраняет поле",
          page._form_values().get("close_quits") is True
          and blank.close_quits is True)
    page.deleteLater()


def launch_paths() -> None:
    """В путях запуска нет прямых слэшей.

    Выделенный сервер на -config=KR_Debug/имя.cfg отвечает «Could not find
    server config» и выходит, хотя файл на месте. Проверено двумя прогонами
    DayZServer_x64.exe, отличавшимися одним символом. Правка, из-за которой
    это случилось, выглядела безобидно, а стоила полностью нерабочего запуска
    на чужой машине — поэтому разделитель проверяем, а не помним.
    """
    print("Пути в команде запуска:")
    from core.launcher import build_client_command, build_server_command
    from core.mods import ModRegistry
    from core.presets import MODE_DEDICATED, MODE_DIAG, ServerPreset
    from core.settings import STABLE
    from core.settings import Settings as _S

    st = _S.load()
    reg = ModRegistry(st)
    for mode in (MODE_DIAG, MODE_DEDICATED):
        preset = ServerPreset(name="smoke_paths", mode=mode,
                              mission="smoke.chernarusplus",
                              server_config="smoke.cfg", profiles="smoke")
        for who, build in (("сервер", build_server_command),
                           ("клиент", build_client_command)):
            _exe, args, _cwd = build(preset, st, STABLE, reg)
            bad = [a for a in args
                   if a.startswith(("-config=", "-mission=", "-profiles=", "-mod=",
                                    "-serverMod="))
                   and "/" in a]
            check(f"{who} ({mode}): разделители родные", not bad, "; ".join(bad))


def service_menu() -> None:
    """Меню «Обслуживание» собирается и знает про отсутствие пресета.

    Четыре действия переехали из редактора пресета, и проверять тут нечего,
    кроме одного: что они на месте и ведут куда надо. Кнопка без пресета
    должна быть неактивна — предлагать чистить профиль, которого нет, незачем.
    """
    print("Меню обслуживания пресета:")
    from PySide6.QtWidgets import QApplication, QPushButton
    from core.presets import ServerPreset
    from core.settings import Settings as _S
    from ui import preset_actions
    QApplication.instance() or QApplication([])

    st = _S.load()
    preset = ServerPreset(name="smoke_service", mission="smoke.chernarusplus")
    btn = QPushButton()
    menu = preset_actions.build_menu(btn, None, st, preset, "stable")
    texts = [a.text() for a in menu.actions() if a.text()]
    check("в меню четыре действия", len(texts) == 4, str(texts))
    # Сверяем со словарём, а не с русскими словами: к этому месту прогона
    # загружен тот язык, который оставил предыдущий тест.
    from core.i18n import tr as _tr
    check("очистки идут последними",
          texts[2:] == [_tr("preset.clear_db", "Очистить БД"),
                        _tr("preset.clear_prof", "Очистить профайл")], str(texts))
    path = preset_actions.profile_dir(st, preset, "stable")
    check("путь профиля считается без редактора", bool(path), path)
    btn.deleteLater()
    menu.deleteLater()


def pack_exclusions() -> None:
    """Следы обфускатора исключаются при любых настройках.

    .6w_pack лежит прямо в папке сорсов, рядом с config.cpp, и однажды уже
    уехал в боевой pbo. Полагаться на то, что нужная маска не выпадет из
    списка в настройках, тут нельзя: список правится руками.
    """
    print("Исключения при запаковке:")
    import tempfile
    from pathlib import Path as _P
    from core.packer import _MUST_EXCLUDE, _with_must_exclude, leaked_secrets
    from core.settings import Settings as _S

    # список из настроек: свои маски целы, обязательные дописаны, дублей нет
    out = _with_must_exclude(["-P", "-X=*.bak,.claude", "+Z"])
    x = next((f for f in out if f.upper().startswith(("-X=", "+X="))), "")
    masks = x.partition("=")[2].split(",")
    check("маски из настроек не потерялись", {"*.bak", ".claude"} <= set(masks))
    check("обязательные маски дописаны", set(_MUST_EXCLUDE) <= set(masks))
    check("дублей нет", len(masks) == len(set(masks)))
    check("остальные флаги на месте", out[0] == "-P" and "+Z" in out)

    # ключа -X в настройках нет вовсе — добавляем свой
    out = _with_must_exclude(["-P"])
    x = next((f for f in out if f.upper().startswith(("-X=", "+X="))), "")
    check("ключ -X добавляется, если его не было",
          set(_MUST_EXCLUDE) <= set(x.partition("=")[2].split(",")))

    # и то же самое через настройки по умолчанию: маски видны в диалоге
    out = _with_must_exclude(_S().pack_flags.split())
    x = next((f for f in out if f.upper().startswith(("-X=", "+X="))), "")
    check("в настройках по умолчанию маски уже есть",
          len(x.partition("=")[2].split(",")) == len(set(x.partition("=")[2].split(","))))

    # имя файла обфускатора в таблице pbo видно и при сжатом содержимом
    import struct

    from core.packer import forbidden_entries, pbo_entries

    def fake_pbo(path, names):
        head = b"\0" + struct.pack("<I", 0x56657273) + b"\0" * 16
        head += b"prefix\0smoke\0\0"             # свойства и их конец
        for n in names:
            head += n.encode() + b"\0" + b"\0" * 20
        head += b"\0" + b"\0" * 20               # конец таблицы файлов
        path.write_bytes(head + b"\x7f" * 128)   # «сжатое» содержимое
        return path

    with tempfile.TemporaryDirectory() as tmp:
        dirty = fake_pbo(_P(tmp) / "dirty.pbo",
                         ["config.bin", ".6w_pack", "scripts\\4_World\\a.c"])
        clean = fake_pbo(_P(tmp) / "ok.pbo", ["config.bin", "scripts\\4_World\\a.c"])
        check("таблица файлов pbo читается", pbo_entries(clean) ==
              ["config.bin", "scripts\\4_World\\a.c"],
              str(pbo_entries(clean)))
        check("файл обфускатора в pbo замечен",
              forbidden_entries(dirty) == [".6w_pack"], str(forbidden_entries(dirty)))
        check("чистая таблица файлов проходит", forbidden_entries(clean) == [])

    # карта переименований в готовом pbo — тоже утечка, и она заметна
    with tempfile.TemporaryDirectory() as tmp:
        pbo = _P(tmp) / "smoke.pbo"
        pbo.write_bytes(b"\x00" * 64 + b'{"obfuscated_definitions":{}}' + b"\x00" * 64)
        check("кэш переименований в pbo замечен",
              "obfuscated_definitions" in leaked_secrets(pbo))
        clean = _P(tmp) / "clean.pbo"
        clean.write_bytes(b"\x00" * 4096)
        check("чистый pbo проходит", leaked_secrets(clean) == [])


def cfg_autosave() -> None:
    """Снятая галка у ключа конфига доходит до файла.

    Кнопки «Сохранить» в карточке нет, запись идёт сама — и молча потерянная
    правка была бы заметна только тому, кто потом откроет файл.
    """
    print("Конфиг сервера:")
    import tempfile
    import time
    from pathlib import Path
    from PySide6.QtWidgets import QApplication
    import core.launcher as launcher
    from core.servercfg import ServerCfg
    from ui.cfg_editor import CfgCard
    QApplication.instance() or QApplication([])

    path = Path(tempfile.mkdtemp()) / "serverDZ.cfg"
    path.write_text('hostname = "smoke";' + chr(10) + "logMemory = 6;" + chr(10),
                    encoding="utf-8")
    was_running = launcher.dayz_running
    launcher.dayz_running = lambda: False       # в прогоне игра ни при чём
    try:
        card = CfgCard()
        card.set_path(path)
        # Строки собираются порциями, через цикл событий: ждём, как ждал бы
        # человек, открывший карточку. Без этого строк ещё нет.
        card.ensure_built()
        app = QApplication.instance()
        # Строки собираются порциями через цикл событий; под нагрузкой
        # прогона это дольше, чем на холостом ходу, поэтому ждём с запасом —
        # выходим сразу, как только собрались.
        deadline = time.perf_counter() + 20
        while not card.keys.is_built() and time.perf_counter() < deadline:
            app.processEvents()
        check("строки конфига собрались", card.keys.is_built())
        card.keys.rows["logMemory"].check.setChecked(False)
        card.save()                             # то же, что делает отсрочка
        left = ServerCfg(path).values()
        check("снятая галка убирает ключ из файла", "logMemory" not in left,
              f"осталось: {sorted(left)}")
        check("остальное не тронуто", left.get("hostname") == "smoke")
        card.deleteLater()
    finally:
        launcher.dayz_running = was_running


def mods_buttons() -> None:
    """«Включить все» и «Выключить все» правда меняют состав.

    Собранное окно ничего не доказывает: обработчик звал метод, которого в
    классе нет, и кнопка молча не делала ничего. Пресет здесь свой, на диск
    он не пишется.
    """
    print("Кнопки состава модов:")
    from PySide6.QtWidgets import QApplication
    from core.mods import ModRegistry
    from core.presets import ServerPreset
    from core.settings import Settings as _S
    from ui.mods_panel import ModsPanel
    QApplication.instance() or QApplication([])

    st = _S.load()
    reg = ModRegistry(st)
    reg.scan()
    preset = ServerPreset(name="smoke_all", mission="smoke.chernarusplus")
    preset.save = lambda: None      # на диск ничего не уходит
    panel = ModsPanel()
    panel.set_context(reg, st)
    panel.preset = preset
    total = len(reg.all())
    for flat in (False, True):
        panel._flat_view = flat
        panel._rebuild()
        preset.mods, preset.server_mods = [], []
        panel._set_all(True)
        got = len(preset.mods) + len(preset.server_mods)
        vid = "плоский список" if flat else "дерево"
        check(f"включить все ({vid}): подключено {got} из {total}", got == total)
        panel._set_all(False)
        check(f"выключить все ({vid})",
              not preset.mods and not preset.server_mods)
    panel.deleteLater()


def _cfg_card_built():
    """Карточка конфига со всеми ключами — как её видит человек."""
    from ui.cfg_editor import CfgCard
    card = CfgCard()
    card.keys.build()
    card.keys.load({})
    return card


def _poke(win, app) -> None:
    """Дёргает то, что человек трогает первым делом.

    Собранное окно ещё ничего не доказывает: обработчик может быть подключён с
    неверной подписью, и это выяснится на первом нажатии. Именно так и вышло с
    фильтром модов — падало на первом набранном символе.

    Ошибку в обработчике Qt вызывающему не отдаёт: сигнал пришёл из недр
    библиотеки, и исключение уходит в sys.excepthook, а setText возвращается
    как ни в чём не бывало. Поэтому try/except тут бесполезен — подменяем
    крючок и смотрим, не легло ли в него что-нибудь.
    """
    def run(title, action):
        errors = []
        hook = sys.excepthook
        sys.excepthook = lambda t, v, tb: errors.append(f"{t.__name__}: {v}")
        try:
            action()
            for _ in range(3):
                app.processEvents()
        except Exception as e:      # noqa: BLE001 — прогон должен дойти до конца
            errors.append(f"{type(e).__name__}: {e}")
        finally:
            sys.excepthook = hook
        check(title, not errors, "; ".join(errors))

    panel = getattr(win, "mods_panel", None)
    if panel is not None:
        def type_filter():
            panel.search.setText("kr")
            panel.search.setText("")
        run("фильтр модов принимает текст", type_filter)

    if panel is not None:
        def spin_wheel():
            """Колесо над списком модов — там живёт правило передачи хода.

            Оно лазает по дереву виджетов вверх и вниз, и одна неверная
            догадка о том, что считать страницей, роняла программу прямо под
            курсором.
            """
            from PySide6.QtCore import QPoint, QPointF, Qt
            from PySide6.QtGui import QWheelEvent
            view = panel.tree.viewport()
            centre = view.rect().center()
            for delta in (-120, 120):
                e = QWheelEvent(QPointF(centre), QPointF(view.mapToGlobal(centre)),
                                QPoint(0, 0), QPoint(0, delta),
                                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                Qt.ScrollPhase.NoScrollPhase, False)
                app.sendEvent(view, e)
        run("колесо над списком модов", spin_wheel)

    page = getattr(win, "launch_page", None)
    for name in ("setup_card", "mods_card", "pack_card"):
        card = getattr(page, name, None)
        if card is None:
            continue
        run(f"карточка «{name}» раскрывается и сворачивается",
            lambda c=card: (c.set_open(True), c.set_open(False)))


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
    wheel_rules()
    mods_buttons()
    settings_sections()
    one_window()
    pack_section()
    toolkit_offer()
    sign_key()
    krbuild_events()
    last_preset()
    window_size()
    contrast()
    card_motion()
    icon_cache()
    log_speed()
    close_button()
    launch_paths()
    service_menu()
    pack_exclusions()
    cfg_autosave()
    server_flag()
    flashes()
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
