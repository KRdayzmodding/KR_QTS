"""Создание пресетов — «Ленивый» мастер; «Расширенный» редактор — для правки уже созданных."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout, QFileDialog,
    QGroupBox, QWizardPage, QWidget,
)
from qfluentwidgets import (
    LineEdit, ComboBox, CheckBox, SpinBox, PushButton, PrimaryPushButton,
    ToolButton, RadioButton, BodyLabel, CaptionLabel, FluentIcon as FIF,
)

from core.i18n import tr
from core.params import specs_for, FLAG, SWITCH, INT, SERVER, CLIENT
from core.presets import ServerPreset, MODE_DIAG, MODE_DEDICATED
from core.settings import Settings, STABLE, EXPERIMENTAL
from ui.mission_picker import MapPicker
from ui.theme import ThemedDialog, ThemedWizard


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


# Параметры запуска новых пресетов — отладочный набор «как надо»:
# полное логирование на сервере, окно вместо фуллскрина на клиенте,
# быстрый вход/выход. Diag-набор добавляется поверх для режима отладки.
_DEFAULT_PARAMS_SERVER = {
    "doLogs": True, "adminLog": True, "netLog": True, "noPause": True,
}
_DEFAULT_PARAMS_CLIENT = {
    "noPause": True, "window": True,
}
_DEFAULT_PARAMS_DIAG = {
    "filePatching": True, "battleye": False, "newErrorsAreWarnings": True,
}
# TimeLogin/TimeLogout в db/globals.xml миссии, секунды. Единица, а не
# ванильные 15: при отладке сервер перезапускают десятки раз за сессию,
# и каждый лишний тик ожидания входа платится живым временем.
_DEFAULT_TIME_LOGIN = 1


def _attach_map_mods(preset: ServerPreset, picker: MapPicker) -> None:
    """Моды карты (из репозитория миссии) автоматически включаются в пресет."""
    from pathlib import Path as _P
    entry = picker.catalog_entry()
    if not entry:
        return
    for spec in getattr(entry, "mods", []):
        mod_name = _P(spec.get("path", "")).name.lstrip("@")
        if mod_name and mod_name not in preset.mods:
            preset.mods.append(mod_name)


# ---------------------------------------------------------------- Расширенный

class AdvancedPresetDialog(ThemedDialog):
    def __init__(self, preset: ServerPreset, settings: Settings, parent=None):
        super().__init__(parent)
        self.preset = preset
        self.settings = settings
        # пара имя+карта на момент открытия: совпадение с самим собой — не конфликт
        from core.layout import preset_key
        self._original_key = (preset_key(preset.name, preset.world)
                              if preset.path().exists() else "")
        self.setWindowTitle(tr("preset.edit_title", "Пресет: {n}", n=preset.name))
        self.resize(760, 680)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name = LineEdit()
        self.name.setText(preset.name)
        form.addRow(tr("preset.name", "Название"), self.name)
        self.name_error = CaptionLabel("")
        self.name_error.setStyleSheet("color:#d32f2f;")
        self.name_error.setWordWrap(True)
        form.addRow("", self.name_error)

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

        # доступность режима/ветки — только если нужные exe реально на месте
        diag_ok = bool(settings.client_stable) and \
            (Path(settings.client_stable) / "DayZDiag_x64.exe").is_file()
        dedicated_ok = bool(settings.server_stable) and \
            (Path(settings.server_stable) / "DayZServer_x64.exe").is_file()
        self.mode.setItemEnabled(0, diag_ok)
        self.mode.setItemEnabled(1, dedicated_ok)
        if not diag_ok and self.mode.currentIndex() == 0 and dedicated_ok:
            self.mode.setCurrentIndex(1)
        elif not dedicated_ok and self.mode.currentIndex() == 1 and diag_ok:
            self.mode.setCurrentIndex(0)

        exp_ok = (bool(settings.client_exp) and Path(settings.client_exp).is_dir()) or \
            (bool(settings.server_exp) and Path(settings.server_exp).is_dir())
        self.branch.setItemEnabled(1, exp_ok)
        if not exp_ok and self.branch.currentIndex() == 1:
            self.branch.setCurrentIndex(0)

        self.map_picker = MapPicker(self)
        self.map_picker.set_context(settings, preset.branch, preset.mode,
                                    preset.name, current_mission=preset.mission)
        self.mode.currentIndexChanged.connect(self._mission_ctx)
        self.branch.currentIndexChanged.connect(self._mission_ctx)
        self.name.textChanged.connect(self._name_changed)
        self.map_picker.changed.connect(self._files_hint_update)
        form.addRow(tr("preset.map", "Карта"), self.map_picker)
        self.files_hint = CaptionLabel("")
        self.files_hint.setWordWrap(True)
        form.addRow("", self.files_hint)
        self._name_changed(preset.name)

        self.port = SpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(preset.port)
        form.addRow(tr("preset.port", "Порт"), self.port)

        self.time_login = SpinBox()
        self.time_login.setRange(0, 3600)
        self.time_login.setToolTip(tr("preset.time_login_tip",
                                      "TimeLogin и TimeLogout в db\\globals.xml миссии — "
                                      "таймеры ожидания при входе и выходе. Задаются одним "
                                      "значением; для отладки удобно 0."))
        self.time_login.setValue(self._read_time_login())
        form.addRow(tr("preset.time_login", "Время на вход/выход (секунды)"), self.time_login)

        clean_row = QHBoxLayout()
        b_clear_db = PushButton(FIF.DELETE, tr("preset.clear_db", "Очистить БД"))
        b_clear_db.setToolTip(tr("preset.clear_db_tip",
                                 "Удаляет папки storage_* в миссии пресета — обнуление "
                                 "персистентности (лут, персонажи, постройки)."))
        b_clear_db.clicked.connect(self._clear_storage)
        b_clear_prof = PushButton(FIF.BROOM, tr("preset.clear_prof", "Очистить профайл"))
        b_clear_prof.setToolTip(tr("preset.clear_prof_tip",
                                   "Полностью чистит папку профиля сервера (логи, настройки модов)."))
        b_clear_prof.clicked.connect(self._clear_profile)
        b_admin = PushButton(FIF.PEOPLE, tr("preset.admin_sync",
                                            "Актуализировать данные для Admin Tools"))
        b_admin.setToolTip(tr("preset.admin_sync_tip",
                              "Перезаписывает в профиле списки админов и пароль VPP "
                              "из «Настроек» — для COT, VPPAdminTools и LBmaster."))
        b_admin.clicked.connect(self._sync_admin_tools)
        b_open_prof = PushButton(FIF.FOLDER, tr("preset.open_prof", "Открыть папку профиля"))
        b_open_prof.setToolTip(tr("preset.open_prof_tip",
                                  "Открывает папку профиля сервера в проводнике."))
        b_open_prof.clicked.connect(self._open_profile)
        clean_row.addWidget(b_clear_db)
        clean_row.addWidget(b_clear_prof)
        clean_row.addWidget(b_admin)
        clean_row.addWidget(b_open_prof)
        clean_row.addStretch(1)
        form.addRow("", clean_row)
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

    def _clear_storage(self) -> None:
        from qfluentwidgets import MessageBox, InfoBar, InfoBarPosition
        from core.layout import clear_mission_storage
        mission = self.map_picker.mission_name()
        box = MessageBox(tr("preset.clear_db", "Очистить БД"),
                         tr("preset.clear_db_confirm",
                            "Удалить storage_* в миссии «{m}»?\nЛут, персонажи и постройки "
                            "будут сброшены.", m=mission or "?"), self)
        if not box.exec():
            return
        n = clear_mission_storage(self.settings, self.branch.currentData(),
                                  self.mode.currentData(), mission)
        InfoBar.success(title=tr("preset.cleared_db", "Удалено storage-папок: {n}", n=n),
                        content="", parent=self, duration=3000,
                        position=InfoBarPosition.TOP_RIGHT)

    def _clear_profile(self) -> None:
        from qfluentwidgets import MessageBox, InfoBar, InfoBarPosition
        from core.launcher import dayz_running
        from core.layout import clear_profile, preset_base_name
        if dayz_running():
            InfoBar.warning(title=tr("preset.busy_title", "Сервер запущен"),
                            content=tr("preset.busy_body",
                                       "Остановите сервер — он держит файлы профиля открытыми "
                                       "и перезапишет их при выходе."),
                            parent=self, duration=6000, position=InfoBarPosition.TOP_RIGHT)
            return
        profiles = self.preset.profiles or preset_base_name(
            self.name.text().strip(), self.map_picker.mission_name())
        box = MessageBox(tr("preset.clear_prof", "Очистить профайл"),
                         tr("preset.clear_prof_confirm",
                            "Полностью очистить папку профиля «{p}»?", p=profiles or "?"),
                         self)
        if not box.exec():
            return
        n = clear_profile(self.settings, self.branch.currentData(),
                          self.mode.currentData(), profiles)
        InfoBar.success(title=tr("preset.cleared_prof", "Удалено элементов: {n}", n=n),
                        content="", parent=self, duration=3000,
                        position=InfoBarPosition.TOP_RIGHT)

    def _profile_dir(self) -> str:
        """Абсолютный путь папки профиля для текущих значений формы."""
        from core.layout import resolve_profiles, preset_base_name
        profiles = self.preset.profiles or preset_base_name(
            self.name.text().strip(), self.map_picker.mission_name())
        return resolve_profiles(profiles, self.settings, self.branch.currentData(),
                                self.mode.currentData())

    def _open_profile(self) -> None:
        import os
        from qfluentwidgets import InfoBar, InfoBarPosition
        path = self._profile_dir()
        if not path or not Path(path).is_dir():
            InfoBar.warning(title=tr("preset.no_profile",
                                     "Папки профиля ещё нет — она создастся при запуске."),
                            content=path or "", parent=self, duration=5000,
                            position=InfoBarPosition.TOP_RIGHT)
            return
        os.startfile(path)  # noqa: S606 — открытие проводника по своей же папке

    def _sync_admin_tools(self) -> None:
        from qfluentwidgets import InfoBar, InfoBarPosition
        from core.admin_tools import apply as apply_admin_rights
        s = self.settings
        if not s.admin_steamids and not s.admin_password.strip():
            InfoBar.warning(title=tr("preset.admin_sync_empty",
                                     "В настройках не заданы ни SteamID админов, ни пароль."),
                            content="", parent=self, duration=5000,
                            position=InfoBarPosition.TOP_RIGHT)
            return
        # mods=None — обновляем обе админки: какая из них подключена к пресету,
        # тут неважно, лишние файлы никому не мешают
        done = apply_admin_rights(self._profile_dir(), None, s.admin_steamids, s.admin_password)
        InfoBar.success(title=tr("preset.admin_synced", "Обновлено админок: {n}", n=len(done)),
                        content=", ".join(t.title for t, _ in done),
                        parent=self, duration=4000, position=InfoBarPosition.TOP_RIGHT)

    def _read_time_login(self) -> int:
        """Актуальное значение из globals.xml миссии; иначе из пресета;
        иначе значение по умолчанию."""
        from pathlib import Path as _P
        from core.layout import resolve_mission
        from core.missions import read_global_var
        p = self.preset
        mission = resolve_mission(p.mission, self.settings, p.branch, p.mode)
        if mission:
            val = read_global_var(_P(mission), "TimeLogin")
            if val is not None:
                try:
                    return int(float(val))
                except ValueError:
                    pass
        return p.time_login if p.time_login >= 0 else _DEFAULT_TIME_LOGIN

    def _mission_ctx(self) -> None:
        self.map_picker.set_context(self.settings, self.branch.currentData(),
                                    self.mode.currentData(),
                                    self.name.text().strip(),
                                    current_mission=self.map_picker.mission_name())

    def _name_changed(self, name: str) -> None:
        self.name.setError(False)
        self.name_error.setText("")
        self.map_picker.set_preset_name(name.strip())

    def _files_hint_update(self) -> None:
        from core.layout import DEBUG_DIR, PROFILE_SUBDIR
        name = self.name.text().strip() or "?"
        world = self.map_picker.world()
        fname = f"{name}_{world}" if world else name
        self.files_hint.setText(tr(
            "preset.files_hint",
            "Файлы пресета: {d}\\{f}.cfg,  {d}\\{p}\\{f},  миссия — см. выше.",
            d=DEBUG_DIR, p=PROFILE_SUBDIR, f=fname))

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
        from core.layout import (valid_name, name_conflict, create_preset_files,
                                 rename_preset_files)
        p = self.preset
        new_name = self.name.text().strip() or p.name
        if not valid_name(new_name):
            problem = tr("preset.bad_name_full",
                         "Недопустимое название. Разрешены только латинские буквы, "
                         "цифры, «-» и «_» — без кириллицы и пробелов, "
                         "и начинаться оно должно с буквы. "
                         "Например: my_test_server")
            self.name.setError(True)
            self.name.setToolTip(problem)
            self.name_error.setText(problem)
            return
        world = self.map_picker.world()
        conflict = name_conflict(new_name, world, current_key=self._original_key)
        if conflict:
            self.name.setError(True)
            self.name.setToolTip(conflict)
            self.name_error.setText(conflict)
            return
        if new_name != p.name:
            rename_preset_files(self.settings, self.branch.currentData(),
                                self.mode.currentData(), p.name, new_name, world)
            p.name = new_name  # save() сам уберёт старый файл пресета
            self.map_picker.set_preset_name(new_name)
        p.mode = self.mode.currentData()
        p.branch = self.branch.currentData()
        p.mission = self.map_picker.mission_name()
        # конфиг и профиль всегда следуют имени пресета
        try:
            p.server_config, p.profiles = create_preset_files(
                self.settings, p.branch, p.mode, p.name, p.mission)
        except RuntimeError:
            pass  # корень не задан — предстартовая проверка подскажет
        _attach_map_mods(p, self.map_picker)
        p.port = self.port.value()
        p.time_login = self.time_login.value()
        # применяем сразу, если миссия уже на диске (иначе — перед запуском)
        from pathlib import Path as _P
        from core.layout import resolve_mission
        from core.missions import set_global_var
        mission_path = resolve_mission(p.mission, self.settings, p.branch, p.mode)
        if mission_path and _P(mission_path).is_dir():
            set_global_var(_P(mission_path), "TimeLogin", str(p.time_login))
            set_global_var(_P(mission_path), "TimeLogout", str(p.time_login))
        p.params_server = self._collect_params(SERVER)
        p.params_client = self._collect_params(CLIENT)
        p.extra_server = self.extra_server.text().strip()
        p.extra_client = self.extra_client.text().strip()
        p.save()
        self.map_picker.ensure_mission()  # миссии нет — стартует модальная загрузка
        self.accept()


# ---------------------------------------------------------------- Ленивый мастер

class LazyPresetWizard(ThemedWizard):
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
        self.name.setPlaceholderText(tr("preset.lazy_name_ph", "Например: my_test_server"))
        self.name.textChanged.connect(lambda _t: self._clear_name_error())
        l1.addWidget(BodyLabel(tr("preset.name", "Название")))
        l1.addWidget(self.name)
        self.name_error = CaptionLabel("")
        self.name_error.setStyleSheet("color:#d32f2f;")
        self.name_error.setWordWrap(True)
        l1.addWidget(self.name_error)
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

        # доступность режимов — только если нужный exe реально на месте
        diag_ok = bool(settings.client_stable) and \
            (Path(settings.client_stable) / "DayZDiag_x64.exe").is_file()
        dedicated_ok = bool(settings.server_stable) and \
            (Path(settings.server_stable) / "DayZServer_x64.exe").is_file()
        if not diag_ok:
            self.rb_diag.setEnabled(False)
            diag_desc.setEnabled(False)
            no_diag = tr("preset.lazy_diag_missing",
                        "DayZDiag_x64.exe не найден — укажите папку игры в «Настройках».")
            self.rb_diag.setToolTip(no_diag)
            diag_desc.setToolTip(no_diag)
        if not dedicated_ok:
            self.rb_dedicated.setEnabled(False)
            ded_desc.setEnabled(False)
            no_ded = tr("preset.lazy_dedicated_missing",
                       "DayZServer_x64.exe не найден — укажите папку сервера в «Настройках».")
            self.rb_dedicated.setToolTip(no_ded)
            ded_desc.setToolTip(no_ded)
        if not diag_ok and dedicated_ok:
            self.rb_dedicated.setChecked(True)
        p1.registerField("name*", self.name)
        self.addPage(p1)

        # Шаг 2: карта (имена конфига/профиля/миссии следуют имени пресета)
        p2 = QWizardPage()
        p2.setTitle(tr("preset.lazy_p2", "Карта"))
        l2 = QFormLayout(p2)
        self.map_picker = MapPicker(p2)
        self.rb_diag.toggled.connect(lambda _on: self._sync_map_ctx())
        self.map_picker.changed.connect(self._update_note)
        l2.addRow(tr("preset.map", "Карта"), self.map_picker)
        self.auto_note = CaptionLabel("")
        self.auto_note.setWordWrap(True)
        l2.addRow("", self.auto_note)
        self.addPage(p2)
        self._p2 = p2

        # Шаг 3: финиш
        p3 = QWizardPage()
        p3.setTitle(tr("common.done", "Готово"))
        l3 = QVBoxLayout(p3)
        l3.addWidget(BodyLabel(tr("preset.lazy_done",
                               "Пресет будет создан с разумными настройками по умолчанию.\n"
                               "Моды подключаются на вкладке «Моды», параметры — в «Расширенном» редакторе.")))
        self.addPage(p3)

        self.currentIdChanged.connect(self._page_changed)

    def _sync_map_ctx(self) -> None:
        mode = MODE_DIAG if self.rb_diag.isChecked() else MODE_DEDICATED
        self.map_picker.set_context(self.settings, STABLE, mode,
                                    self.name.text().strip())

    def _page_changed(self, _id: int) -> None:
        if self.currentPage() is self._p2:
            self._sync_map_ctx()
            self._update_note()

    def _update_note(self) -> None:
        from core.layout import DEBUG_DIR, PROFILE_SUBDIR
        name = self.name.text().strip()
        world = self.map_picker.world()
        fname = f"{name}_{world}" if world else name
        self.auto_note.setText(tr(
            "preset.lazy_auto",
            "Конфиг и профиль будут созданы автоматически:\n"
            "{d}\\{f}.cfg  и  {d}\\{p}\\{f}", d=DEBUG_DIR, p=PROFILE_SUBDIR, f=fname))

    def _clear_name_error(self) -> None:
        self.name.setError(False)
        self.name_error.setText("")

    def validateCurrentPage(self) -> bool:  # имя метода задаёт Qt
        from core.layout import valid_name, name_conflict
        if self.currentId() == 0:
            name = self.name.text().strip()
            problem = ""
            if not valid_name(name):
                problem = tr("preset.bad_name_full",
                             "Недопустимое название. Разрешены только латинские буквы, "
                             "цифры, «-» и «_» — без кириллицы и пробелов, "
                             "и начинаться оно должно с буквы. "
                             "Например: my_test_server")
            else:
                problem = name_conflict(name)
            if problem:
                self.name.setError(True)
                self.name.setToolTip(problem)
                self.name_error.setText(problem)
                return False
        return super().validateCurrentPage()

    def accept(self) -> None:
        from core.layout import create_preset_files, name_conflict
        diag = self.rb_diag.isChecked()
        name = self.name.text().strip()
        mode = MODE_DIAG if diag else MODE_DEDICATED
        mission = self.map_picker.mission_name()
        conflict = name_conflict(name, self.map_picker.world())
        if conflict:
            self.auto_note.setText(conflict)
            return
        try:
            config, profiles = create_preset_files(self.settings, STABLE, mode,
                                                   name, mission)
        except RuntimeError as e:
            self.auto_note.setText(str(e))
            return
        preset = ServerPreset(name=name, mode=mode, server_config=config,
                              mission=mission, profiles=profiles,
                              time_login=_DEFAULT_TIME_LOGIN)
        preset.params_server = dict(_DEFAULT_PARAMS_SERVER)
        preset.params_client = dict(_DEFAULT_PARAMS_CLIENT)
        if diag:
            preset.params_server.update(_DEFAULT_PARAMS_DIAG)
            preset.params_client.update(_DEFAULT_PARAMS_DIAG)
        _attach_map_mods(preset, self.map_picker)
        preset.save()
        self.result_preset = preset
        self.map_picker.ensure_mission()  # миссии нет — стартует модальная загрузка
        super().accept()
