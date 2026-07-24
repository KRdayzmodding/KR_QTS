"""Вкладка модов: подключение к пресету, порядок загрузки, наборы, сорсы."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidgetItem, QHeaderView, QMenu,
    QInputDialog, QDialog, QFileDialog, QTableWidget,
)
from qfluentwidgets import (
    PushButton, PrimaryPushButton, TransparentToolButton, TableWidget, ListWidget,
    SearchLineEdit, BodyLabel, CaptionLabel, InfoBar, InfoBarPosition,
    FluentIcon as FIF,
)

from core.i18n import tr
from core.mods import ModRegistry, ModInfo, SOURCE_STEAM
from core.presets import ServerPreset, ModPreset

COL_ON, COL_NAME, COL_SRC, COL_SERVER, COL_SOURCES = range(5)


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
        b_add = PushButton(FIF.ADD, tr("mods.sources_add", "Добавить папку…"))
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
        p = QFileDialog.getExistingDirectory(self, tr("mods.sources_pick", "Папка сорсов"))
        if p:
            self.lst.addItem(p)

    def sources(self) -> list[str]:
        return [self.lst.item(i).text() for i in range(self.lst.count())]


class ModsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.registry: ModRegistry | None = None
        self.preset: ServerPreset | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        top = QHBoxLayout()
        b_refresh = PushButton(FIF.SYNC, tr("mods.refresh", "Обновить"))
        b_refresh.clicked.connect(self.refresh)
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
        for b in (b_refresh, b_all, b_none, b_up, b_down, b_save_set, self.b_apply_set):
            top.addWidget(b)
        top.addStretch(1)
        layout.addLayout(top)

        self.search = SearchLineEdit()
        self.search.setPlaceholderText(tr("mods.search_ph", "Фильтр по названию…"))
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)

        self.table = TableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            tr("mods.col_on", "Вкл"), tr("mods.col_name", "Мод"),
            tr("mods.col_src", "Источник"), tr("mods.col_server", "Серверный"),
            tr("mods.col_sources", "Сорсы"),
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(COL_SOURCES, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.cellDoubleClicked.connect(self._cell_dbl)
        self.table.itemChanged.connect(lambda _i: self.apply_to_preset())
        layout.addWidget(self.table, 1)

        hint = CaptionLabel(tr("mods.hint",
                         "Галка «Вкл» подключает мод. «Серверный» — мод пойдёт в -serverMod (только сервер). "
                         "Порядок строк = порядок загрузки. Двойной клик по «Сорсы» — привязать сорсы локального мода."))
        hint.setWordWrap(True)
        layout.addWidget(hint)

    # ---------------------------------------------------------------- контекст

    def set_context(self, registry: ModRegistry, preset: ServerPreset | None) -> None:
        self.registry = registry
        self.preset = preset
        self._rebuild()

    def refresh(self) -> None:
        if self.registry:
            self.registry.scan()
        self._rebuild()

    def _rebuild(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        if not self.registry:
            self.table.blockSignals(False)
            return
        preset = self.preset
        enabled_order = (preset.mods + preset.server_mods) if preset else []

        def sort_key(m: ModInfo):
            key = m.folder_name
            for i, n in enumerate(enabled_order):
                got = self.registry.get(n)
                if got and got.folder_name == key:
                    return (0, i)
            return (1, m.name.lower())

        for mod in sorted(self.registry.all(), key=sort_key):
            self._add_row(mod)
        self.table.blockSignals(False)
        self._apply_filter(self.search.text())

    def _apply_filter(self, text: str) -> None:
        q = text.strip().lower()
        for row in range(self.table.rowCount()):
            name = self.table.item(row, COL_NAME).text().lower()
            self.table.setRowHidden(row, bool(q) and q not in name)

    def _add_row(self, mod: ModInfo) -> None:
        preset = self.preset
        row = self.table.rowCount()
        self.table.insertRow(row)

        on = QTableWidgetItem()
        on.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable)
        enabled = bool(preset and (self._in_list(mod, preset.mods)
                                   or self._in_list(mod, preset.server_mods)))
        on.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        self.table.setItem(row, COL_ON, on)

        name = QTableWidgetItem(mod.name)
        name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
        name.setData(Qt.ItemDataRole.UserRole, mod.folder_name)
        if mod.duplicate_of_steam:
            name.setText(mod.name + "  " + tr("mods.dup", "(есть дубль в Workshop)"))
        name.setToolTip(mod.path)
        self.table.setItem(row, COL_NAME, name)

        src = QTableWidgetItem("Steam" if mod.source == SOURCE_STEAM
                               else tr("mods.local", "Локальный"))
        src.setFlags(src.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, COL_SRC, src)

        srv = QTableWidgetItem()
        srv.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                     | Qt.ItemFlag.ItemIsSelectable)
        is_server = bool(preset and self._in_list(mod, preset.server_mods))
        srv.setCheckState(Qt.CheckState.Checked if is_server else Qt.CheckState.Unchecked)
        srv.setToolTip(tr("mods.server_tip",
                          "Серверный мод: подключается только к серверу через -serverMod."))
        self.table.setItem(row, COL_SERVER, srv)

        sources = QTableWidgetItem("; ".join(mod.sources) if mod.sources else
                                   ("—" if mod.source == SOURCE_STEAM else
                                    tr("mods.no_sources", "не заданы")))
        sources.setFlags(sources.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, COL_SOURCES, sources)

    def _in_list(self, mod: ModInfo, names: list[str]) -> bool:
        for n in names:
            got = self.registry.get(n)
            if got and got.folder_name == mod.folder_name:
                return True
        return False

    # ---------------------------------------------------------------- действия

    def _row_mod(self, row: int) -> ModInfo | None:
        item = self.table.item(row, COL_NAME)
        if not item:
            return None
        return self.registry.mods.get(item.data(Qt.ItemDataRole.UserRole).lower())

    def _cell_dbl(self, row: int, col: int) -> None:
        if col != COL_SOURCES:
            return
        mod = self._row_mod(row)
        if not mod or mod.source == SOURCE_STEAM:
            return
        dlg = SourcesDialog(mod, self)
        if dlg.exec():
            mod.sources = dlg.sources()
            self.registry.save_sources()
            self._rebuild()

    def _set_all(self, state: bool) -> None:
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            self.table.item(row, COL_ON).setCheckState(
                Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self.apply_to_preset()

    def _move(self, delta: int) -> None:
        row = self.table.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= self.table.rowCount():
            return
        self.table.blockSignals(True)
        for col in range(self.table.columnCount()):
            a = self.table.takeItem(row, col)
            b = self.table.takeItem(target, col)
            self.table.setItem(row, col, b)
            self.table.setItem(target, col, a)
        self.table.blockSignals(False)
        self.table.setCurrentCell(target, COL_NAME)
        self.apply_to_preset()

    def apply_to_preset(self) -> None:
        """Переносит состояние таблицы в пресет (порядок строк = порядок загрузки)."""
        if not self.preset or not self.registry:
            return
        mods, server_mods = [], []
        for row in range(self.table.rowCount()):
            if self.table.item(row, COL_ON).checkState() != Qt.CheckState.Checked:
                continue
            mod = self._row_mod(row)
            if not mod:
                continue
            if self.table.item(row, COL_SERVER).checkState() == Qt.CheckState.Checked:
                server_mods.append(mod.name)
            else:
                mods.append(mod.name)
        self.preset.mods = mods
        self.preset.server_mods = server_mods
        self.preset.save()

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
