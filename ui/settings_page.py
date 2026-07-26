"""Страница общих настроек (Fluent)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFileDialog, QScrollArea,
)
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from qfluentwidgets import (
    LineEdit, PasswordLineEdit, PlainTextEdit, ComboBox,
    PushButton, PrimaryPushButton, ToolButton, BodyLabel, CaptionLabel,
    StrongBodyLabel, FluentIcon as FIF, setTheme, Theme,
)

from pathlib import Path

from core import autodetect
from core.i18n import tr, AVAILABLE
from core.settings import Settings, find_pbo_project_exe
from ui.pboproject_dialog import PboProjectDialog


class PathRow(QHBoxLayout):
    def __init__(self, value: str, parent: QWidget):
        super().__init__()
        self.edit = LineEdit()
        self.edit.setText(value)
        btn = ToolButton(FIF.FOLDER)

        def browse():
            p = QFileDialog.getExistingDirectory(parent, "", self.edit.text())
            if p:
                self.edit.setText(p)

        btn.clicked.connect(browse)
        self.addWidget(self.edit, 1)
        self.addWidget(btn)

    def text(self) -> str:
        return self.edit.text().strip()


class SettingsPage(QScrollArea):
    def __init__(self, settings: Settings, on_saved=None):
        super().__init__()
        self.settings = settings
        self.on_saved = on_saved
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setStyleSheet("QScrollArea{background:transparent;} QWidget#settingsInner{background:transparent;}")

        inner = QWidget()
        inner.setObjectName("settingsInner")
        self.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)

        def section(title: str) -> QFormLayout:
            heading = StrongBodyLabel(title)
            layout.addWidget(heading)
            f = QFormLayout()
            f.setSpacing(8)
            layout.addLayout(f)
            layout.addSpacing(6)
            return f

        # ------------------------------------------------------------ Общее
        form_general = section(tr("settings.section_general", "Общее"))
        self.lang = ComboBox()
        for code, label in AVAILABLE.items():
            self.lang.addItem(label, userData=code)
        codes = list(AVAILABLE)
        self.lang.setCurrentIndex(codes.index(settings.language)
                                  if settings.language in codes else 0)
        form_general.addRow(BodyLabel(tr("settings.language", "Язык (нужен перезапуск)")), self.lang)

        self.project_prefix = LineEdit()
        self.project_prefix.setText(settings.project_prefix)
        self.project_prefix.setPlaceholderText(tr("settings.prefix_ph", "Например: KR"))
        self.project_prefix.setToolTip(tr("settings.prefix_tip",
                                          "Подставляется в hostname создаваемых серверов."))
        form_general.addRow(BodyLabel(tr("settings.prefix_label", "Префикс проекта")), self.project_prefix)

        self.theme = ComboBox()
        self.theme.addItem(tr("settings.theme_auto", "Как в системе"), userData="auto")
        self.theme.addItem(tr("settings.theme_light", "Светлая"), userData="light")
        self.theme.addItem(tr("settings.theme_dark", "Тёмная"), userData="dark")
        theme_codes = ["auto", "light", "dark"]
        self.theme.setCurrentIndex(theme_codes.index(settings.theme)
                                   if settings.theme in theme_codes else 0)
        self.theme.currentIndexChanged.connect(self._theme_changed)
        form_general.addRow(BodyLabel(tr("settings.theme_label", "Тема оформления")), self.theme)

        # ------------------------------------------------------------ Пути
        form_paths = section(tr("settings.section_paths", "Пути"))
        self.p_client = PathRow(settings.client_stable, self)
        self.p_client_exp = PathRow(settings.client_exp, self)
        self.p_server = PathRow(settings.server_stable, self)
        self.p_server_exp = PathRow(settings.server_exp, self)
        self.p_mikero = PathRow(settings.mikero_tools, self)
        self.p_tools = PathRow(settings.dayz_tools, self)
        form_paths.addRow(BodyLabel(tr("settings.client", "Папка игры (DayZ)")), self.p_client)
        form_paths.addRow(BodyLabel(tr("settings.client_exp", "Папка игры Experimental")), self.p_client_exp)
        form_paths.addRow(BodyLabel(tr("settings.server", "Папка сервера (DayZServer)")), self.p_server)
        form_paths.addRow(BodyLabel(tr("settings.server_exp", "Папка сервера Experimental")), self.p_server_exp)
        form_paths.addRow(BodyLabel(tr("settings.mikero", "Mikero Tools (DePboTools)")), self.p_mikero)
        form_paths.addRow(BodyLabel(tr("settings.dayz_tools", "DayZ Tools")), self.p_tools)

        self.workshop = PlainTextEdit()
        self.workshop.setPlainText("\n".join(settings.workshop_dirs))
        self.workshop.setMaximumHeight(64)
        self.workshop.setToolTip(tr("settings.workshop_tip",
                                    "Папки steamapps/workshop/content/221100 — по одной на строку."))
        form_paths.addRow(BodyLabel(tr("settings.workshop", "Папки Steam Workshop")), self.workshop)

        self.p_downloads = PathRow(settings.downloads_dir, self)
        self.p_downloads.edit.setPlaceholderText(tr("settings.downloads_ph",
                                                    "<папка программы>\\downloads"))
        self.p_downloads.edit.setToolTip(tr("settings.downloads_tip",
                                            "Общее хранилище скачанных модов карт; во все корни "
                                            "они подключаются junction-ссылками."))
        form_paths.addRow(BodyLabel(tr("settings.downloads", "Папка загрузок")), self.p_downloads)

        # ------------------------------------------------------------ Steam
        form_steam = section(tr("settings.section_steam", "Steam"))
        self.admin_ids = PlainTextEdit()
        self.admin_ids.setPlainText("\n".join(settings.admin_steamids))
        self.admin_ids.setMaximumHeight(64)
        self.admin_ids.setToolTip(tr("settings.admins_tip",
                                     "SteamID64 админов — по одному на строку. Используется модами-админками."))
        form_steam.addRow(BodyLabel(tr("settings.admins", "Админские SteamID")), self.admin_ids)

        self.admin_pass = PasswordLineEdit()
        self.admin_pass.setText(settings.admin_password)
        form_steam.addRow(BodyLabel(tr("settings.admin_pass", "Пароль модов-админок")), self.admin_pass)

        steam_row = QHBoxLayout()
        self.steam_key = PasswordLineEdit()
        self.steam_key.setText(settings.steam_api_key)
        btn_get_key = PushButton(FIF.LINK, tr("settings.steam_key_get", "Получить"))
        btn_get_key.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl("https://steamcommunity.com/dev/apikey")))
        steam_row.addWidget(self.steam_key, 1)
        steam_row.addWidget(btn_get_key)
        form_steam.addRow(BodyLabel(tr("settings.steam_key", "Steam API-ключ")), steam_row)
        steam_hint = CaptionLabel(tr(
            "settings.steam_key_hint",
            "Нужен для определения зависимостей стим-модов через официальный API. "
            "Как получить: нажмите «Получить», войдите в Steam, в поле «Domain Name» "
            "впишите что угодно (например, localhost), согласитесь с условиями и "
            "скопируйте ключ сюда. Без ключа зависимости читаются со страницы "
            "воркшопа — работает, но менее надёжно."))
        steam_hint.setWordWrap(True)
        form_steam.addRow("", steam_hint)

        # ------------------------------------------------------------ Запаковка
        form_pack = section(tr("settings.section_pack", "Запаковка модов"))
        self._pack_flags = settings.pack_flags
        self._clean_meta = settings.clean_meta
        self.b_pbo_settings = PushButton(FIF.SETTING, tr("settings.pbo_settings", "Настройки PboProject"))
        self.b_pbo_settings.clicked.connect(self._open_pbo_settings)
        form_pack.addRow(BodyLabel(tr("settings.pbo_settings_label", "Запаковка PBO")), self.b_pbo_settings)

        self.pack_engine = ComboBox()
        self.pack_engine.addItem(tr("settings.engine_full", "Полная, с проверками (pboProject)"),
                                 userData="full")
        self.pack_engine.addItem(tr("settings.engine_fast", "Быстрая, без проверок (pbo_packer)"),
                                 userData="fast")
        self.pack_engine.setCurrentIndex(1 if settings.pack_engine == "fast" else 0)
        self.pack_engine.setToolTip(tr("settings.engine_tip",
                                       "pbo_packer в разы быстрее, но не проверяет ошибки и не "
                                       "подписывает pbo — только для локальной отладки."))
        form_pack.addRow(BodyLabel(tr("settings.engine_label", "Способ запаковки модов")), self.pack_engine)

        self.p_mikero.edit.textChanged.connect(self._update_pbo_button_state)
        self._update_pbo_button_state()

        btns = QHBoxLayout()
        btn_detect = PushButton(FIF.SEARCH, tr("settings.autodetect",
                                               "Автопоиск незаполненных путей"))
        btn_detect.clicked.connect(self._autodetect)
        btn_save = PrimaryPushButton(FIF.SAVE, tr("common.save", "Сохранить"))
        btn_save.clicked.connect(self._save)
        btns.addWidget(btn_detect)
        btns.addStretch(1)
        btns.addWidget(btn_save)
        layout.addLayout(btns)

        self.note = CaptionLabel("")
        layout.addWidget(self.note)
        layout.addStretch(1)

    def _theme_changed(self, _idx: int) -> None:
        code = self.theme.currentData()
        setTheme({"light": Theme.LIGHT, "dark": Theme.DARK, "auto": Theme.AUTO}
                .get(code, Theme.AUTO))
        self.settings.theme = code
        self.settings.save()

    def _autodetect(self) -> None:
        det = autodetect.detect_all()
        pairs = [
            (self.p_client, det["client_stable"]), (self.p_client_exp, det["client_exp"]),
            (self.p_server, det["server_stable"]), (self.p_server_exp, det["server_exp"]),
            (self.p_mikero, det["mikero_tools"]), (self.p_tools, det["dayz_tools"]),
        ]
        filled = 0
        for row, val in pairs:
            if not row.text() and val:
                row.edit.setText(val)
                filled += 1
        if not self.workshop.toPlainText().strip() and det["workshop_dirs"]:
            self.workshop.setPlainText("\n".join(det["workshop_dirs"]))
            filled += 1
        self.note.setText(tr("settings.detected", "Заполнено полей: {n}", n=filled))

    def _update_pbo_button_state(self) -> None:
        found = Path(find_pbo_project_exe(self.p_mikero.text())).is_file()
        self.b_pbo_settings.setEnabled(found)
        self.b_pbo_settings.setToolTip(
            tr("settings.pbo_settings_tip",
              "Флаги командной строки pboProject: подпись, сжатие, "
              "обработка файлов и т.д. — с пояснениями по каждому.")
            if found else
            tr("settings.pbo_settings_missing",
              "pboProject не найден по указанному пути Mikero Tools — "
              "укажите правильный путь, чтобы открыть эти настройки."))

        self.pack_engine.setItemEnabled(0, found)
        if not found and self.pack_engine.currentData() == "full":
            self.pack_engine.setCurrentIndex(1)
        self.pack_engine.setItemText(
            0,
            tr("settings.engine_full", "Полная, с проверками (pboProject)") if found else
            tr("settings.engine_full_missing",
              "Полная, с проверками (pboProject) — недоступно, pboProject не найден"))

    def _open_pbo_settings(self) -> None:
        dlg = PboProjectDialog(self._pack_flags, self._clean_meta, self)
        if dlg.exec():
            self._pack_flags = dlg.result_flags() or "-P -K"
            self._clean_meta = dlg.result_clean_meta()

    def _save(self) -> None:
        s = self.settings
        s.language = self.lang.currentData()
        s.project_prefix = self.project_prefix.text().strip()
        s.client_stable = self.p_client.text()
        s.client_exp = self.p_client_exp.text()
        s.server_stable = self.p_server.text()
        s.server_exp = self.p_server_exp.text()
        s.mikero_tools = self.p_mikero.text()
        s.dayz_tools = self.p_tools.text()
        s.workshop_dirs = [x.strip() for x in self.workshop.toPlainText().splitlines() if x.strip()]
        # local_mods_dirs больше не редактируется на этой странице — управляется
        # с вкладки «Моды» (кнопка «Добавить локальные моды»), не перезаписываем
        s.admin_steamids = [x.strip() for x in self.admin_ids.toPlainText().splitlines() if x.strip()]
        s.admin_password = self.admin_pass.text()
        s.steam_api_key = self.steam_key.text().strip()
        s.downloads_dir = self.p_downloads.text()
        s.pack_flags = self._pack_flags
        s.clean_meta = self._clean_meta
        s.pack_engine = self.pack_engine.currentData()
        s.save()
        if self.on_saved:
            self.on_saved()
