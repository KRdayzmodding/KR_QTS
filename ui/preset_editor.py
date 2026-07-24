"""Создание и редактирование пресетов: «Ленивый» мастер и «Расширенный» редактор."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QFileDialog,
    QGroupBox, QWizard, QWizardPage, QMessageBox, QWidget,
)
from qfluentwidgets import (
    LineEdit, ComboBox, CheckBox, SpinBox, PushButton, PrimaryPushButton,
    ToolButton, RadioButton, BodyLabel, CaptionLabel, FluentIcon as FIF,
)

from core.i18n import tr
from core.params import specs_for, FLAG, SWITCH, INT, STR, SERVER, CLIENT
from core.presets import ServerPreset, MODE_DIAG, MODE_DEDICATED
from core.settings import Settings, STABLE, EXPERIMENTAL
from ui.mission_picker import MissionPicker


def choose_creation_mode(parent) -> str | None:
    """Возвращает 'lazy' | 'advanced' | None."""
    box = QMessageBox(parent)
    box.setWindowTitle(tr("preset.new_title", "Новый пресет"))
    box.setText(tr("preset.new_question",
                   "Как создать пресет?\n\n«Ленивый» — несколько простых шагов с подсказками.\n"
                   "«Расширенный» — все настройки сразу на одной форме."))
    b_lazy = box.addButton(tr("preset.lazy", "Ленивый"), QMessageBox.ButtonRole.AcceptRole)
    b_adv = box.addButton(tr("preset.advanced", "Расширенный"), QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    if box.clickedButton() == b_lazy:
        return "lazy"
    if box.clickedButton() == b_adv:
        return "advanced"
    return None


class _PathField(QHBoxLayout):
    def __init__(self, parent: QWidget, value: str, pick_dir: bool, root_hint: str = ""):
        super().__init__()
        self.parent_widget = parent
        self.pick_dir = pick_dir
        self.root_hint = root_hint
        self.edit = LineEdit()
        self.edit.setText(value)
        btn = ToolButton(FIF.FOLDER if pick_dir else FIF.DOCUMENT)
        btn.clicked.connect(self._browse)
        self.addWidget(self.edit, 1)
        self.addWidget(btn)

    def _browse(self) -> None:
        start = self.edit.text() or self.root_hint
        if self.pick_dir:
            p = QFileDialog.getExistingDirectory(self.parent_widget, "", start)
        else:
            p, _ = QFileDialog.getOpenFileName(self.parent_widget, "", start)
        if p:
            # Если путь внутри корня клиента — храним относительный (читабельнее)
            if self.root_hint and p.lower().startswith(self.root_hint.lower().rstrip("\\/") + "/") \
               or self.root_hint and p.lower().startswith(self.root_hint.lower().rstrip("\\/") + "\\"):
                p = p[len(self.root_hint.rstrip("\\/")) + 1:]
            self.edit.setText(p)

    def text(self) -> str:
        return self.edit.text().strip()


# ---------------------------------------------------------------- Расширенный

class AdvancedPresetDialog(QDialog):
    def __init__(self, preset: ServerPreset, settings: Settings, parent=None):
        super().__init__(parent)
        self.preset = preset
        self.settings = settings
        self.setWindowTitle(tr("preset.edit_title", "Пресет: {n}", n=preset.name))
        self.resize(760, 680)
        root_hint = settings.client_root(preset.branch)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name = LineEdit()
        self.name.setText(preset.name)
        form.addRow(tr("preset.name", "Название"), self.name)

        self.mode = ComboBox()
        self.mode.addItem(tr("preset.mode_diag",
                             "Diag: DayZDiag_x64 как сервер и клиент (отладка, filepatching)"),
                          userData=MODE_DIAG)
        self.mode.addItem(tr("preset.mode_dedicated",
                             "Dedicated: отдельный DayZServer_x64 + обычный клиент"),
                          userData=MODE_DEDICATED)
        self.mode.setCurrentIndex(0 if preset.mode == MODE_DIAG else 1)
        self.mode.currentIndexChanged.connect(self._rebuild_params)
        form.addRow(tr("preset.mode", "Режим запуска"), self.mode)

        self.branch = ComboBox()
        self.branch.addItem("Stable", userData=STABLE)
        self.branch.addItem("Experimental", userData=EXPERIMENTAL)
        self.branch.setCurrentIndex(0 if preset.branch == STABLE else 1)
        form.addRow(tr("preset.branch", "Ветка по умолчанию"), self.branch)

        self.client_diag = CheckBox(tr("preset.client_diag",
                                       "Подключать клиентом DayZDiag_x64 (для dedicated-режима)"))
        self.client_diag.setChecked(preset.client_use_diag)
        form.addRow("", self.client_diag)

        self.p_config = _PathField(self, preset.server_config, False, root_hint)
        self.p_mission = MissionPicker(self)
        self.p_mission.set_context(settings, preset.branch, preset.mode,
                                   current=preset.mission)
        self.mode.currentIndexChanged.connect(self._mission_ctx)
        self.branch.currentIndexChanged.connect(self._mission_ctx)
        self.p_profiles = _PathField(self, preset.profiles, True, root_hint)
        form.addRow(tr("preset.config", "Серверный конфиг (serverDZ.cfg)"), self.p_config)
        form.addRow(tr("preset.mission", "Миссия"), self.p_mission)
        form.addRow(tr("preset.profiles", "Папка профиля"), self.p_profiles)
        hint = CaptionLabel(tr("preset.path_hint",
                               "Пути можно указывать относительно корня клиента или абсолютные."))
        form.addRow("", hint)

        self.port = SpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(preset.port)
        form.addRow(tr("preset.port", "Порт"), self.port)
        layout.addLayout(form)

        self.params_box = QHBoxLayout()
        layout.addLayout(self.params_box)
        self._param_widgets: dict[tuple[str, str], QWidget] = {}
        self._rebuild_params()

        form2 = QFormLayout()
        self.extra_server = LineEdit()
        self.extra_server.setText(preset.extra_server)
        self.extra_server.setToolTip(tr("preset.extra_tip",
                                        "Любые дополнительные аргументы командной строки."))
        self.extra_client = LineEdit()
        self.extra_client.setText(preset.extra_client)
        self.extra_client.setToolTip(self.extra_server.toolTip())
        form2.addRow(tr("preset.extra_server", "Доп. аргументы сервера"), self.extra_server)
        form2.addRow(tr("preset.extra_client", "Доп. аргументы клиента"), self.extra_client)
        layout.addLayout(form2)

        btns = QHBoxLayout()
        btns.addStretch(1)
        b_cancel = PushButton(tr("common.cancel", "Отмена"))
        b_cancel.clicked.connect(self.reject)
        b_save = PrimaryPushButton(FIF.SAVE, tr("common.save", "Сохранить"))
        b_save.clicked.connect(self._save)
        btns.addWidget(b_cancel)
        btns.addWidget(b_save)
        layout.addLayout(btns)

    def _mission_ctx(self) -> None:
        self.p_mission.set_context(self.settings, self.branch.currentData(),
                                   self.mode.currentData(),
                                   current=self.p_mission.value())

    # Параметры: FLAG -> чекбокс; SWITCH -> комбо (—/вкл/выкл); INT/STR -> строка
    def _rebuild_params(self) -> None:
        while self.params_box.count():
            item = self.params_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._param_widgets = {}
        diag = self.mode.currentData() == MODE_DIAG
        for target, title, values in (
            (SERVER, tr("preset.params_server", "Параметры сервера"), self.preset.params_server),
            (CLIENT, tr("preset.params_client", "Параметры клиента"), self.preset.params_client),
        ):
            box = QGroupBox(title)
            f = QFormLayout(box)
            for spec in specs_for(target, diag):
                w: QWidget
                if spec.ptype == FLAG:
                    w = CheckBox()
                    w.setChecked(bool(values.get(spec.name, False)))
                elif spec.ptype == SWITCH:
                    w = ComboBox()
                    w.addItem("—", userData=None)
                    w.addItem(tr("preset.sw_on", "включено (=1)"), userData=True)
                    w.addItem(tr("preset.sw_off", "выключено (=0)"), userData=False)
                    cur = values.get(spec.name, None)
                    w.setCurrentIndex(0 if cur is None else (1 if cur else 2))
                else:
                    w = LineEdit()
                    w.setText(str(values.get(spec.name, "")))
                    if spec.ptype == INT:
                        w.setPlaceholderText(tr("preset.int_ph", "число или пусто"))
                w.setToolTip(spec.tooltip())
                label = BodyLabel(f"-{spec.name}")
                label.setToolTip(spec.tooltip())
                f.addRow(label, w)
                self._param_widgets[(target, spec.name)] = w
            self.params_box.addWidget(box)

    def _collect_params(self, target: str) -> dict:
        out = {}
        diag = self.mode.currentData() == MODE_DIAG
        for spec in specs_for(target, diag):
            w = self._param_widgets.get((target, spec.name))
            if w is None:
                continue
            if spec.ptype == FLAG:
                if w.isChecked():
                    out[spec.name] = True
            elif spec.ptype == SWITCH:
                val = w.currentData()
                if val is not None:
                    out[spec.name] = val
            else:
                text = w.text().strip()
                if text:
                    if spec.ptype == INT:
                        try:
                            out[spec.name] = int(text)
                        except ValueError:
                            continue
                    else:
                        out[spec.name] = text
        return out

    def _save(self) -> None:
        p = self.preset
        new_name = self.name.text().strip() or p.name
        if new_name != p.name:
            p.delete()  # имя = имя файла, старый убираем
            p.name = new_name
        p.mode = self.mode.currentData()
        p.branch = self.branch.currentData()
        p.client_use_diag = self.client_diag.isChecked()
        p.server_config = self.p_config.text()
        p.mission = self.p_mission.value()
        p.profiles = self.p_profiles.text()
        p.port = self.port.value()
        p.params_server = self._collect_params(SERVER)
        p.params_client = self._collect_params(CLIENT)
        p.extra_server = self.extra_server.text().strip()
        p.extra_client = self.extra_client.text().strip()
        p.save()
        self.accept()


# ---------------------------------------------------------------- Ленивый мастер

class LazyPresetWizard(QWizard):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.result_preset: ServerPreset | None = None
        self.setWindowTitle(tr("preset.lazy_title", "Новый пресет — простой режим"))
        self.resize(640, 480)

        # Шаг 1: имя и режим
        p1 = QWizardPage()
        p1.setTitle(tr("preset.lazy_p1", "Название и режим"))
        l1 = QVBoxLayout(p1)
        self.name = LineEdit()
        self.name.setPlaceholderText(tr("preset.lazy_name_ph", "Например: Мой сервер Черноруси"))
        l1.addWidget(BodyLabel(tr("preset.name", "Название")))
        l1.addWidget(self.name)
        l1.addSpacing(12)
        self.rb_diag = RadioButton(tr("preset.lazy_diag",
                                      "Отладка модов (Diag) — рекомендуется для разработки"))
        diag_desc = CaptionLabel(tr("preset.lazy_diag_desc",
                                    "Игра запускается в диагностическом режиме, работает filepatching."))
        diag_desc.setContentsMargins(28, 0, 0, 0)
        self.rb_dedicated = RadioButton(tr("preset.lazy_dedicated",
                                           "Обычный сервер (Dedicated) — как «настоящий» сервер"))
        ded_desc = CaptionLabel(tr("preset.lazy_dedicated_desc",
                                   "Отдельная серверная программа + обычный клиент."))
        ded_desc.setContentsMargins(28, 0, 0, 0)
        self.rb_diag.setChecked(True)
        l1.addWidget(self.rb_diag)
        l1.addWidget(diag_desc)
        l1.addSpacing(8)
        l1.addWidget(self.rb_dedicated)
        l1.addWidget(ded_desc)
        l1.addStretch(1)
        p1.registerField("name*", self.name)
        self.addPage(p1)

        # Шаг 2: пути
        p2 = QWizardPage()
        p2.setTitle(tr("preset.lazy_p2", "Файлы сервера"))
        l2 = QFormLayout(p2)
        root = settings.client_stable
        self.p_config = _PathField(p2, "", False, root)
        self.p_mission = MissionPicker(p2)
        self.p_mission.set_context(settings, STABLE, MODE_DIAG)
        self.rb_diag.toggled.connect(
            lambda _on: self.p_mission.set_context(
                settings, STABLE,
                MODE_DIAG if self.rb_diag.isChecked() else MODE_DEDICATED,
                current=self.p_mission.value()))
        self.p_profiles = _PathField(p2, "", True, root)
        l2.addRow(tr("preset.lazy_config", "Конфиг сервера (serverDZ.cfg)"), self.p_config)
        l2.addRow(tr("preset.mission", "Миссия"), self.p_mission)
        l2.addRow(tr("preset.lazy_profiles", "Папка профиля (логи и настройки сервера)"), self.p_profiles)
        note = CaptionLabel(tr("preset.lazy_p2_hint",
                               "Профиль можно указать в любую пустую папку — сервер сам её заполнит."))
        l2.addRow("", note)
        self.addPage(p2)

        # Шаг 3: финиш
        p3 = QWizardPage()
        p3.setTitle(tr("common.done", "Готово"))
        l3 = QVBoxLayout(p3)
        l3.addWidget(BodyLabel(tr("preset.lazy_done",
                               "Пресет будет создан с разумными настройками по умолчанию.\n"
                               "Моды подключаются на вкладке «Моды», параметры — в «Расширенном» редакторе.")))
        self.addPage(p3)

    def accept(self) -> None:
        diag = self.rb_diag.isChecked()
        preset = ServerPreset(
            name=self.name.text().strip() or "Новый пресет",
            mode=MODE_DIAG if diag else MODE_DEDICATED,
            server_config=self.p_config.text(),
            mission=self.p_mission.value(),
            profiles=self.p_profiles.text(),
        )
        preset.params_server = {"doLogs": True, "noPause": True}
        preset.params_client = {"noPause": True}
        if diag:
            preset.params_server.update({"filePatching": True, "battleye": False,
                                         "newErrorsAreWarnings": True})
            preset.params_client.update({"filePatching": True, "battleye": False,
                                         "newErrorsAreWarnings": True})
        preset.save()
        self.result_preset = preset
        super().accept()
