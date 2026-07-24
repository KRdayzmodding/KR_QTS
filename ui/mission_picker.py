"""Выбор миссии: выпадающий список mpmissions + «+» (новая миссия из каталога) + обновление."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFormLayout, QDialog,
)
from qfluentwidgets import (
    EditableComboBox, ComboBox, LineEdit, ToolButton, PushButton,
    PrimaryPushButton, CheckBox, BodyLabel, CaptionLabel, MessageBox,
    FluentIcon as FIF, InfoBar, InfoBarPosition,
)

from core import missions
from core.i18n import tr
from core.missions import CatalogEntry, InstalledMission
from core.settings import Settings
from ui.download_window import DownloadWindow


class NewMissionDialog(QDialog):
    """Имя миссии слева, карта из каталога справа."""

    def __init__(self, catalog: list[CatalogEntry], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("mission.new_title", "Новая миссия"))
        self.resize(520, 200)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name = LineEdit()
        self.name.setPlaceholderText(tr("mission.name_ph", "например: myserver"))
        self.map_combo = ComboBox()
        for e in catalog:
            self.map_combo.addItem(f"{e.title}  (.{e.world})", userData=e)
        form.addRow(BodyLabel(tr("mission.name", "Название миссии")), self.name)
        form.addRow(BodyLabel(tr("mission.map", "Карта")), self.map_combo)
        layout.addLayout(form)

        self.hint = CaptionLabel(tr("mission.new_hint",
                                    "Папка миссии получит имя <название>.<карта>. "
                                    "Файлы будут скачаны с официального GitHub карты."))
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        btns = QHBoxLayout()
        btns.addStretch(1)
        b_cancel = PushButton(tr("preset.cancel", "Отмена"))
        b_cancel.clicked.connect(self.reject)
        b_ok = PrimaryPushButton(FIF.DOWNLOAD, tr("mission.download", "Скачать"))
        b_ok.clicked.connect(self._ok)
        btns.addWidget(b_cancel)
        btns.addWidget(b_ok)
        layout.addLayout(btns)

    def _ok(self) -> None:
        name = self.name.text().strip()
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", name or ""):
            self.hint.setText(tr("mission.bad_name",
                                 "Название: только латиница, цифры, - и _ (без точек)."))
            return
        self.accept()

    def result_name(self) -> str:
        entry: CatalogEntry = self.map_combo.currentData()
        return f"{self.name.text().strip()}.{entry.world}"

    def result_entry(self) -> CatalogEntry:
        return self.map_combo.currentData()


class UpdateMissionDialog(QDialog):
    """Подтверждение обновления с вопросом про storage."""

    def __init__(self, mission_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("mission.upd_title", "Обновление миссии"))
        self.resize(480, 170)
        layout = QVBoxLayout(self)
        warn = BodyLabel(tr("mission.upd_warn",
                            "«{n}» будет перезаписана свежей версией с GitHub.\n"
                            "Ваши правки файлов миссии будут потеряны.", n=mission_name))
        warn.setWordWrap(True)
        layout.addWidget(warn)
        self.keep_storage = CheckBox(tr("mission.keep_storage",
                                        "Сохранить storage_* (персистентность, персонажи)"))
        self.keep_storage.setChecked(False)
        layout.addWidget(self.keep_storage)
        layout.addStretch(1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        b_cancel = PushButton(tr("preset.cancel", "Отмена"))
        b_cancel.clicked.connect(self.reject)
        b_ok = PrimaryPushButton(FIF.SYNC, tr("mission.update", "Обновить"))
        b_ok.clicked.connect(self.accept)
        btns.addWidget(b_cancel)
        btns.addWidget(b_ok)
        layout.addLayout(btns)


class MissionPicker(QWidget):
    """Комбо с миссиями из mpmissions, «+» для новой, «обновить» для каталожных."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings: Settings | None = None
        self.branch = "stable"
        self.mode = "diag"
        self._windows: list[DownloadWindow] = []

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.combo = EditableComboBox()
        self.combo.setPlaceholderText(tr("mission.pick_ph", "Выберите или введите миссию…"))
        self.combo.currentIndexChanged.connect(lambda _i: self._update_buttons())
        self.b_add = ToolButton(FIF.ADD)
        self.b_add.setToolTip(tr("mission.add_tip", "Новая миссия из каталога карт"))
        self.b_add.clicked.connect(self._new_mission)
        self.b_upd = ToolButton(FIF.SYNC)
        self.b_upd.setToolTip(tr("mission.upd_tip",
                                 "Обновить миссию до последней версии с GitHub"))
        self.b_upd.clicked.connect(self._update_mission)
        row.addWidget(self.combo, 1)
        row.addWidget(self.b_add)
        row.addWidget(self.b_upd)

    # ------------------------------------------------------------------

    def set_context(self, settings: Settings, branch: str, mode: str,
                    current: str = "") -> None:
        self.settings = settings
        self.branch = branch
        self.mode = mode
        self.refresh(select=current)

    def refresh(self, select: str | None = None) -> None:
        if select is None:
            select = self.combo.currentText()
        self.combo.clear()
        self._installed: dict[str, InstalledMission] = {}
        if self.settings:
            directory = missions.mpmissions_dir(self.settings, self.branch, self.mode)
            for m in missions.installed_missions(directory):
                self._installed[m.name] = m
                self.combo.addItem(m.name)
        if select:
            idx = self.combo.findText(select)
            if idx >= 0:
                self.combo.setCurrentIndex(idx)
            else:
                self.combo.setCurrentText(select)
        self._update_buttons()

    def value(self) -> str:
        return self.combo.currentText().strip()

    def _current_installed(self) -> InstalledMission | None:
        return self._installed.get(self.value())

    def _update_buttons(self) -> None:
        m = self._current_installed()
        self.b_upd.setEnabled(bool(m and m.from_catalog))
        if m and m.from_catalog:
            self.b_upd.setToolTip(tr("mission.upd_tip_src",
                                     "Обновить с {repo}", repo=m.meta.get("repo", "")))

    # ------------------------------------------------------------------

    def _new_mission(self) -> None:
        if not self.settings:
            return
        catalog = missions.load_catalog()
        if not catalog:
            InfoBar.error(title=tr("mission.no_catalog", "Каталог миссий не найден."),
                          content="", parent=self.window(), duration=4000,
                          position=InfoBarPosition.TOP_RIGHT)
            return
        dlg = NewMissionDialog(catalog, self.window())
        if not dlg.exec():
            return
        name = dlg.result_name()
        entry = dlg.result_entry()
        directory = missions.mpmissions_dir(self.settings, self.branch, self.mode)
        if not str(directory):
            InfoBar.error(title=tr("mission.no_root",
                                   "Не задан корень игры/сервера в настройках."),
                          content="", parent=self.window(), duration=4000,
                          position=InfoBarPosition.TOP_RIGHT)
            return
        if (directory / name).exists():
            box = MessageBox(tr("mission.exists_title", "Миссия уже есть"),
                             tr("mission.exists", "Папка {n} уже существует. Перезаписать?",
                                n=name), self.window())
            if not box.exec():
                return
            self._start_download(entry, directory, name, replace=True, keep_storage=False)
            return
        self._start_download(entry, directory, name)

    def _update_mission(self) -> None:
        m = self._current_installed()
        if not m or not self.settings:
            return
        entry = None
        for e in missions.load_catalog():
            if e.id == m.meta.get("catalog_id"):
                entry = e
                break
        if entry is None:
            return
        dlg = UpdateMissionDialog(m.name, self.window())
        if not dlg.exec():
            return
        directory = missions.mpmissions_dir(self.settings, self.branch, self.mode)
        self._start_download(entry, directory, m.name, replace=True,
                             keep_storage=dlg.keep_storage.isChecked())

    def _start_download(self, entry: CatalogEntry, directory: Path, name: str,
                        replace: bool = False, keep_storage: bool = True) -> None:
        win = DownloadWindow(entry, directory, name, replace=replace,
                             keep_storage=keep_storage)
        win.finished_ok.connect(lambda _p, n=name: self.refresh(select=n))
        win.show()
        self._windows.append(win)  # держим ссылку, иначе окно соберёт GC
