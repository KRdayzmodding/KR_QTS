"""Мастер первого запуска: язык, пути (автопоиск), импорт старых батников."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QWizardPage, QVBoxLayout, QFormLayout, QHBoxLayout, QFileDialog,
    QListWidgetItem,
)
from PySide6.QtCore import Qt
from qfluentwidgets import (
    ComboBox, LineEdit, PlainTextEdit, PushButton, ToolButton,
    ListWidget, BodyLabel, CaptionLabel, FluentIcon as FIF,
)

from core import autodetect, i18n
from core.i18n import tr, AVAILABLE
from core.presets import import_bats_from_dir, ServerPreset
from core.settings import Settings, check_path
from core.steam_urls import SETTINGS_APPS
from ui.settings_page import make_install_button
from ui.steam_watch import SteamWatcher, status_text
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
            "Красная рамка означает, что путь указан, но по нему нет папки или в ней "
            "нет самой программы (например, игру удалили, а папка осталась, или в "
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

        self.path_status: dict[str, CaptionLabel] = {}

        def row(key: str, label: str, value: str):
            box = QVBoxLayout()
            box.setSpacing(2)
            h = QHBoxLayout()
            edit = LineEdit()
            edit.setText(value)
            # проверка та же, что в «Настройках»: для клиента и сервера мало
            # существования папки — нужен исполняемый файл
            edit.setError(bool(check_path(key, value)))
            edit.textChanged.connect(
                lambda t, e=edit, k=key: e.setError(bool(check_path(k, t.strip()))))
            btn = ToolButton(FIF.FOLDER)
            btn.clicked.connect(lambda _=False, e=edit: self._browse(e))
            h.addWidget(edit, 1)
            h.addWidget(btn)
            # не установлено — предлагаем взять недостающее, не уходя из мастера
            b_inst = make_install_button(self, key)
            if b_inst is not None:
                b_inst.setVisible(not value.strip())
                edit.textChanged.connect(lambda t, b=b_inst: b.setVisible(not t.strip()))
                h.addWidget(b_inst)
            box.addLayout(h)
            # состояние загрузки Steam: заполняется наблюдателем, пока пусто — скрыто
            st = CaptionLabel("")
            st.setWordWrap(True)
            st.hide()
            box.addWidget(st)
            l2.addRow(label, box)
            self.paths[key] = edit
            self.path_status[key] = st

        row("client_stable", tr("settings.client", "DayZ"),
            settings.client_stable or det["client_stable"])
        row("server_stable", tr("settings.server", "DayZ Server"),
            settings.server_stable or det["server_stable"])
        row("client_exp", tr("settings.client_exp", "DayZ Experimental"),
            settings.client_exp or det["client_exp"])
        row("server_exp", tr("settings.server_exp", "DayZ Server Experimental"),
            settings.server_exp or det["server_exp"])
        row("dayz_tools", tr("settings.dayz_tools", "DayZ Tools"),
            settings.dayz_tools or det["dayz_tools"])
        row("dayz_tools_exp", tr("settings.dayz_tools_exp", "DayZ Tools Experimental"),
            settings.dayz_tools_exp or det["dayz_tools_exp"])
        row("mikero_tools", tr("settings.mikero", "Mikero Tools (DePboTools)"),
            settings.mikero_tools or det["mikero_tools"])
        self._workshop_dirs = settings.workshop_dirs or det["workshop_dirs"]
        self.ws_label = CaptionLabel("\n".join(self._workshop_dirs) or
                                     tr("wizard.no_workshop", "Workshop не найден (можно указать в настройках)"))
        l2.addRow(tr("settings.workshop", "Steam Workshop"), self.ws_label)

        # повторный автопоиск: пригодится, если пользователь доустановил
        # что-то мимо наших кнопок, не закрывая мастер
        b_detect = PushButton(FIF.SEARCH, tr("wizard.redetect", "Найти пути автоматически"))
        b_detect.setToolTip(tr("wizard.redetect_tip",
                               "Перечитывает библиотеки Steam и заполняет пустые поля."))
        b_detect.clicked.connect(self._redetect)
        l2v.addWidget(b_detect)
        self.addPage(p2)

        # --- Шаг 3: Steam — SteamID админов
        #     API-ключ сюда намеренно не вынесен: он нигде не обязателен
        #     (везде есть безключевой путь) — его место в «Настройках».
        p_steam = QWizardPage()
        p_steam.setTitle(tr("wizard.steam_title", "Steam"))
        p_steam.setSubTitle(tr("wizard.steam_sub",
                               "Поле необязательное и легко заполняется позже в «Настройках» — "
                               "но про него проще не забыть сразу."))
        l_steam = QFormLayout(p_steam)
        self.admin_ids = PlainTextEdit()
        self.admin_ids.setPlainText("\n".join(settings.admin_steamids))
        self.admin_ids.setMaximumHeight(64)
        self.admin_ids.setPlaceholderText(tr("wizard.admin_ph", "SteamID64 — по одному на строку"))
        l_steam.addRow(tr("settings.admins", "Админские SteamID"), self.admin_ids)
        self.b_resolve = PushButton(FIF.SEARCH, tr("settings.admins_resolve",
                                                   "Добавить по ссылке на профиль…"))
        self.b_resolve.setToolTip(tr("settings.admins_resolve_tip",
                                     "Определяет SteamID64 по ссылке вида "
                                     "steamcommunity.com/id/<имя> или /profiles/<id>."))
        self.b_resolve.clicked.connect(self._resolve_steamid)
        l_steam.addRow("", self.b_resolve)
        admin_hint = CaptionLabel(tr("wizard.admin_hint",
                                     "Используется модами-админками (COT, VPPAdminTools, LBmaster) для выдачи "
                                     "прав. Проще всего — вставить ссылку на свой профиль Steam "
                                     "кнопкой выше, SteamID64 определится сам."))
        admin_hint.setWordWrap(True)
        l_steam.addRow("", admin_hint)
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

        # Кнопка установки отправляет пользователя в Steam, и дальше мастер
        # ничего бы о загрузке не знал — поэтому следим за ней сами и
        # подставляем путь, как только компонент установится.
        self.watcher = SteamWatcher(self)
        self.watcher.watch_apps(self.paths)
        self.watcher.app_changed.connect(self._steam_app_changed)
        self.watcher.app_installed.connect(self._steam_app_installed)
        self.watcher.start()

    # ------------------------------------------------------- загрузки Steam

    def _steam_app_changed(self, key: str, st) -> None:
        label = self.path_status.get(key)
        if label is None:
            return
        text = status_text(st)
        label.setText(text)
        label.setVisible(bool(text))

    def _steam_app_installed(self, key: str, path: str) -> None:
        from qfluentwidgets import InfoBar, InfoBarPosition
        edit = self.paths.get(key)
        label = self.path_status.get(key)
        if label is not None:
            label.setVisible(False)
        if edit is None or not path:
            return
        title = SETTINGS_APPS.get(key, ("", key))[1]
        if edit.text().strip():
            return          # путь уже задан — вероятно, вручную, не перетираем
        edit.setText(path)
        InfoBar.success(
            title=tr("steam.dl_done", "«{n}» установлен", n=title),
            content=tr("steam.dl_path_set_wizard", "Путь подставлен автоматически."),
            parent=self, duration=8000, position=InfoBarPosition.TOP_RIGHT)

    def _redetect(self) -> None:
        """Повторный автопоиск — заполняет только пустые поля."""
        from qfluentwidgets import InfoBar, InfoBarPosition
        det = autodetect.detect_all()
        filled = 0
        for key, edit in self.paths.items():
            if not edit.text().strip() and det.get(key):
                edit.setText(det[key])
                filled += 1
        if not self._workshop_dirs and det["workshop_dirs"]:
            self._workshop_dirs = det["workshop_dirs"]
            self.ws_label.setText("\n".join(self._workshop_dirs))
            filled += 1
        InfoBar.info(title=tr("settings.detected", "Заполнено полей: {n}", n=filled),
                     content="", parent=self, duration=4000,
                     position=InfoBarPosition.TOP_RIGHT)

    def _browse(self, edit: QLineEdit) -> None:
        p = QFileDialog.getExistingDirectory(self, "", edit.text())
        if p:
            edit.setText(p)

    def _resolve_steamid(self) -> None:
        """SteamID64 по ссылке на профиль — тот же механизм, что в «Настройках».
        Ключ на этом шаге ещё не введён (его тут и нет), поэтому резолв идёт
        публичными способами — им ключ не нужен."""
        from PySide6.QtWidgets import QInputDialog
        from ui.settings_page import _ResolveSteamIdWorker
        value, ok = QInputDialog.getText(
            self, tr("settings.admins_resolve", "Добавить по ссылке на профиль…"),
            tr("settings.admins_resolve_prompt",
               "Ссылка на профиль Steam (или ник из ссылки /id/):"))
        if not ok or not value.strip():
            return
        self.b_resolve.setEnabled(False)
        self._resolve_worker = _ResolveSteamIdWorker(value, self.settings.steam_api_key, self)
        self._resolve_worker.done.connect(self._steamid_resolved)
        self._resolve_worker.start()

    def _steamid_resolved(self, sid: str, source: str) -> None:
        from qfluentwidgets import InfoBar, InfoBarPosition
        self.b_resolve.setEnabled(True)
        if not sid:
            InfoBar.error(title=tr("settings.admins_resolve_failed",
                                   "Не удалось определить SteamID"),
                          content=source, parent=self, duration=6000,
                          position=InfoBarPosition.TOP_RIGHT)
            return
        lines = [x.strip() for x in self.admin_ids.toPlainText().splitlines() if x.strip()]
        if sid in lines:
            InfoBar.info(title=tr("settings.admins_resolve_dup", "{id} уже в списке", id=sid),
                         content="", parent=self, duration=4000,
                         position=InfoBarPosition.TOP_RIGHT)
            return
        lines.append(sid)
        self.admin_ids.setPlainText("\n".join(lines))
        InfoBar.success(title=tr("settings.admins_resolve_ok", "Добавлен {id}", id=sid),
                        content="", parent=self, duration=4000,
                        position=InfoBarPosition.TOP_RIGHT)

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
