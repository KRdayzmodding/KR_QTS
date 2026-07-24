"""Страница общих настроек (Fluent)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFileDialog, QScrollArea,
)
from PySide6.QtCore import Qt
from qfluentwidgets import (
    LineEdit, PasswordLineEdit, PlainTextEdit, ComboBox, CheckBox,
    PushButton, PrimaryPushButton, ToolButton, BodyLabel, CaptionLabel,
    FluentIcon as FIF,
)

from core import autodetect
from core.i18n import tr, AVAILABLE
from core.settings import Settings


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
        form = QFormLayout()
        form.setSpacing(8)

        self.lang = ComboBox()
        for code, label in AVAILABLE.items():
            self.lang.addItem(label, userData=code)
        codes = list(AVAILABLE)
        self.lang.setCurrentIndex(codes.index(settings.language)
                                  if settings.language in codes else 0)
        form.addRow(BodyLabel(tr("settings.language", "Язык (нужен перезапуск)")), self.lang)

        self.p_client = PathRow(settings.client_stable, self)
        self.p_client_exp = PathRow(settings.client_exp, self)
        self.p_server = PathRow(settings.server_stable, self)
        self.p_server_exp = PathRow(settings.server_exp, self)
        self.p_mikero = PathRow(settings.mikero_tools, self)
        self.p_tools = PathRow(settings.dayz_tools, self)
        form.addRow(BodyLabel(tr("settings.client", "Папка игры (DayZ)")), self.p_client)
        form.addRow(BodyLabel(tr("settings.client_exp", "Папка игры Experimental")), self.p_client_exp)
        form.addRow(BodyLabel(tr("settings.server", "Папка сервера (DayZServer)")), self.p_server)
        form.addRow(BodyLabel(tr("settings.server_exp", "Папка сервера Experimental")), self.p_server_exp)
        form.addRow(BodyLabel(tr("settings.mikero", "Mikero Tools (DePboTools)")), self.p_mikero)
        form.addRow(BodyLabel(tr("settings.dayz_tools", "DayZ Tools")), self.p_tools)

        self.workshop = PlainTextEdit()
        self.workshop.setPlainText("\n".join(settings.workshop_dirs))
        self.workshop.setMaximumHeight(64)
        self.workshop.setToolTip(tr("settings.workshop_tip",
                                    "Папки steamapps/workshop/content/221100 — по одной на строку."))
        form.addRow(BodyLabel(tr("settings.workshop", "Папки Steam Workshop")), self.workshop)

        self.admin_ids = PlainTextEdit()
        self.admin_ids.setPlainText("\n".join(settings.admin_steamids))
        self.admin_ids.setMaximumHeight(64)
        self.admin_ids.setToolTip(tr("settings.admins_tip",
                                     "SteamID64 админов — по одному на строку. Используется модами-админками."))
        form.addRow(BodyLabel(tr("settings.admins", "Админские SteamID")), self.admin_ids)

        self.admin_pass = PasswordLineEdit()
        self.admin_pass.setText(settings.admin_password)
        form.addRow(BodyLabel(tr("settings.admin_pass", "Пароль модов-админок")), self.admin_pass)

        self.pack_flags = LineEdit()
        self.pack_flags.setText(settings.pack_flags)
        self.pack_flags.setToolTip(tr("settings.pack_flags_tip",
                                      "Дополнительные флаги pboProject (например -P -K)."))
        form.addRow(BodyLabel(tr("settings.pack_flags", "Флаги запаковки")), self.pack_flags)

        self.clean_meta = CheckBox(tr("settings.clean_meta",
                                      "Удалять *.meta в сорсах перед запаковкой"))
        self.clean_meta.setChecked(settings.clean_meta)
        form.addRow("", self.clean_meta)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btn_detect = PushButton(FIF.SEARCH, tr("settings.autodetect",
                                               "Автопоиск незаполненных путей"))
        btn_detect.clicked.connect(self._autodetect)
        btn_save = PrimaryPushButton(FIF.SAVE, tr("settings.save", "Сохранить"))
        btn_save.clicked.connect(self._save)
        btns.addWidget(btn_detect)
        btns.addStretch(1)
        btns.addWidget(btn_save)
        layout.addLayout(btns)

        self.note = CaptionLabel("")
        layout.addWidget(self.note)
        layout.addStretch(1)

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

    def _save(self) -> None:
        s = self.settings
        s.language = self.lang.currentData()
        s.client_stable = self.p_client.text()
        s.client_exp = self.p_client_exp.text()
        s.server_stable = self.p_server.text()
        s.server_exp = self.p_server_exp.text()
        s.mikero_tools = self.p_mikero.text()
        s.dayz_tools = self.p_tools.text()
        s.workshop_dirs = [x.strip() for x in self.workshop.toPlainText().splitlines() if x.strip()]
        s.admin_steamids = [x.strip() for x in self.admin_ids.toPlainText().splitlines() if x.strip()]
        s.admin_password = self.admin_pass.text()
        s.pack_flags = self.pack_flags.text().strip() or "-P -K"
        s.clean_meta = self.clean_meta.isChecked()
        s.save()
        if self.on_saved:
            self.on_saved()
