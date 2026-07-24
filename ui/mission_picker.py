"""Выбор карты для пресета.

Имя миссии не вводится: оно всегда <имя пресета>.<карта>. Пользователь
выбирает карту из каталога; если миссии ещё нет в KR_Debug/mpmissions —
она скачивается с официального GitHub карты.
"""
from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QDialog
from qfluentwidgets import (
    ComboBox, ToolButton, PushButton, PrimaryPushButton, CheckBox,
    BodyLabel, CaptionLabel, IndeterminateProgressBar, FluentIcon as FIF,
)

from core import missions
from core.downloader import MissionCopyWorker
from core.i18n import tr
from core.missions import CatalogEntry, template_name
from core.settings import Settings
from ui.download_window import DownloadWindow


class CopyDialog(QDialog):
    """Модальное окошко локального копирования шаблона в миссию пресета."""

    def __init__(self, src, dst, replace: bool = False, keep_storage: bool = True,
                 parent=None):
        super().__init__(parent, Qt.WindowType.Dialog
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowTitle(tr("mission.copy_title", "Создание миссии"))
        self.resize(440, 130)
        layout = QVBoxLayout(self)
        self.status = BodyLabel(tr("mission.copying", "Копирование {s} → {d}…",
                                   s=src.name, d=dst.name))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.bar = IndeterminateProgressBar()
        self.bar.start()
        layout.addWidget(self.bar)
        self.btn = PushButton(tr("dl.close", "Закрыть"))
        self.btn.setEnabled(False)
        self.btn.clicked.connect(self.close)
        layout.addWidget(self.btn)

        self.worker = MissionCopyWorker(src, dst, replace=replace,
                                        keep_storage=keep_storage)
        self.worker.done.connect(self._done)
        self.worker.start()

    def _done(self, ok: bool, result: str) -> None:
        self.bar.stop()
        if ok:
            self.status.setText(tr("mission.copied", "Готово: {p}", p=result))
        else:
            self.status.setText(result)
        self.btn.setEnabled(True)

_LEGACY = "legacy"
_CATALOG = "cat"


class UpdateMissionDialog(QDialog):
    """Подтверждение пересоздания миссии из шаблона + вопрос про storage."""

    def __init__(self, mission_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("mission.recreate_title", "Пересоздание миссии"))
        self.resize(480, 170)
        layout = QVBoxLayout(self)
        warn = BodyLabel(tr("mission.recreate_warn",
                            "«{n}» будет пересоздана из шаблона actual.<карта>.\n"
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
        b_cancel = PushButton(tr("common.cancel", "Отмена"))
        b_cancel.clicked.connect(self.reject)
        b_ok = PrimaryPushButton(FIF.COPY, tr("mission.recreate", "Пересоздать"))
        b_ok.clicked.connect(self.accept)
        btns.addWidget(b_cancel)
        btns.addWidget(b_ok)
        layout.addLayout(btns)


class MapPicker(QWidget):
    """Комбо карт из каталога + статус миссии + кнопка обновления."""

    changed = Signal()  # смена карты/имени — редакторы обновляют подсказки

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings: Settings | None = None
        self.branch = "stable"
        self.mode = "diag"
        self.preset_name = ""
        self._windows: list[DownloadWindow] = []

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        row = QHBoxLayout()
        self.combo = ComboBox()
        self.combo.currentIndexChanged.connect(lambda _i: self._update_status())
        self.b_upd = ToolButton(FIF.SYNC)
        self.b_upd.setToolTip(tr("mission.upd_tip",
                                 "Обновить шаблон actual.<карта> с GitHub"))
        self.b_upd.clicked.connect(self._update_template)
        self.b_recreate = ToolButton(FIF.COPY)
        self.b_recreate.setToolTip(tr("mission.recreate_tip",
                                      "Пересоздать миссию пресета из шаблона"))
        self.b_recreate.clicked.connect(self._recreate_mission)
        row.addWidget(self.combo, 1)
        row.addWidget(self.b_upd)
        row.addWidget(self.b_recreate)
        col.addLayout(row)
        self.status = CaptionLabel("")
        col.addWidget(self.status)

    # ------------------------------------------------------------------

    def set_context(self, settings: Settings, branch: str, mode: str,
                    preset_name: str, current_mission: str = "") -> None:
        self.settings = settings
        self.branch = branch
        self.mode = mode
        self.preset_name = preset_name
        current_world = current_mission.rsplit(".", 1)[1] if "." in current_mission else ""

        self.combo.blockSignals(True)
        self.combo.clear()
        select = 0
        # Старый пресет с миссией, не подчиняющейся правилу имён — не ломаем его
        derived_names = {f"{preset_name}.{e.world}" for e in missions.load_catalog()}
        if current_mission and current_mission not in derived_names:
            self.combo.addItem(tr("mission.keep_current", "Текущая миссия: {m}",
                                  m=current_mission),
                               userData=(_LEGACY, current_mission))
        for entry in missions.load_catalog():
            self.combo.addItem(f"{entry.title}  (.{entry.world})",
                               userData=(_CATALOG, entry))
            if current_mission in derived_names and entry.world == current_world \
                    and select == 0:
                select = self.combo.count() - 1
        self.combo.setCurrentIndex(select)
        self.combo.blockSignals(False)
        self._update_status()

    def set_preset_name(self, name: str) -> None:
        self.preset_name = name
        self._update_status()

    # ------------------------------------------------------------------

    def _data(self):
        return self.combo.currentData() or (None, None)

    def mission_name(self) -> str:
        kind, val = self._data()
        if kind == _LEGACY:
            return val
        if kind == _CATALOG and self.preset_name:
            return f"{self.preset_name}.{val.world}"
        return ""

    def world(self) -> str:
        """Имя мира выбранной карты (для схемы имён <пресет>_<карта>)."""
        kind, val = self._data()
        if kind == _CATALOG:
            return val.world
        if kind == _LEGACY and "." in val:
            return val.rsplit(".", 1)[1]
        return ""

    def catalog_entry(self) -> CatalogEntry | None:
        kind, val = self._data()
        return val if kind == _CATALOG else None

    def _missions_base(self):
        if not self.settings:
            return None
        base = missions.mpmissions_dir(self.settings, self.branch, self.mode)
        return base if str(base) else None

    def _mission_dir(self):
        base = self._missions_base()
        name = self.mission_name()
        return (base / name) if (base and name) else None

    def _template_dir(self):
        from core.layout import templates_dir
        world = self.world()
        if not self.settings or not world:
            return None
        return templates_dir(self.settings) / template_name(world)

    def _update_status(self) -> None:
        kind, _val = self._data()
        d = self._mission_dir()
        t = self._template_dir()
        installed = bool(d and d.is_dir())
        template_ok = bool(t and t.is_dir())
        if kind == _LEGACY:
            self.status.setText(tr("mission.st_legacy", "Используется как есть."))
            self.b_upd.setEnabled(False)
            self.b_recreate.setEnabled(False)
            self.changed.emit()
            return
        entry = self.catalog_entry()
        if not self.preset_name:
            self.status.setText("")
        elif installed:
            self.status.setText(tr("mission.st_ok", "✓ {n} — установлена", n=d.name))
        elif template_ok:
            self.status.setText(tr("mission.st_copy",
                                   "{n} — будет создана из шаблона {t} (без скачивания)",
                                   n=d.name if d else "?", t=t.name))
        else:
            self.status.setText(tr("mission.st_dl_tpl",
                                   "Шаблон {t} будет скачан с github.com/{repo}, "
                                   "миссия {n} — его локальная копия",
                                   t=t.name if t else "?", n=d.name if d else "?",
                                   repo=entry.repo if entry else "?"))
        self.b_upd.setEnabled(template_ok and bool(entry))
        self.b_recreate.setEnabled(installed and template_ok)
        self.changed.emit()

    # ------------------------------------------------------------------

    def _mods_dl_dir(self):
        from core.layout import mods_dl_dir
        return mods_dl_dir(self.settings) if self.settings else None

    def ensure_mission(self) -> None:
        """Миссии нет — создаёт её из шаблона; нет шаблона — сначала качает его."""
        entry = self.catalog_entry()
        d = self._mission_dir()
        t = self._template_dir()
        if not entry or not d or not t or d.is_dir():
            return
        if t.is_dir():
            self._start_copy(t, d)
            return
        win = DownloadWindow(entry, t.parent, t.name, mods_dir=self._mods_dl_dir())
        win.finished_ok.connect(lambda _p, s=t, dst=d: self._start_copy(s, dst))
        win.show()
        self._windows.append(win)  # держим ссылку, иначе окно соберёт GC

    def _start_copy(self, src, dst, replace: bool = False,
                    keep_storage: bool = True) -> None:
        dlg = CopyDialog(src, dst, replace=replace, keep_storage=keep_storage,
                         parent=self.window())
        dlg.worker.done.connect(lambda _ok, _p: self._update_status())
        dlg.show()
        self._windows.append(dlg)

    def _update_template(self) -> None:
        t = self._template_dir()
        entry = self.catalog_entry()
        if not t or not entry:
            return
        win = DownloadWindow(entry, t.parent, t.name, replace=True,
                             keep_storage=False, mods_dir=self._mods_dl_dir())
        win.finished_ok.connect(lambda _p: self._update_status())
        win.show()
        self._windows.append(win)

    def _recreate_mission(self) -> None:
        d = self._mission_dir()
        t = self._template_dir()
        if not d or not t or not t.is_dir():
            return
        dlg = UpdateMissionDialog(d.name, self.window())
        if not dlg.exec():
            return
        self._start_copy(t, d, replace=True,
                         keep_storage=dlg.keep_storage.isChecked())
