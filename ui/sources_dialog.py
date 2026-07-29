"""Моды с привязанными сорсами — и запуск их перепаковки.

Вкладка «Моды» показывает вообще всё, что нашлось, и пересобрать оттуда можно
только по одному моду. Во время работы над модом нужно другое: видеть свои
сборки, сразу понимать, какие из них устарели, и пересобрать нужные разом.
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QTreeWidgetItem, QHeaderView
from qfluentwidgets import (
    PushButton, PrimaryPushButton, TreeWidget, CheckBox, CaptionLabel,
    FluentIcon as FIF,
)

from core import packer, packlog
from core.i18n import tr
from core.mods import ModInfo, ModRegistry, SOURCE_LOCAL
from core.settings import Settings
from ui.theme import ThemedDialog

(COL_MOD, COL_SOURCES, COL_STATE) = range(3)
_ORANGE = QColor("#e08f00")
_GREEN = QColor("#2e7d32")


class PackWorker(QThread):
    """Перепаковка нескольких модов подряд.

    RebuildWorker с вкладки «Моды» умеет только один мод, а здесь выбирают
    сразу несколько — иначе пришлось бы городить очередь из воркеров.
    """
    source_start = Signal(str)              # имя pbo
    source_done = Signal(str, bool, int, int, int)  # pbo, успех, мс, warnings, errors
    finished_all = Signal(int, int)         # собрано, ошибок

    def __init__(self, settings: Settings, jobs: list[tuple[ModInfo, str]], parent=None):
        super().__init__(parent)
        self.settings = settings
        self.jobs = jobs

    def run(self) -> None:
        done = failed = 0
        for mod, src in self.jobs:
            name = packer.pbo_for_source(mod, src).name
            self.source_start.emit(name)
            t0 = time.monotonic()
            ok, _ = packer.pack_source_auto(self.settings, mod, src)
            w, e = packlog.counts(Path(src).name)
            self.source_done.emit(name, ok, int((time.monotonic() - t0) * 1000), w, e)
            if ok:
                done += 1
            else:
                failed += 1
        self.finished_all.emit(done, failed)


class SourcesDialog(ThemedDialog):
    """Список локальных модов с сорсами; выбранные можно перепаковать."""

    def __init__(self, registry: ModRegistry, settings: Settings, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.settings = settings
        self.selected_jobs: list[tuple[ModInfo, str]] = []

        self.setWindowTitle(tr("sources.title", "Моды с сорсами"))
        self.resize(620, 460)
        layout = QVBoxLayout(self)

        hint = CaptionLabel(tr("sources.hint",
                               "Отмечены моды, у которых сорсы новее собранных PBO. "
                               "Перепаковываются только отмеченные."))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.tree = TreeWidget(self)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([
            tr("mods.col_name", "Мод"),
            tr("sources.col_sources", "Сорсов"),
            tr("sources.col_state", "Состояние"),
        ])
        hdr = self.tree.header()
        hdr.setSectionResizeMode(COL_MOD, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(COL_SOURCES, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(COL_STATE, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tree, 1)

        self._fill()

        btns = QHBoxLayout()
        b_all = PushButton(tr("mods.enable_all", "Включить все"))
        b_all.clicked.connect(lambda: self._set_all(True))
        b_none = PushButton(tr("mods.disable_all", "Выключить все"))
        b_none.clicked.connect(lambda: self._set_all(False))
        btns.addWidget(b_all)
        btns.addWidget(b_none)
        btns.addStretch(1)
        b_cancel = PushButton(tr("common.close", "Закрыть"))
        b_cancel.clicked.connect(self.reject)
        self.b_pack = PrimaryPushButton(FIF.SYNC, tr("sources.repack", "Перепаковать"))
        self.b_pack.clicked.connect(self._accept_selection)
        btns.addWidget(b_cancel)
        btns.addWidget(self.b_pack)
        layout.addLayout(btns)

    # ------------------------------------------------------------------ данные

    def _fill(self) -> None:
        stale_by_mod = {id(m): set(s) for m, s in packer.stale_mods(
            [m for m in self.registry.all() if m.source == SOURCE_LOCAL])}
        any_rows = False
        for mod in self.registry.all():
            if mod.source != SOURCE_LOCAL or not mod.sources:
                continue
            any_rows = True
            stale = stale_by_mod.get(id(mod), set())
            item = QTreeWidgetItem([mod.name, str(len(mod.sources)), ""])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # по умолчанию отмечено то, что реально требует пересборки —
            # обычно именно это и нужно, а полный ребилд долгий
            item.setCheckState(COL_MOD, Qt.CheckState.Checked if stale
                               else Qt.CheckState.Unchecked)
            if stale:
                item.setText(COL_STATE, tr("sources.stale", "изменены: {n}", n=len(stale)))
                item.setForeground(COL_STATE, _ORANGE)
            else:
                item.setText(COL_STATE, tr("sources.fresh", "актуальны"))
                item.setForeground(COL_STATE, _GREEN)
            item.setData(COL_MOD, Qt.ItemDataRole.UserRole, mod)
            self.tree.addTopLevelItem(item)
        if not any_rows:
            self.tree.addTopLevelItem(QTreeWidgetItem(
                [tr("sources.none", "Локальных модов с сорсами нет"), "", ""]))

    def _items(self):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(COL_MOD, Qt.ItemDataRole.UserRole):
                yield item

    def _set_all(self, state: bool) -> None:
        s = Qt.CheckState.Checked if state else Qt.CheckState.Unchecked
        for item in self._items():
            item.setCheckState(COL_MOD, s)

    def _accept_selection(self) -> None:
        """Собирает задания: для отмеченных модов — все их папки сорсов.

        Именно все, а не только устаревшие: кнопка называется «Перепаковать»,
        и если мод отметили вручную, ожидается полная пересборка его pbo.
        """
        self.selected_jobs = [
            (item.data(COL_MOD, Qt.ItemDataRole.UserRole), src)
            for item in self._items()
            if item.checkState(COL_MOD) == Qt.CheckState.Checked
            for src in item.data(COL_MOD, Qt.ItemDataRole.UserRole).sources
        ]
        self.accept()
