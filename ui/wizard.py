"""Мастер первого запуска: язык, пути (автопоиск), импорт старых батников."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QWizardPage, QVBoxLayout, QFormLayout, QHBoxLayout, QFileDialog,
    QListWidgetItem,
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from qfluentwidgets import (
    ComboBox, LineEdit, PasswordLineEdit, PlainTextEdit, PushButton, ToolButton,
    ListWidget, BodyLabel, CaptionLabel, FluentIcon as FIF,
)

from core import autodetect, i18n
from core.i18n import tr, AVAILABLE
from core.presets import import_bats_from_dir, ServerPreset
from core.settings import Settings
from ui.theme import ThemedWizard


class FirstRunWizard(ThemedWizard):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.imported: list[ServerPreset] = []
        self.setWindowTitle(tr("wizard.title", "KR Server Manager — первая настройка"))
        self.resize(720, 560)

        # --- Шаг 1: язык + префикс проекта
        p1 = QWizardPage()
        p1.setTitle(tr("wizard.lang_title", "Язык / Language / Sprache"))
        l1 = QVBoxLayout(p1)
        self.lang = ComboBox()
        for code, label in AVAILABLE.items():
            self.lang.addItem(label, userData=code)
        idx = list(AVAILABLE).index(settings.language) if settings.language in AVAILABLE else 0
        self.lang.setCurrentIndex(idx)
        l1.addWidget(self.lang)

        l1.addWidget(BodyLabel(tr("wizard.prefix_label",
                                  "Название проекта / префикс мододела")))
        self.project_prefix = LineEdit()
        self.project_prefix.setText(settings.project_prefix)
        self.project_prefix.setPlaceholderText(tr("wizard.prefix_ph", "Например: KR"))
        l1.addWidget(self.project_prefix)
        prefix_hint = CaptionLabel(tr("wizard.prefix_hint",
                                     "Будет подставляться в hostname создаваемых серверов — "
                                     "не придётся вводить его вручную каждый раз. "
                                     "Изменить можно позже в настройках."))
        prefix_hint.setWordWrap(True)
        l1.addWidget(prefix_hint)
        p1.registerField("prefix*", self.project_prefix)

        l1.addStretch(1)
        self.addPage(p1)

        # --- Шаг 2: пути (автопоиск уже выполнен)
        p2 = QWizardPage()
        p2.setTitle(tr("wizard.paths_title", "Пути"))
        p2.setSubTitle(tr("wizard.paths_sub",
                          "Пути найдены автоматически по реестру Steam. Проверьте и поправьте при необходимости."))
        l2v = QVBoxLayout(p2)
        paths_help = CaptionLabel(tr("wizard.paths_help",
            "Ничего страшного, если что-то не найдено или не установлено — поле можно "
            "оставить пустым и заполнить позже в «Настройках», когда всё будет готово. "
            "Красная рамка означает, что путь указан, но папки по нему сейчас нет "
            "(например, игра установлена, но эту конкретную папку удалили, или в "
            "реестре остался след от старой установки). DayZ, Experimental-версия и "
            "выделенный сервер устанавливаются и обновляются через Steam (библиотека "
            "игр и вкладка «Инструменты» для DayZ Tools); Mikero Tools (DePboTools) — "
            "отдельная бесплатная утилита с сайта разработчика, ищется по названию."))
        paths_help.setWordWrap(True)
        l2v.addWidget(paths_help)
        l2 = QFormLayout()
        l2v.addLayout(l2)
        det = autodetect.detect_all()
        self.paths: dict[str, LineEdit] = {}

        def row(key: str, label: str, value: str):
            h = QHBoxLayout()
            edit = LineEdit()
            edit.setText(value)
            edit.setError(bool(value) and not Path(value).is_dir())
            edit.textChanged.connect(lambda t, e=edit: e.setError(bool(t) and not Path(t).is_dir()))
            btn = ToolButton(FIF.FOLDER)
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
        ws_label = CaptionLabel("\n".join(self._workshop_dirs) or
                                tr("wizard.no_workshop", "Workshop не найден (можно указать в настройках)"))
        l2.addRow(tr("settings.workshop", "Папки Steam Workshop"), ws_label)
        self.addPage(p2)

        # --- Шаг 3: Steam — SteamID админов и API-ключ
        p_steam = QWizardPage()
        p_steam.setTitle(tr("wizard.steam_title", "Steam"))
        p_steam.setSubTitle(tr("wizard.steam_sub",
                               "Оба поля необязательны и легко заполняются позже в «Настройках» — "
                               "но про них проще не забыть сразу."))
        l_steam = QFormLayout(p_steam)
        self.admin_ids = PlainTextEdit()
        self.admin_ids.setPlainText("\n".join(settings.admin_steamids))
        self.admin_ids.setMaximumHeight(64)
        self.admin_ids.setPlaceholderText(tr("wizard.admin_ph", "SteamID64 — по одному на строку"))
        l_steam.addRow(tr("settings.admins", "Админские SteamID"), self.admin_ids)
        admin_hint = CaptionLabel(tr("wizard.admin_hint",
                                     "Используется модами-админками для выдачи прав. Своё SteamID64 "
                                     "можно найти на steamid.io или в свойствах профиля Steam."))
        admin_hint.setWordWrap(True)
        l_steam.addRow("", admin_hint)

        steam_key_row = QHBoxLayout()
        self.steam_key = PasswordLineEdit()
        self.steam_key.setText(settings.steam_api_key)
        btn_get_key = PushButton(FIF.LINK, tr("settings.steam_key_get", "Получить"))
        btn_get_key.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl("https://steamcommunity.com/dev/apikey")))
        steam_key_row.addWidget(self.steam_key, 1)
        steam_key_row.addWidget(btn_get_key)
        l_steam.addRow(tr("settings.steam_key", "Steam API-ключ"), steam_key_row)
        key_hint = CaptionLabel(tr("settings.steam_key_hint",
            "Нужен для определения зависимостей стим-модов через официальный API. "
            "Как получить: нажмите «Получить», войдите в Steam, в поле «Domain Name» "
            "впишите что угодно (например, localhost), согласитесь с условиями и "
            "скопируйте ключ сюда. Без ключа зависимости читаются со страницы "
            "воркшопа — работает, но менее надёжно."))
        key_hint.setWordWrap(True)
        l_steam.addRow("", key_hint)
        self.addPage(p_steam)

        # --- Шаг 4: импорт батников
        p3 = QWizardPage()
        p3.setTitle(tr("wizard.import_title", "Импорт старых батников"))
        p3.setSubTitle(tr("wizard.import_sub",
                          "Приложение разбирает строки запуска в батниках и пробует создать из них пресеты. "
                          "Работает не со всеми батниками — проверьте, что распозналось, и снимите галки с ненужного."))
        l3 = QVBoxLayout(p3)
        h = QHBoxLayout()
        self.bat_dir = LineEdit()
        btn_dir = ToolButton(FIF.FOLDER)
        btn_dir.clicked.connect(lambda: self._browse(self.bat_dir))
        btn_scan = PushButton(FIF.SEARCH, tr("wizard.scan", "Найти батники"))
        btn_scan.clicked.connect(self._scan_bats)
        h.addWidget(self.bat_dir, 1)
        h.addWidget(btn_dir)
        h.addWidget(btn_scan)
        l3.addLayout(h)
        self.bat_list = ListWidget()
        l3.addWidget(self.bat_list, 1)
        h_sel = QHBoxLayout()
        btn_all = PushButton(tr("wizard.select_all", "Выбрать всё"))
        btn_all.clicked.connect(lambda: self._set_all_checked(True))
        btn_none = PushButton(tr("wizard.select_none", "Убрать всё"))
        btn_none.clicked.connect(lambda: self._set_all_checked(False))
        h_sel.addWidget(btn_all)
        h_sel.addWidget(btn_none)
        h_sel.addStretch(1)
        l3.addLayout(h_sel)
        self.addPage(p3)
        self._p3 = p3

        # --- Шаг 5: финиш
        p4 = QWizardPage()
        p4.setTitle(tr("common.done", "Готово"))
        l4 = QVBoxLayout(p4)
        l4.addWidget(BodyLabel(tr("wizard.done_text",
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

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.bat_list.count()):
            self.bat_list.item(i).setCheckState(state)

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
        s.project_prefix = self.project_prefix.text().strip()
        for key, edit in self.paths.items():
            setattr(s, key, edit.text().strip())
        s.workshop_dirs = self._workshop_dirs
        s.admin_steamids = [x.strip() for x in self.admin_ids.toPlainText().splitlines() if x.strip()]
        s.steam_api_key = self.steam_key.text().strip()
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
