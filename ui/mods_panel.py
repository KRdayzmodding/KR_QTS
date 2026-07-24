"""Вкладка модов: дерево по источникам (Steam / GitHub / локальные папки).

Колонки: Вкл (галка) | Название мода | @папка (серым) | Размер | PBO | Порядок |
Серверный | Сорсы. Порядок загрузки хранится в пресете; галка добавляет мод
в конец списка, стрелки двигают внутри списка.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidgetItem, QHeaderView, QMenu,
    QInputDialog, QDialog, QFileDialog, QListView, QTreeView, QAbstractItemView,
)
from qfluentwidgets import (
    PushButton, PrimaryPushButton, TransparentToolButton, TreeWidget, ListWidget,
    SearchLineEdit, BodyLabel, CaptionLabel, InfoBar, InfoBarPosition,
    FluentIcon as FIF,
)

from core.i18n import tr
from core.mods import (
    ModRegistry, ModInfo, SOURCE_STEAM, SOURCE_GITHUB, validate_mod_dir, format_size,
)
from core.presets import ServerPreset, ModPreset
from core.settings import Settings

(COL_NAME, COL_FOLDER, COL_SIZE, COL_PBO, COL_ORDER, COL_SERVER,
 COL_SOURCES) = range(7)
_GREY = QColor("#888888")


def pick_multiple_directories(parent, caption: str) -> list[str]:
    """Выбор нескольких папок разом — обычный QFileDialog умеет только одну.

    Стандартный трюк: недативный диалог + режим множественного выбора
    у внутренних view-виджетов.
    """
    dlg = QFileDialog(parent, caption)
    dlg.setFileMode(QFileDialog.FileMode.Directory)
    dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dlg.setOption(QFileDialog.Option.ShowDirsOnly, True)
    for view_type in (QListView, QTreeView):
        view = dlg.findChild(view_type)
        if view:
            view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    if dlg.exec():
        return dlg.selectedFiles()
    return []


class SourcesDialog(QDialog):
    """Папки сорсов локального мода (для запаковщика)."""

    def __init__(self, mod: ModInfo, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("mods.sources_title", "Сорсы мода {m}", m=mod.name))
        self.resize(560, 300)
        layout = QVBoxLayout(self)
        hint = BodyLabel(tr("mods.sources_hint",
                            "Одна папка сорсов = один PBO в addons. Запаковщик сравнивает даты файлов сорсов с датой PBO."))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.lst = ListWidget()
        self.lst.addItems(mod.sources)
        layout.addWidget(self.lst, 1)
        btns = QHBoxLayout()
        b_add = PushButton(FIF.ADD, tr("mods.sources_add", "Добавить папки…"))
        b_add.setToolTip(tr("mods.sources_add_tip",
                            "Можно выбрать сразу несколько папок (Ctrl/Shift+клик)."))
        b_del = PushButton(FIF.REMOVE, tr("mods.sources_del", "Убрать выбранную"))
        b_ok = PrimaryPushButton("OK")
        b_add.clicked.connect(self._add)
        b_del.clicked.connect(lambda: self.lst.takeItem(self.lst.currentRow()))
        b_ok.clicked.connect(self.accept)
        btns.addWidget(b_add)
        btns.addWidget(b_del)
        btns.addStretch(1)
        btns.addWidget(b_ok)
        layout.addLayout(btns)

    def _add(self) -> None:
        existing = {self.lst.item(i).text() for i in range(self.lst.count())}
        for p in pick_multiple_directories(self, tr("mods.sources_pick", "Папки сорсов")):
            if p not in existing:
                self.lst.addItem(p)
                existing.add(p)

    def sources(self) -> list[str]:
        return [self.lst.item(i).text() for i in range(self.lst.count())]


class ModsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.registry: ModRegistry | None = None
        self.preset: ServerPreset | None = None
        self.settings: Settings | None = None
        self._building = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        top = QHBoxLayout()
        b_refresh = PushButton(FIF.SYNC, tr("mods.refresh", "Обновить"))
        b_refresh.clicked.connect(self.refresh)
        b_add_dir = PushButton(FIF.FOLDER_ADD, tr("mods.add_local", "Добавить локальные моды"))
        b_add_dir.setToolTip(tr("mods.add_dir_tip",
                                "Папка с @модами или одиночная @папка мода."))
        b_add_dir.clicked.connect(self._add_folder)
        b_all = PushButton(tr("mods.enable_all", "Включить все"))
        b_all.clicked.connect(lambda: self._set_all(True))
        b_none = PushButton(tr("mods.disable_all", "Выключить все"))
        b_none.clicked.connect(lambda: self._set_all(False))
        b_up = TransparentToolButton(FIF.UP)
        b_up.setToolTip(tr("mods.up", "Выше в порядке загрузки"))
        b_up.clicked.connect(lambda: self._move(-1))
        b_down = TransparentToolButton(FIF.DOWN)
        b_down.setToolTip(tr("mods.down", "Ниже в порядке загрузки"))
        b_down.clicked.connect(lambda: self._move(1))
        b_save_set = PushButton(FIF.SAVE_AS, tr("mods.save_set", "Сохранить как набор…"))
        b_save_set.clicked.connect(self._save_set)
        self.b_apply_set = PushButton(FIF.CHECKBOX, tr("mods.apply_set", "Применить набор"))
        self.b_apply_set.clicked.connect(self._apply_set_menu)
        for b in (b_refresh, b_add_dir, b_all, b_none, b_up, b_down,
                  b_save_set, self.b_apply_set):
            top.addWidget(b)
        top.addStretch(1)
        layout.addLayout(top)

        self.search = SearchLineEdit()
        self.search.setPlaceholderText(tr("mods.search_ph", "Фильтр по названию…"))
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)

        self.tree = TreeWidget(self)
        self.tree.setColumnCount(7)
        self.tree.setHeaderLabels([
            tr("mods.col_name", "Мод"), tr("mods.col_folder", "Папка"),
            tr("mods.col_size", "Размер"), tr("mods.col_pbo", "PBO"),
            tr("mods.col_order", "Порядок"), tr("mods.col_server", "Серверный"),
            tr("mods.col_sources", "Сорсы"),
        ])
        hdr = self.tree.header()
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(COL_FOLDER, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(COL_SIZE, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(COL_PBO, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(COL_ORDER, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(COL_SERVER, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(COL_SOURCES, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemDoubleClicked.connect(self._item_dbl)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_context_menu)
        layout.addWidget(self.tree, 1)

        hint = CaptionLabel(tr("mods.hint",
                               "Галка подключает мод (в конец порядка загрузки). «Серверный» — мод идёт "
                               "в -serverMod. Стрелками ↑↓ меняется порядок. Двойной клик по «Сорсы» — "
                               "привязать сорсы локального мода для запаковки."))
        hint.setWordWrap(True)
        layout.addWidget(hint)

    # ---------------------------------------------------------------- контекст

    def set_context(self, registry: ModRegistry, preset: ServerPreset | None,
                    settings: Settings | None = None) -> None:
        self.registry = registry
        self.preset = preset
        if settings is not None:
            self.settings = settings
        self._rebuild()

    def refresh(self) -> None:
        if self.registry:
            self.registry.scan()
        self._rebuild()

    # ---------------------------------------------------------------- дерево

    def _expanded_groups(self) -> set[str]:
        out = set()
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            if g.isExpanded():
                out.add(g.text(COL_NAME).rsplit(" (", 1)[0])
        return out

    def _rebuild(self) -> None:
        expanded = self._expanded_groups() or None  # None = первый раз, раскрыть всё
        self._building = True
        self.tree.clear()
        if not self.registry:
            self._building = False
            return

        groups: dict[str, list[ModInfo]] = {}
        for mod in self.registry.all():
            groups.setdefault(mod.group or tr("mods.local", "Локальный"), []).append(mod)

        def group_rank(name: str):
            if name == "Steam":
                return (0, name)
            if name == "GitHub":
                return (1, name)
            return (2, name.lower())

        for gname in sorted(groups, key=group_rank):
            mods = groups[gname]
            gitem = QTreeWidgetItem([f"{gname} ({len(mods)})", "", "", "", "", "", ""])
            gitem.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = QFont()
            font.setBold(True)
            gitem.setFont(COL_NAME, font)
            self.tree.addTopLevelItem(gitem)
            for mod in mods:
                self._add_mod_item(gitem, mod)
            gitem.setExpanded(expanded is None or gname in expanded)
        self._building = False
        self._apply_filter(self.search.text())

    def _add_mod_item(self, parent: QTreeWidgetItem, mod: ModInfo) -> None:
        p = self.preset
        enabled = bool(p and (self._find(mod, p.mods) is not None
                              or self._find(mod, p.server_mods) is not None))
        is_server = bool(p and self._find(mod, p.server_mods) is not None)

        name = mod.name
        if mod.duplicate_of_steam:
            name += "  " + tr("mods.dup", "(есть дубль в Workshop)")
        if not mod.valid:
            name = "⚠ " + name
        item = QTreeWidgetItem([name, mod.folder_name, format_size(mod.size_bytes),
                                str(mod.pbo_count), self._order_text(mod), "",
                                self._sources_text(mod)])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                      | Qt.ItemFlag.ItemIsUserCheckable)
        # невалидный мод (нет addons/.pbo и т.п.) — подключить нельзя;
        # чекбокс остаётся видимым, но снятым, попытка включить откатывается
        # в _item_changed, а имя красным + иконка предупреждения
        item.setCheckState(COL_NAME, Qt.CheckState.Checked if (enabled and mod.valid)
                           else Qt.CheckState.Unchecked)
        item.setCheckState(COL_SERVER, Qt.CheckState.Checked if (is_server and mod.valid)
                           else Qt.CheckState.Unchecked)
        item.setForeground(COL_FOLDER, _GREY)
        item.setForeground(COL_SOURCES, _GREY)
        item.setForeground(COL_SIZE, _GREY)
        item.setForeground(COL_PBO, _GREY)
        if mod.pbo_names:
            item.setToolTip(COL_PBO, "\n".join(mod.pbo_names))
        if not mod.valid:
            item.setForeground(COL_NAME, QColor("#d32f2f"))
        item.setToolTip(COL_NAME, mod.problem or mod.path)
        item.setToolTip(COL_SERVER, tr("mods.server_tip",
                                       "Серверный мод: подключается только к серверу через -serverMod."))
        item.setData(COL_NAME, Qt.ItemDataRole.UserRole, mod.folder_name.lower())
        parent.addChild(item)

    def _sources_text(self, mod: ModInfo) -> str:
        if mod.source == SOURCE_STEAM:
            return "—"
        return "; ".join(mod.sources) if mod.sources else tr("mods.no_sources", "не заданы")

    def _order_text(self, mod: ModInfo) -> str:
        if not self.preset:
            return ""
        i = self._find(mod, self.preset.mods)
        if i is not None:
            return str(i + 1)
        i = self._find(mod, self.preset.server_mods)
        if i is not None:
            return f"S{i + 1}"
        return ""

    def _find(self, mod: ModInfo, names: list[str]) -> int | None:
        for i, n in enumerate(names):
            got = self.registry.get(n)
            if got and got.folder_name == mod.folder_name:
                return i
        return None

    def _iter_mod_items(self):
        for gi in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(gi)
            for ci in range(g.childCount()):
                yield g.child(ci)

    def _item_mod(self, item: QTreeWidgetItem) -> ModInfo | None:
        key = item.data(COL_NAME, Qt.ItemDataRole.UserRole)
        return self.registry.mods.get(key) if (key and self.registry) else None

    def _refresh_orders(self) -> None:
        self._building = True
        for item in self._iter_mod_items():
            mod = self._item_mod(item)
            if mod:
                item.setText(COL_ORDER, self._order_text(mod))
        self._building = False

    # ---------------------------------------------------------------- изменения

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._building or not self.preset or not self.registry:
            return
        mod = self._item_mod(item)
        if not mod:
            return
        if not mod.valid and (item.checkState(COL_NAME) == Qt.CheckState.Checked
                              or item.checkState(COL_SERVER) == Qt.CheckState.Checked):
            # невалидный мод нельзя подключить — откатываем попытку включить
            self._building = True
            item.setCheckState(COL_NAME, Qt.CheckState.Unchecked)
            item.setCheckState(COL_SERVER, Qt.CheckState.Unchecked)
            self._building = False
            InfoBar.warning(title=tr("mods.cant_enable",
                                     "Мод нельзя подключить: {p}", p=mod.problem),
                            content="", parent=self.window(), duration=4000,
                            position=InfoBarPosition.TOP_RIGHT)
            return
        p = self.preset
        enabled = item.checkState(COL_NAME) == Qt.CheckState.Checked
        server = item.checkState(COL_SERVER) == Qt.CheckState.Checked

        def drop(name_list):
            i = self._find(mod, name_list)
            if i is not None:
                name_list.pop(i)

        drop(p.mods)
        drop(p.server_mods)
        if enabled:
            (p.server_mods if server else p.mods).append(mod.name)
        elif column == COL_SERVER and server:
            # серверную галку поставили на выключенном моде — включаем сразу
            p.server_mods.append(mod.name)
            self._building = True
            item.setCheckState(COL_NAME, Qt.CheckState.Checked)
            self._building = False
        p.save()
        self._refresh_orders()

    def _set_all(self, state: bool) -> None:
        if not self.preset:
            return
        p = self.preset
        if not state:
            p.mods, p.server_mods = [], []
        else:
            for item in self._iter_mod_items():
                mod = self._item_mod(item)
                if mod and mod.valid and self._find(mod, p.mods) is None \
                        and self._find(mod, p.server_mods) is None:
                    p.mods.append(mod.name)
        p.save()
        self._rebuild()

    def _move(self, delta: int) -> None:
        item = self.tree.currentItem()
        mod = self._item_mod(item) if item else None
        if not mod or not self.preset:
            return
        for lst in (self.preset.mods, self.preset.server_mods):
            i = self._find(mod, lst)
            if i is not None:
                j = i + delta
                if 0 <= j < len(lst):
                    lst[i], lst[j] = lst[j], lst[i]
                    self.preset.save()
                    self._refresh_orders()
                return

    def _item_dbl(self, item: QTreeWidgetItem, column: int) -> None:
        if column != COL_SOURCES:
            return
        mod = self._item_mod(item)
        if not mod or mod.source == SOURCE_STEAM:
            return
        dlg = SourcesDialog(mod, self)
        if dlg.exec():
            mod.sources = dlg.sources()
            self.registry.save_sources()
            item.setText(COL_SOURCES, self._sources_text(mod))

    def _apply_filter(self, text: str) -> None:
        q = text.strip().lower()
        for gi in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(gi)
            visible_children = 0
            for ci in range(g.childCount()):
                child = g.child(ci)
                match = (not q or q in child.text(COL_NAME).lower()
                         or q in child.text(COL_FOLDER).lower())
                child.setHidden(not match)
                visible_children += int(match)
            g.setHidden(visible_children == 0)
            if q and visible_children:
                g.setExpanded(True)

    # ---------------------------------------------------------------- папки модов

    def _group_source_dirs(self, gitem: QTreeWidgetItem) -> list[str]:
        """Записи settings.local_mods_dirs, которым соответствует эта группа дерева."""
        if not self.settings:
            return []
        matches: set[str] = set()
        for ci in range(gitem.childCount()):
            mod = self._item_mod(gitem.child(ci))
            if not mod:
                continue
            mp = Path(mod.path)
            for d in self.settings.local_mods_dirs:
                dp = Path(d)
                if mp.parent == dp or mp == dp:
                    matches.add(d)
        return list(matches)

    def _tree_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if not item or item.parent() is not None or not self.settings:
            return  # меню только на группах верхнего уровня
        dirs = self._group_source_dirs(item)
        if not dirs:
            return  # группа не из настроенных папок (Steam/GitHub/легаси-корни)
        menu = QMenu(self)
        act = menu.addAction(tr("mods.remove_dir",
                                "Убрать эту папку из списка локальных модов"))
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen != act:
            return
        for d in dirs:
            if d in self.settings.local_mods_dirs:
                self.settings.local_mods_dirs.remove(d)
        self.settings.save()
        self.refresh()

    def _add_folder(self) -> None:
        if not self.settings:
            return
        picked = QFileDialog.getExistingDirectory(
            self, tr("mods.add_dir_pick", "Папка с модами или @папка мода"))
        if not picked:
            return
        p = Path(picked)
        candidates = [p] if p.name.startswith("@") else \
            [c for c in p.iterdir() if c.is_dir() and c.name.startswith("@")]
        if not candidates:
            InfoBar.warning(title=tr("mods.add_none",
                                     "В папке нет @модов — нечего добавлять."),
                            content="", parent=self, duration=4000,
                            position=InfoBarPosition.TOP_RIGHT)
            return
        # невалидные моды не блокируют добавление папки — показываем их
        # в дереве красным и с заблокированной галкой, а не прячем
        problems = [err for c in candidates if (err := validate_mod_dir(c))]
        valid = len(candidates) - len(problems)
        if str(p) not in self.settings.local_mods_dirs:
            self.settings.local_mods_dirs.append(str(p))
            self.settings.save()
        self.refresh()
        InfoBar.success(title=tr("mods.add_ok_dir", "Папка добавлена. Валидных модов: {v}, "
                                 "с проблемами: {p}", v=valid, p=len(problems)),
                        content="\n".join(problems[:6]), parent=self, duration=5000,
                        position=InfoBarPosition.TOP_RIGHT)

    # ---------------------------------------------------------------- наборы

    def _save_set(self) -> None:
        if not self.preset:
            return
        name, ok = QInputDialog.getText(self, tr("mods.set_title", "Набор модов"),
                                        tr("mods.set_name", "Название набора:"))
        if not ok or not name.strip():
            return
        ModPreset(name=name.strip(), mods=list(self.preset.mods),
                  server_mods=list(self.preset.server_mods)).save()
        InfoBar.success(title=tr("mods.set_saved", "Набор «{n}» сохранён.", n=name.strip()),
                        content="", parent=self, duration=3000,
                        position=InfoBarPosition.TOP_RIGHT)

    def _apply_set_menu(self) -> None:
        sets = ModPreset.load_all()
        if not sets:
            InfoBar.info(title=tr("mods.no_sets", "Сохранённых наборов пока нет."),
                         content="", parent=self, duration=3000,
                         position=InfoBarPosition.TOP_RIGHT)
            return
        menu = QMenu(self)
        for mp in sets:
            menu.addAction(mp.name, lambda m=mp: self._apply_set(m))
        menu.exec(self.b_apply_set.mapToGlobal(self.b_apply_set.rect().bottomLeft()))

    def _apply_set(self, mp: ModPreset) -> None:
        if not self.preset:
            return
        self.preset.mods = list(mp.mods)
        self.preset.server_mods = list(mp.server_mods)
        self.preset.save()
        self._rebuild()
