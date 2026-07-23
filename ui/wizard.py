"""Мастер первого запуска: язык, пути (автопоиск), импорт старых батников."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QWizard, QWizardPage, QVBoxLayout, QFormLayout, QComboBox, QLabel,
    QLineEdit, QPushButton, QHBoxLayout, QFileDialog, QListWidget,
    QListWidgetItem, QCheckBox,
)
from PySide6.QtCore import Qt

from core import autodetect, i18n
from core.i18n import tr, AVAILABLE
from core.presets import import_bats_from_dir, ServerPreset
from core.settings import Settings


class FirstRunWizard(QWizard):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.imported: list[ServerPreset] = []
        self.setWindowTitle(tr("wizard.title", "KR Server Manager — первая настройка"))
        self.resize(720, 560)

        # --- Шаг 1: язык
        p1 = QWizardPage()
        p1.setTitle(tr("wizard.lang_title", "Язык / Language / Sprache"))
        l1 = QVBoxLayout(p1)
        self.lang = QComboBox()
        for code, label in AVAILABLE.items():
            self.lang.addItem(label, code)
        idx = list(AVAILABLE).index(settings.language) if settings.language in AVAILABLE else 0
        self.lang.setCurrentIndex(idx)
        l1.addWidget(self.lang)
        l1.addStretch(1)
        self.addPage(p1)

        # --- Шаг 2: пути (автопоиск уже выполнен)
        p2 = QWizardPage()
        p2.setTitle(tr("wizard.paths_title", "Пути"))
        p2.setSubTitle(tr("wizard.paths_sub",
                          "Пути найдены автоматически по реестру Steam. Проверьте и поправьте при необходимости."))
        l2 = QFormLayout(p2)
        det = autodetect.detect_all()
        self.paths: dict[str, QLineEdit] = {}

        def row(key: str, label: str, value: str):
            h = QHBoxLayout()
            edit = QLineEdit(value)
            btn = QPushButton("…")
            btn.setFixedWidth(30)
            btn.clicked.connect(lambda _=False, e=edit: self._browse(e))
            h.addWidget(edit, 1)
            h.addWidget(btn)
            l2.addRow(label, h)
            self.paths[key] = edit

        row("client_stable", tr("settings.client", "Папка игры (DayZ)"),
            settings.client_stable or det["client_stable"])
        row("client_exp", tr("settings.client_exp", "Папка игры Experimental"),
            settings.client_exp or det["client_exp"])
        row("server_stable", tr("settings.server", "Папка сервера (DayZServer)"),
            settings.server_stable or det["server_stable"])
        row("server_exp", tr("settings.server_exp", "Папка сервера Experimental"),
            settings.server_exp or det["server_exp"])
        row("mikero_tools", tr("settings.mikero", "Mikero Tools (DePboTools)"),
            settings.mikero_tools or det["mikero_tools"])
        row("dayz_tools", tr("settings.dayz_tools", "DayZ Tools"),
            settings.dayz_tools or det["dayz_tools"])
        self._workshop_dirs = settings.workshop_dirs or det["workshop_dirs"]
        ws_label = QLabel("\n".join(self._workshop_dirs) or
                          tr("wizard.no_workshop", "Workshop не найден (можно указать в настройках)"))
        ws_label.setStyleSheet("color:#888;")
        l2.addRow(tr("settings.workshop", "Папки Steam Workshop"), ws_label)
        self.addPage(p2)

        # --- Шаг 3: импорт батников
        p3 = QWizardPage()
        p3.setTitle(tr("wizard.import_title", "Импорт старых батников"))
        p3.setSubTitle(tr("wizard.import_sub",
                          "Приложение разбирает строки запуска в батниках и пробует создать из них пресеты. "
                          "Работает не со всеми батниками — проверьте, что распозналось, и снимите галки с ненужного."))
        l3 = QVBoxLayout(p3)
        h = QHBoxLayout()
        self.bat_dir = QLineEdit()
        btn_dir = QPushButton("…")
        btn_dir.setFixedWidth(30)
        btn_dir.clicked.connect(lambda: self._browse(self.bat_dir))
        btn_scan = QPushButton(tr("wizard.scan", "Найти батники"))
        btn_scan.clicked.connect(self._scan_bats)
        h.addWidget(self.bat_dir, 1)
        h.addWidget(btn_dir)
        h.addWidget(btn_scan)
        l3.addLayout(h)
        self.bat_list = QListWidget()
        l3.addWidget(self.bat_list, 1)
        self.addPage(p3)
        self._p3 = p3

        # --- Шаг 4: финиш
        p4 = QWizardPage()
        p4.setTitle(tr("wizard.done_title", "Готово"))
        l4 = QVBoxLayout(p4)
        l4.addWidget(QLabel(tr("wizard.done_text",
                               "Настройка завершена. Всё можно изменить позже в «Настройках».\n\n"
                               "Дальше: создайте или выберите пресет, подключите моды на вкладке «Моды»\n"
                               "и нажмите «Запустить».")))
        self.addPage(p4)

        self.currentIdChanged.connect(self._page_changed)

    def _browse(self, edit: QLineEdit) -> None:
        p = QFileDialog.getExistingDirectory(self, "", edit.text())
        if p:
            edit.setText(p)

    def _page_changed(self, _id: int) -> None:
        # На страницу импорта подставляем Debug-папку клиента
        if self.currentPage() is self._p3 and not self.bat_dir.text():
            client = self.paths["client_stable"].text()
            if client:
                debug = Path(client) / "Debug"
                self.bat_dir.setText(str(debug if debug.is_dir() else client))
                self._scan_bats()

    def _scan_bats(self) -> None:
        self.bat_list.clear()
        directory = Path(self.bat_dir.text())
        yes, no = tr("wizard.ok", "✓"), tr("wizard.miss", "—")

        def mark(flag: bool) -> str:
            return yes if flag else no

        for report in import_bats_from_dir(directory):
            preset = report.preset
            item = QListWidgetItem(tr(
                "wizard.bat_item",
                "{name}  [{mode}]  конфиг {cfg}  миссия {mis}  профиль {prof}  "
                "модов {n}+{ns}  клиент {cli}",
                name=preset.name, mode=preset.mode,
                cfg=mark(report.has_config), mis=mark(report.has_mission),
                prof=mark(report.has_profiles), n=report.n_mods,
                ns=report.n_server_mods, cli=mark(report.client_found)))
            if not (report.has_config and report.has_mission):
                item.setToolTip(tr("wizard.bat_partial",
                                   "Распозналось не всё — после импорта дозаполните пресет в редакторе."))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, preset)
            self.bat_list.addItem(item)

    def accept(self) -> None:
        s = self.settings
        s.language = self.lang.currentData()
        for key, edit in self.paths.items():
            setattr(s, key, edit.text().strip())
        s.workshop_dirs = self._workshop_dirs
        s.first_run_done = True
        s.save()
        i18n.load(s.language)

        for i in range(self.bat_list.count()):
            item = self.bat_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                preset: ServerPreset = item.data(Qt.ItemDataRole.UserRole)
                preset.save()
                self.imported.append(preset)
        super().accept()
