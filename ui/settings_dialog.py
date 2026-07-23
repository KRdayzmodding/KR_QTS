"""Диалог общих настроек приложения."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QPushButton,
    QComboBox, QPlainTextEdit, QCheckBox, QFileDialog, QDialogButtonBox, QLabel,
)

from core import autodetect
from core.i18n import tr, AVAILABLE
from core.settings import Settings


class PathRow(QHBoxLayout):
    def __init__(self, value: str, parent: QDialog, directory: bool = True):
        super().__init__()
        self.edit = QLineEdit(value)
        btn = QPushButton("…")
        btn.setFixedWidth(30)

        def browse():
            if directory:
                p = QFileDialog.getExistingDirectory(parent, "", self.edit.text())
            else:
                p, _ = QFileDialog.getOpenFileName(parent, "", self.edit.text())
            if p:
                self.edit.setText(p)

        btn.clicked.connect(browse)
        self.addWidget(self.edit, 1)
        self.addWidget(btn)

    def text(self) -> str:
        return self.edit.text().strip()


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("settings.title", "Общие настройки"))
        self.resize(680, 620)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.lang = QComboBox()
        for code, label in AVAILABLE.items():
            self.lang.addItem(label, code)
        self.lang.setCurrentIndex(max(0, list(AVAILABLE).index(settings.language)
                                      if settings.language in AVAILABLE else 0))
        form.addRow(tr("settings.language", "Язык (нужен перезапуск)"), self.lang)

        self.p_client = PathRow(settings.client_stable, self)
        self.p_client_exp = PathRow(settings.client_exp, self)
        self.p_server = PathRow(settings.server_stable, self)
        self.p_server_exp = PathRow(settings.server_exp, self)
        self.p_mikero = PathRow(settings.mikero_tools, self)
        self.p_tools = PathRow(settings.dayz_tools, self)
        form.addRow(tr("settings.client", "Папка игры (DayZ)"), self.p_client)
        form.addRow(tr("settings.client_exp", "Папка игры Experimental"), self.p_client_exp)
        form.addRow(tr("settings.server", "Папка сервера (DayZServer)"), self.p_server)
        form.addRow(tr("settings.server_exp", "Папка сервера Experimental"), self.p_server_exp)
        form.addRow(tr("settings.mikero", "Mikero Tools (DePboTools)"), self.p_mikero)
        form.addRow(tr("settings.dayz_tools", "DayZ Tools"), self.p_tools)

        self.workshop = QPlainTextEdit("\n".join(settings.workshop_dirs))
        self.workshop.setMaximumHeight(60)
        self.workshop.setToolTip(tr("settings.workshop_tip",
                                    "Папки steamapps/workshop/content/221100 — по одной на строку."))
        form.addRow(tr("settings.workshop", "Папки Steam Workshop"), self.workshop)

        self.admin_ids = QPlainTextEdit("\n".join(settings.admin_steamids))
        self.admin_ids.setMaximumHeight(60)
        self.admin_ids.setToolTip(tr("settings.admins_tip",
                                     "SteamID64 админов — по одному на строку. Используется модами-админками."))
        form.addRow(tr("settings.admins", "Админские SteamID"), self.admin_ids)

        self.admin_pass = QLineEdit(settings.admin_password)
        self.admin_pass.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(tr("settings.admin_pass", "Пароль модов-админок"), self.admin_pass)

        self.pack_flags = QLineEdit(settings.pack_flags)
        self.pack_flags.setToolTip(tr("settings.pack_flags_tip",
                                      "Дополнительные флаги pboProject (например -P -K)."))
        form.addRow(tr("settings.pack_flags", "Флаги запаковки"), self.pack_flags)

        self.clean_meta = QCheckBox(tr("settings.clean_meta",
                                       "Удалять *.meta в сорсах перед запаковкой"))
        self.clean_meta.setChecked(settings.clean_meta)
        form.addRow("", self.clean_meta)

        layout.addLayout(form)

        btn_detect = QPushButton(tr("settings.autodetect", "Автопоиск незаполненных путей"))
        btn_detect.clicked.connect(self._autodetect)
        layout.addWidget(btn_detect)
        self.note = QLabel("")
        self.note.setStyleSheet("color:#888;")
        layout.addWidget(self.note)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

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
        self.accept()
