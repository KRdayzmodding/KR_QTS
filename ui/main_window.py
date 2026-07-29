"""Главное окно (Fluent): боковая навигация — Запуск / Моды / Конфиг / Настройки."""
from __future__ import annotations

import html
from pathlib import Path

import psutil
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QApplication,
    QSystemTrayIcon,
)
from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, FluentIcon as FIF,
    ComboBox, CheckBox, PushButton, PrimaryPushButton, TransparentToolButton,
    BodyLabel, StrongBodyLabel, CardWidget, InfoBar, InfoBarPosition, MessageBox,
    SystemTrayMenu, Action,
)

from core import filepatch, logsource, packer, packlog
from core.i18n import tr
from core.launcher import LaunchWorker, dayz_running, kill_all, kill_pid
from core.mods import ModRegistry
from core.preflight import run_checks
from core.presets import ServerPreset, MODE_DIAG
from core.settings import (
    Settings, STABLE, EXPERIMENTAL, CLIENT_EXE, SERVER_EXE, PATH_NOT_INSTALLED,
    check_path, find_pbo_project_exe, is_install,
)
from core.steam_urls import SETTINGS_APPS
from ui.cfg_editor import CfgEditor
from ui.log_window import LogWindow
from ui.mods_panel import ModsPanel
from ui.preflight_dialog import PreflightDialog
from ui.preset_editor import AdvancedPresetDialog, LazyPresetWizard
from ui.settings_page import SettingsPage
from ui.steam_watch import SteamWatcher, status_text
from ui.mini_window import MiniWindow
from ui.packing_log import PackingLog
from ui.launch_status import LaunchStatus, LaunchMonitor, SERVER, CLIENT
from ui.packlog_window import PackLogWindow
from ui.theme import app_icon

_STATUS_COLORS = {"info": "#d4d4d4", "warning": "#e5c07b", "error": "#ff6b6b"}
_CONSOLE_QSS = ("QPlainTextEdit{background:#1e1e1e;color:#d4d4d4;"
                "border:1px solid #333;border-radius:6px;padding:4px;}")


class LaunchInterface(QWidget):
    """Страница «Запуск»: пресет, ветка, галки, кнопки, статус, журнал запуска."""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.setObjectName("launchInterface")
        self.win = win
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        # Пресет + ветка — прижаты влево, чтобы справа осталось место для
        # кнопки «Подключить моды» (см. ниже, addStretch перед ней)
        top = QHBoxLayout()
        top.addWidget(BodyLabel(tr("main.preset", "Пресет:")))
        self.preset_combo = ComboBox()
        self.preset_combo.setMinimumWidth(200)
        self.preset_combo.setMaximumWidth(260)
        top.addWidget(self.preset_combo)
        self.b_new = TransparentToolButton(FIF.ADD)
        self.b_new.setToolTip(tr("main.preset_new", "Создать"))
        self.b_edit = TransparentToolButton(FIF.EDIT)
        self.b_edit.setToolTip(tr("main.preset_edit", "Изменить"))
        self.b_del = TransparentToolButton(FIF.DELETE)
        self.b_del.setToolTip(tr("main.preset_del", "Удалить"))
        top.addWidget(self.b_new)
        top.addWidget(self.b_edit)
        top.addWidget(self.b_del)
        top.addSpacing(20)
        top.addWidget(BodyLabel(tr("main.branch", "Ветка:")))
        self.branch_combo = ComboBox()
        self.branch_combo.addItem("Stable", userData=STABLE)
        self.branch_combo.addItem("Experimental", userData=EXPERIMENTAL)
        top.addWidget(self.branch_combo)
        top.addStretch(1)
        self.b_connect_mods = PushButton(FIF.APPLICATION, tr("main.connect_mods", "Подключить моды"))
        top.addWidget(self.b_connect_mods)
        layout.addLayout(top)

        def framed(title: str) -> QVBoxLayout:
            """Обведённый рамкой блок с заголовком."""
            card = CardWidget()
            box = QVBoxLayout(card)
            box.setContentsMargins(16, 10, 16, 12)
            box.setSpacing(8)
            box.addWidget(StrongBodyLabel(title))
            layout.addWidget(card)
            return box

        # ------------------------------------------------------------ Сервер
        srv = framed(tr("main.frame_server", "Сервер"))
        row = QHBoxLayout()
        self.chk_server = CheckBox(tr("common.server", "Сервер"))
        self.chk_client = CheckBox(tr("common.client", "Клиент"))
        row.addWidget(self.chk_server)
        row.addWidget(self.chk_client)
        row.addStretch(1)
        self.status_label = StrongBodyLabel("")
        row.addWidget(self.status_label)
        srv.addLayout(row)

        row2 = QHBoxLayout()
        self.btn_launch = PrimaryPushButton(FIF.PLAY, tr("main.launch_btn", "Запустить"))
        self.btn_launch.setMinimumHeight(38)
        self.btn_logs = PushButton(FIF.DOCUMENT, tr("main.show_logs", "Показать логи"))
        self.btn_logs.setMinimumHeight(38)
        row2.addWidget(self.btn_launch, 2)
        row2.addWidget(self.btn_logs, 1)
        srv.addLayout(row2)

        # ---------------------------------------------------------- Запаковка
        pack = framed(tr("main.frame_pack", "Запаковка"))
        row_pack = QHBoxLayout()
        row_pack.addWidget(BodyLabel(tr("main.pack_engine",
                                        "Перепаковка изменённых модов перед запуском:")))
        # три состояния одним списком: выключено + два режима pboProject
        self.pack_engine = ComboBox()
        self.pack_engine.addItem(tr("main.repack_off", "Не перепаковывать"), userData="")
        self.pack_engine.addItem(tr("settings.engine_normal",
                                    "Обычная — переиспользует temp"), userData="normal")
        self.pack_engine.addItem(tr("settings.engine_full",
                                    "Полная (FullBuild) — чистит temp"), userData="full")
        row_pack.addWidget(self.pack_engine, 1)
        self.btn_pack_settings = TransparentToolButton(FIF.SETTING)
        self.btn_pack_settings.setToolTip(tr("main.pack_settings_tip",
                                             "Настройки pboProject — те же, что в «Настройках», "
                                             "но под рукой. Сохраняются сразу."))
        row_pack.addWidget(self.btn_pack_settings)
        pack.addLayout(row_pack)

        row3 = QHBoxLayout()
        self.btn_sources = PushButton(FIF.APPLICATION, tr("main.mods_with_sources",
                                                          "Моды с сорсами"))
        self.btn_sources.setMinimumHeight(38)
        self.btn_sources.setToolTip(tr("main.mods_with_sources_tip",
                                       "Локальные моды, у которых заданы папки сорсов — "
                                       "оттуда же их можно перепаковать."))
        self.btn_packlogs = PushButton(FIF.ZIP_FOLDER, tr("main.show_packlogs",
                                                          "Логи запаковки"))
        self.btn_packlogs.setMinimumHeight(38)
        self.btn_packlogs.setToolTip(tr("main.show_packlogs_tip",
                                        "Логи pboProject по последней запаковке: "
                                        "отдельно сборка pbo, отдельно бинаризация."))
        row3.addWidget(self.btn_sources, 1)
        row3.addWidget(self.btn_packlogs, 1)
        pack.addLayout(row3)

        # Журнал запуска
        self.launch_log = QPlainTextEdit()
        self.launch_log.setReadOnly(True)
        self.launch_log.setFont(QFont("Consolas", 9))
        self.launch_log.setStyleSheet(_CONSOLE_QSS)
        layout.addWidget(self.launch_log, 1)


class MainWindow(FluentWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.registry = ModRegistry(settings)
        self.registry.scan()
        self.presets: list[ServerPreset] = []
        self.current: ServerPreset | None = None
        self.worker: LaunchWorker | None = None
        self.server_pid: int | None = None
        self.client_pid: int | None = None
        self._alive: dict[str, bool] = {}      # для отметки об отключении в логе
        self._quitting = False                 # выход только через меню трея
        self._starting = False                 # идёт запуск: кнопка «Запускается»
        self.ignored_checks: set[str] = set()  # «игнорировать до перезапуска»

        self.setWindowTitle("KR Server Manager")
        # Иконка приложения уже задана в main.py, но заголовок FluentWindow
        # свой, не системный: он подхватывает картинку по сигналу
        # windowIconChanged, а при наследовании от QApplication тот не приходит
        # — без явной установки в шапке остаётся пустое место.
        self.setWindowIcon(app_icon())
        self.resize(1060, 720)

        self.log_server = LogWindow(tr("main.server_log", "Логи сервера"),
                                    accent="#2e7d32", banner_text="SERVER")
        self.log_client = LogWindow(tr("main.client_log", "Логи клиента"),
                                    accent="#1565c0", banner_text="CLIENT")
        for win in (self.log_server, self.log_client):
            win.set_on_top(settings.logs_on_top)
            win.on_top_changed = self._logs_on_top_changed

        # Страницы
        self.launch_page = LaunchInterface(self)
        self.mods_panel = ModsPanel()
        self.mods_panel.setObjectName("modsInterface")
        self.mods_panel.log_cb = self._append_log
        self.pack_table = PackingLog(self.launch_page.launch_log)
        self.launch_status = LaunchStatus(self.launch_page.launch_log)
        # у сервера и клиента свои RPT в разных папках — свой наблюдатель на каждого
        self.monitors = {side: LaunchMonitor(side, self) for side in (SERVER, CLIENT)}
        for mon in self.monitors.values():
            mon.usage.connect(self.launch_status.set_usage)
            mon.crashed.connect(self._on_crash)
            mon.danger.connect(self._on_memory_danger)
            mon.limit.connect(self._on_memory_limit)
        # «игрок вошёл» видно только в RPT сервера — клиент об этом молчит
        self.monitors[SERVER].player_joined.connect(self._on_player_joined)
        # какие pbo паковались в последний раз — только их логи и показываем
        self._packed: list[str] = []
        self.packlog_windows = {k: PackLogWindow(k) for k in packlog.KINDS}
        self.mods_panel.pack_table = self.pack_table
        self.mods_panel.packed_cb = self.remember_packed
        self.cfg_editor = CfgEditor()
        self.cfg_editor.setObjectName("cfgInterface")
        self.settings_page = SettingsPage(settings, on_saved=self._settings_saved)
        self.settings_page.setObjectName("settingsInterface")

        self.addSubInterface(self.launch_page, FIF.PLAY, tr("main.tab_launch", "Запуск"))
        self.addSubInterface(self.mods_panel, FIF.APPLICATION, tr("main.tab_mods", "Моды"))
        self.addSubInterface(self.cfg_editor, FIF.DOCUMENT, tr("main.tab_cfg", "Конфиг сервера"))
        self.addSubInterface(self.settings_page, FIF.SETTING,
                             tr("menu.settings_nav", "Настройки"),
                             position=NavigationItemPosition.BOTTOM)
        self.navigationInterface.addItem(
            routeKey="about", icon=FIF.INFO, text=tr("menu.about", "О программе"),
            onClick=self._about, selectable=False,
            position=NavigationItemPosition.BOTTOM)

        # Сигналы страницы запуска
        lp = self.launch_page
        lp.preset_combo.currentIndexChanged.connect(self._preset_changed)
        lp.branch_combo.currentIndexChanged.connect(self._branch_changed)
        lp.b_new.clicked.connect(self._new_preset)
        lp.b_edit.clicked.connect(self._edit_preset)
        lp.b_del.clicked.connect(self._delete_preset)
        lp.b_connect_mods.clicked.connect(self._open_connect_mods)
        lp.chk_server.toggled.connect(self._launch_flags_changed)
        lp.chk_server.toggled.connect(lambda _v: self._update_launch_button())
        lp.chk_client.toggled.connect(lambda _v: self._update_launch_button())
        lp.chk_client.toggled.connect(self._launch_flags_changed)
        lp.btn_launch.clicked.connect(self.launch_button_clicked)
        lp.btn_logs.clicked.connect(self._show_logs)
        lp.btn_packlogs.clicked.connect(self._show_pack_logs)
        lp.btn_sources.clicked.connect(self._open_sources)
        lp.btn_pack_settings.clicked.connect(self._open_pack_settings)

        current_engine = settings.pack_engine if settings.repack_before_launch else ""
        idx = lp.pack_engine.findData(current_engine)
        lp.pack_engine.setCurrentIndex(idx if idx >= 0 else 0)
        lp.pack_engine.currentIndexChanged.connect(self._pack_engine_changed)
        self._update_branch_availability()

        self._reload_presets()

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(1000)
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start()

        # Загрузки Steam отслеживает главное окно, а не страница настроек:
        # компонентов можно поставить на скачивание сразу несколько и уйти
        # изучать приложение — уведомление и запись пути должны прийти в любом
        # случае, независимо от того, какая страница сейчас открыта.
        self.steam_watcher = SteamWatcher(self)
        self.steam_watcher.watch_apps(SETTINGS_APPS)
        self.steam_watcher.app_changed.connect(self._steam_app_changed)
        self.steam_watcher.app_installed.connect(self._steam_app_installed)
        self.steam_watcher.start()

        self._setup_tray()

    # ----------------------------------------------------- загрузки Steam

    def _steam_app_changed(self, key: str, st) -> None:
        self.settings_page.set_path_status(key, status_text(st))
        self._drop_if_removed(key, st)

    def _drop_if_removed(self, key: str, st) -> None:
        """Компонент удалили — стираем путь, он больше ни на что не годится.

        Стираем только когда папка доступна, а программы в ней нет: это факт, а
        не подозрение. Случай «папки нет вовсе» так не обрабатывается — точно так
        же выглядит отключённый внешний или сетевой диск, и терять настройку
        из-за этого нельзя (там остаётся предупреждение в поле).
        """
        value = getattr(self.settings, key, "")
        if not value or check_path(key, value) != PATH_NOT_INSTALLED:
            return
        if st is not None and st.downloading:
            return      # идёт установка или обновление — exe вот-вот появится

        # Сначала снимаем свои симлинки: пока путь записан, папка видна
        # filepatch как «остаток установки». После очистки настройки добраться
        # до неё будет уже нечем, и ссылки остались бы там навсегда.
        filepatch.sync(self.settings)

        setattr(self.settings, key, "")
        self.settings.save()
        self.settings_page.set_path_value(key, "", force=True)
        self._update_branch_availability()
        title = SETTINGS_APPS.get(key, ("", key))[1]
        self._notify("warning", tr("steam.removed", "«{n}» удалён", n=title),
                     tr("steam.removed_body",
                        "Путь очищен — программы по нему больше нет."),
                     duration=10000)

    def _steam_app_installed(self, key: str, path: str) -> None:
        """Компонент докачался: подставляем путь и сразу сохраняем настройки.

        Сохраняем сами, чтобы пользователю не приходилось возвращаться в
        настройки и жать «Сохранить» — он мог уйти оттуда сразу после запуска
        скачивания. Уже заданный путь не трогаем: он мог быть указан вручную.
        """
        if not path:
            return
        self.settings_page.set_path_status(key, "")
        title = SETTINGS_APPS.get(key, ("", key))[1]

        if getattr(self.settings, key, ""):
            self._notify("info", tr("steam.dl_done", "«{n}» установлен", n=title))
            return

        setattr(self.settings, key, path)
        self.settings.save()
        # поле на странице настроек тоже обновляем — иначе следующее нажатие
        # «Сохранить» затёрло бы записанный путь пустым полем
        self.settings_page.set_path_value(key, path)
        self._update_branch_availability()
        # держим дольше обычного: пользователь в этот момент занят другим
        self._notify("success", tr("steam.dl_done", "«{n}» установлен", n=title),
                     tr("steam.dl_path_saved", "Путь найден и сохранён автоматически."),
                     duration=10000)

    # ------------------------------------------------------------------ пресеты

    def _reload_presets(self, select: str | None = None) -> None:
        combo = self.launch_page.preset_combo
        self.registry.scan()  # редакторы могли докачать моды карт (mods_dl)
        combo.blockSignals(True)
        combo.clear()
        self.presets = ServerPreset.load_all()
        from core.presets import MODE_DIAG
        for p in self.presets:
            tags = ""
            if p.branch == EXPERIMENTAL:
                tags += "[Exp]"
            if p.mode == MODE_DIAG:
                tags += "[Diag]"
            label = (tags + " " if tags else "") + p.name
            if p.world:
                label += f" ({p.world.capitalize()})"
            combo.addItem(label)
        combo.blockSignals(False)
        if not self.presets:
            self.current = None
            self._bind_preset()
            return
        idx = 0
        if select:
            for i, p in enumerate(self.presets):
                if p.file_stem() == select:
                    idx = i
                    break
        combo.setCurrentIndex(idx)
        self._preset_changed(idx)

    def _preset_changed(self, idx: int) -> None:
        self.current = self.presets[idx] if 0 <= idx < len(self.presets) else None
        self._bind_preset()

    def _bind_preset(self) -> None:
        p = self.current
        lp = self.launch_page
        lp.b_edit.setEnabled(p is not None)
        lp.b_del.setEnabled(p is not None)
        lp.b_connect_mods.setEnabled(p is not None)
        for chk, val in ((lp.chk_server, p.launch_server if p else True),
                         (lp.chk_client, p.launch_client if p else True)):
            chk.blockSignals(True)
            chk.setChecked(val)
            chk.blockSignals(False)
        if p:
            lp.branch_combo.blockSignals(True)
            lp.branch_combo.setCurrentIndex(0 if p.branch == STABLE else 1)
            lp.branch_combo.blockSignals(False)
        self.mods_panel.set_context(self.registry, self.settings)
        self._bind_cfg()
        self._bind_log_dirs()

    def _bind_cfg(self) -> None:
        p = self.current
        if p and p.server_config:
            from core.layout import resolve_config
            path = resolve_config(p.server_config, self.settings, self._branch(), p.mode)
            self.cfg_editor.set_path(Path(path))
        else:
            self.cfg_editor.set_path(None)

    def _logs_on_top_changed(self, on: bool) -> None:
        """Галка в одном окне логов ставит поверх и второе — состояние общее."""
        self.settings.logs_on_top = on
        self.settings.save()
        for win in (self.log_server, self.log_client):
            win.set_on_top(on)

    def _bind_log_dirs(self) -> None:
        p = self.current
        branch = self._branch()
        self.log_server.set_directory(
            logsource.server_log_dir(p, self.settings, branch) if p else None)
        self.log_client.set_directory(logsource.client_log_dir(branch))

    def _branch(self) -> str:
        return self.launch_page.branch_combo.currentData() or STABLE

    def _branch_changed(self, _idx: int) -> None:
        if self.current:
            self.current.branch = self._branch()
            self.current.save()
        self._bind_cfg()
        self._bind_log_dirs()

    def _launch_flags_changed(self) -> None:
        if self.current:
            self.current.launch_server = self.launch_page.chk_server.isChecked()
            self.current.launch_client = self.launch_page.chk_client.isChecked()
            self.current.save()

    def _pack_engine_changed(self, _idx: int) -> None:
        """Пустой userData — «не перепаковывать»; движок при этом не сбрасываем:
        он всё ещё нужен кнопке «Ребилд» на вкладке модов."""
        engine = self.launch_page.pack_engine.currentData()
        self.settings.repack_before_launch = bool(engine)
        if engine:
            self.settings.pack_engine = engine
        self.settings.save()

    def _new_preset(self) -> None:
        wiz = LazyPresetWizard(self.settings, self)
        if wiz.exec() and wiz.result_preset:
            self._reload_presets(select=wiz.result_preset.file_stem())

    def _edit_preset(self) -> None:
        if not self.current:
            return
        dlg = AdvancedPresetDialog(self.current, self.settings, self)
        if dlg.exec():
            self._reload_presets(select=self.current.file_stem())

    def _open_connect_mods(self) -> None:
        if not self.current:
            return
        from ui.connect_mods_dialog import ConnectModsDialog
        dlg = ConnectModsDialog(self.registry, self.current, self.settings, self)
        dlg.exec()

    def _delete_preset(self) -> None:
        p = self.current
        if not p:
            return
        from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout
        from qfluentwidgets import BodyLabel
        from ui.theme import ThemedDialog

        dlg = ThemedDialog(self)
        dlg.setWindowTitle(tr("main.del_title", "Удаление пресета"))
        dlg.resize(460, 170)
        lay = QVBoxLayout(dlg)
        text = BodyLabel(tr("main.del_confirm", "Удалить пресет «{n}»?", n=p.name))
        text.setWordWrap(True)
        lay.addWidget(text)
        chk = CheckBox(tr("main.del_files",
                          "Удалить также файлы пресета: конфиг, профиль и миссию "
                          "(вместе со storage)"))
        chk.setChecked(True)
        lay.addWidget(chk)
        lay.addStretch(1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        b_cancel = PushButton(tr("common.cancel", "Отмена"))
        b_cancel.clicked.connect(dlg.reject)
        b_ok = PrimaryPushButton(FIF.DELETE, tr("main.preset_del", "Удалить"))
        b_ok.clicked.connect(dlg.accept)
        btns.addWidget(b_cancel)
        btns.addWidget(b_ok)
        lay.addLayout(btns)
        if not dlg.exec():
            return

        if chk.isChecked():
            from core.layout import delete_preset_files
            removed = delete_preset_files(self.settings, self._branch(), p.mode,
                                          p.server_config, p.profiles, p.mission)
            for r in removed:
                self._append_log(tr("main.del_removed", "Удалено: {p}", p=r))
        p.delete()
        self._reload_presets()

    # ------------------------------------------------------------------ запуск

    def _append_log(self, msg: str, level: str = "info") -> None:
        color = _STATUS_COLORS.get(level, "#d4d4d4")
        self.launch_page.launch_log.appendHtml(
            f'<span style="color:{color};">{html.escape(msg)}</span>')

    def _append_alarm(self, msg: str) -> None:
        """Крупная красная строка в журнале — для того, что нельзя проглядеть.

        Обычные сообщения об ошибках идут тем же кеглем, что и всё остальное, и
        в потоке запуска теряются; здесь случай, когда сервер вот-вот перестанет
        стартовать вообще.
        """
        self.launch_page.launch_log.appendHtml(
            '<div style="color:#ff3b30;font-size:15pt;font-weight:800;">'
            f'{html.escape(msg)}</div>')

    def _side_name(self, side: str) -> str:
        return (tr("common.server", "Сервер") if side == SERVER
                else tr("common.client", "Клиент"))

    def _on_crash(self, side: str, report) -> None:
        """Запуск сорвался — движок написал crash-лог.

        Это единственное место, где сказано, из-за чего именно: файл и строка.
        Поэтому и в журнал крупно, и отдельным окном — пропустить это нельзя,
        сервер попросту не поднимется.
        """
        self.launch_status.set_crash(side, report)
        self._append_alarm(tr("status.crash_log", "{s}: запуск сорван — {r}",
                              s=self._side_name(side), r=report.summary()))
        where = report.file and tr("status.crash_where", "Файл: {f}, строка {n}",
                                   f=report.file, n=report.line) or ""
        box = MessageBox(
            tr("status.crash_title", "Запуск сорван: {s}", s=self._side_name(side)),
            "\n\n".join(x for x in (
                report.headline,
                where,
                report.message,
                tr("status.crash_hint", "Подробности — в {p}", p=report.path.name),
            ) if x),
            self)
        box.yesButton.setText(tr("common.ok", "Понятно"))
        box.cancelButton.hide()
        box.exec()

    def _on_memory_danger(self, side: str, usage) -> None:
        self._append_alarm(tr(
            "status.mem_danger",
            "ВНИМАНИЕ ({s}): скрипты слоя {l} почти достигли лимита памяти ({p}%). "
            "Если лимит будет превышен, запуск не состоится.",
            s=self._side_name(side), l=usage.layer, p=f"{usage.percent:.1f}"))
        self._notify("warning", tr("status.mem_danger_title",
                                   "{s}, слой {l}: {p}% скриптовой памяти",
                                   s=self._side_name(side), l=usage.layer,
                                   p=f"{usage.percent:.1f}"),
                     duration=10000)

    def _on_memory_limit(self, side: str, usage) -> None:
        self._append_alarm(tr(
            "status.mem_limit",
            "ЛИМИТ ({s}): слой {l} исчерпал скриптовую память ({u} из {t} кБ). "
            "Запуск не состоится.",
            s=self._side_name(side), l=usage.layer, u=usage.used_kb, t=usage.total_kb))
        box = MessageBox(
            tr("status.mem_limit_title", "Достигнут лимит скриптовой памяти"),
            tr("status.mem_limit_body",
               "{s}: слой {l} достиг лимита скриптовой памяти — занято {u} из {t} кБ.\n\n"
               "С таким набором модов запуск не состоится — нужно скорректировать "
               "список подключённых модов.",
               s=self._side_name(side), l=usage.layer,
               u=usage.used_kb, t=usage.total_kb),
            self)
        box.yesButton.setText(tr("common.ok", "Понятно"))
        box.cancelButton.hide()
        box.exec()

    def _notify(self, kind: str, title: str, text: str = "", duration: int = 4000) -> None:
        fn = {"success": InfoBar.success, "warning": InfoBar.warning,
              "error": InfoBar.error}.get(kind, InfoBar.info)
        fn(title=title, content=text, parent=self, duration=duration,
           position=InfoBarPosition.TOP_RIGHT)

    def _launch(self) -> None:
        p = self.current
        if not p:
            self._notify("warning", tr("main.no_preset", "Сначала создайте пресет."))
            return
        if not p.launch_server and not p.launch_client:
            self._notify("warning", tr("main.nothing",
                                       "Отметьте, что запускать: сервер и/или клиент."))
            return
        if self.worker and self.worker.isRunning():
            return

        branch = self._branch()
        problems = [pr for pr in run_checks(p, self.settings, branch, self.registry)
                    if pr.check_id not in self.ignored_checks]
        if problems:
            dlg = PreflightDialog(problems, self)
            if not dlg.exec():
                return
            self.ignored_checks |= dlg.ignore_ids

        # Автоисправление кодировки конфига перед запуском
        from core.layout import resolve_config, resolve_profiles
        cfg_path = resolve_config(p.server_config, self.settings, branch, p.mode)
        if cfg_path and Path(cfg_path).is_file():
            from core.servercfg import ServerCfg, needs_reencode
            if needs_reencode(Path(cfg_path)):
                try:
                    ServerCfg(Path(cfg_path)).save()
                    self._append_log(tr("main.cfg_fixed",
                                        "Кодировка конфига исправлена на UTF-8 без BOM."), "warning")
                except OSError as e:
                    self._append_log(str(e), "error")

        # Профиль создаём заранее, чтобы тейлер логов сразу видел папку
        prof = resolve_profiles(p.profiles, self.settings, branch, p.mode)
        if prof:
            Path(prof).mkdir(parents=True, exist_ok=True)

        self._starting = True
        self._update_launch_button()
        self._append_log(tr("main.launching", "— Запуск «{n}» ({b}) —", n=p.name, b=branch))
        self._log_launch_summary(p, cfg_path)
        self.launch_status.start(
            self._server_name(p, cfg_path) if p.launch_server else "",
            self._client_name(p) if p.launch_client else "")
        # RPT читаем с самого начала: строки про память слоёв движок пишет в
        # первые секунды, до того как порт будет занят
        if p.launch_server:
            self.monitors[SERVER].start(Path(prof) if prof else None)
        if p.launch_client:
            # клиенту -profiles не передаётся, его RPT всегда в %LOCALAPPDATA%
            self.monitors[CLIENT].start(logsource.client_log_dir(branch))
        self.worker = LaunchWorker(p, self.settings, branch, self.registry)
        self.worker.log.connect(self._append_log)
        self.worker.pack_plan.connect(self.pack_table.start)
        self.worker.pack_plan.connect(self.remember_packed)
        self.worker.pack_status.connect(self.pack_table.set_status)
        self.worker.server_started.connect(self._on_server_started)
        self.worker.server_ready.connect(self._on_server_ready)
        self.worker.client_started.connect(self._on_client_started)
        self.worker.finished_ok.connect(lambda: self._launch_done(None))
        self.worker.failed.connect(self._launch_done)
        self.worker.start()

    def _server_name(self, preset: ServerPreset, cfg_path: str | None) -> str:
        """Название сервера так, как его увидят игроки.

        Берём hostname из cfg — пользователь мог поправить его руками; если
        конфига ещё нет или строки в нём нет, собираем по тому же правилу,
        по которому конфиг создавался.
        """
        if cfg_path and Path(cfg_path).is_file():
            try:
                from core.servercfg import ServerCfg
                cfg = ServerCfg(Path(cfg_path))
                var = next((v for v in cfg.variables() if v.name == "hostname"), None)
                if var and var.value.strip():
                    return var.value.strip().strip('"')
            except OSError:
                pass
        from core.layout import server_display_name
        return server_display_name(self.settings.project_prefix, preset.name)

    def _client_name(self, preset: ServerPreset) -> str:
        """Чем именно запускается клиент — обычный или диагностический.

        Имени сервера у клиента нет, а различать эти два случая нужно: под diag
        доступен filepatching и свои логи, под обычным — нет.
        """
        use_diag = preset.mode == MODE_DIAG or preset.client_use_diag
        return "DayZDiag_x64" if use_diag else "DayZ_x64"

    def _log_launch_summary(self, preset: ServerPreset, cfg_path: str | None) -> None:
        """Состав модов — то, что чаще всего нужно сверить глазами перед тем,
        как лезть в логи сервера. Название сервера здесь не пишем: оно живёт в
        блоке статуса, который обновляется по ходу запуска."""

        def names(keys: list[str]) -> list[str]:
            out = []
            for key in keys:
                mod = self.registry.mods.get(key.lower()) if self.registry else None
                out.append(mod.name if mod else key)
            return out

        client_mods, server_mods = names(preset.mods), names(preset.server_mods)
        if not client_mods and not server_mods:
            self._append_log(tr("main.log_no_mods", "Моды: не подключены"))
            return
        if client_mods:
            self._append_log(tr("main.log_mods", "Моды ({n}): {list}",
                                n=len(client_mods), list=", ".join(client_mods)))
        if server_mods:
            self._append_log(tr("main.log_server_mods", "Серверные моды ({n}): {list}",
                                n=len(server_mods), list=", ".join(server_mods)))

    def _on_server_ready(self) -> None:
        """Сервер занял порт — с этого момента кнопка предлагает остановку,
        не дожидаясь конца всей процедуры запуска (дальше ещё клиент)."""
        self._starting = False
        self.launch_status.set_running(SERVER)
        self._update_launch_button()

    def _on_server_started(self, pid: int) -> None:
        self.server_pid = pid
        self._append_log(tr("main.log_server_up", "Статус: сервер запущен (PID {p})", p=pid))
        self._bind_log_dirs()

    def _on_client_started(self, pid: int) -> None:
        self.client_pid = pid
        # Запущенным клиент считается не по факту старта процесса, а когда игрок
        # вошёл в мир. Исключение — сервер запускаем не мы: тогда RPT, где это
        # видно, нам недоступен, и лучше показать процесс, чем вечное «подключается».
        if self.current and self.current.launch_server:
            self.launch_status.set_connecting(CLIENT)
        else:
            self.launch_status.set_running(CLIENT)
        self._append_log(tr("main.log_client_up", "Статус: клиент запущен (PID {p})", p=pid))

    def _on_player_joined(self, _side: str) -> None:
        self.launch_status.set_running(CLIENT)

    def _launch_done(self, error: str | None) -> None:
        self._starting = False
        self._update_launch_button()
        if error:
            self._append_log(error, "error")
            self._notify("error", tr("main.launch_failed", "Запуск не удался"), error)
        else:
            self._append_log(tr("main.launch_ok", "Запуск завершён."))
            self._notify("success", tr("main.launch_ok", "Запуск завершён."))

    def remember_packed(self, names: list[str]) -> None:
        """Запоминает состав последней запаковки (имена без .pbo — так же
        называются и файлы логов pboProject)."""
        self._packed = [Path(n).stem for n in names]

    def _open_pack_settings(self) -> None:
        """Настройки pboProject прямо с главной страницы.

        Сохраняем сразу: окно вызывается ради быстрой правки перед сборкой, и
        требовать после этого идти в «Настройки» и жать «Сохранить» — ровно та
        ловушка, из-за которой правки уже терялись.
        """
        from ui.pboproject_dialog import PboProjectDialog
        dlg = PboProjectDialog(self.settings.pack_flags, self.settings.clean_meta, self)
        if not dlg.exec():
            return
        self.settings.pack_flags = dlg.result_flags() or Settings().pack_flags
        self.settings.clean_meta = dlg.result_clean_meta()
        self.settings.save()
        # страница настроек держит свою копию — иначе её «Сохранить» вернёт старое
        self.settings_page.reload_pack_flags()
        self._notify("success", tr("main.pack_settings_saved",
                                   "Настройки запаковки сохранены."))

    def _open_sources(self) -> None:
        """Список локальных модов с сорсами; отмеченные пересобираются."""
        from ui.sources_dialog import SourcesDialog, PackWorker
        if dayz_running():
            self._notify("warning", tr("mods.rebuild_busy",
                                       "Нельзя пересобрать при запущенной игре"),
                         tr("mods.rebuild_busy_body",
                            "Остановите сервер и клиент: они держат PBO открытыми."))
            return
        dlg = SourcesDialog(self.registry, self.settings, self)
        if not dlg.exec() or not dlg.selected_jobs:
            return
        names = [packer.pbo_for_source(m, s).name for m, s in dlg.selected_jobs]
        self.pack_table.start(names)
        self.remember_packed(names)
        self._pack_worker = PackWorker(self.settings, dlg.selected_jobs, self)
        self._pack_worker.source_start.connect(
            lambda n: self.pack_table.set_status(n, "packing"))
        self._pack_worker.source_done.connect(
            lambda n, ok, ms, w, e: self.pack_table.set_status(
                n, "ok" if ok else "fail", ms, w, e))
        self._pack_worker.finished_all.connect(self._packing_done)
        self._pack_worker.start()

    def _packing_done(self, done: int, failed: int) -> None:
        if failed:
            self._notify("error", tr("sources.done_failed",
                                     "Перепаковка: собрано {d}, с ошибками {f}",
                                     d=done, f=failed))
        else:
            self._notify("success", tr("sources.done_ok",
                                       "Перепаковано PBO: {d}", d=done))

    def _show_pack_logs(self) -> None:
        for i, (kind, win) in enumerate(self.packlog_windows.items()):
            win.set_names(self._packed)
            win.show()
            win.raise_()
            # разносим, чтобы второе окно не легло ровно на первое
            win.move(self.x() + 60 + i * 40, self.y() + 60 + i * 40)

    def _show_logs(self) -> None:
        self._bind_log_dirs()
        self._position_log_windows()
        self.log_server.show()
        self.log_client.show()
        self.log_server.raise_()
        self.log_client.raise_()

    def _position_log_windows(self) -> None:
        """Ставит окна логов рядом друг с другом, не перекрывая — но только
        при первом показе каждого (уже видимое окно пользователь мог сам
        передвинуть, сбрасывать его позицию не нужно)."""
        screen = QApplication.primaryScreen().availableGeometry()
        w, h = self.log_server.width(), self.log_server.height()
        margin = 24
        side_by_side = screen.width() >= w * 2 + margin * 3
        if not self.log_server.isVisible():
            self.log_server.move(screen.left() + margin, screen.top() + margin)
        if not self.log_client.isVisible():
            if side_by_side:
                self.log_client.move(screen.left() + margin * 2 + w, screen.top() + margin)
            else:
                self.log_client.move(screen.left() + margin, screen.top() + margin * 2 + h)

    # состояния процесса — общие для текстового статуса и кружков мини-окна
    ST_RUN, ST_DEAD, ST_OFF = "run", "dead", "off"
    STATE_COLORS = {ST_RUN: "#4caf50", ST_DEAD: "#ff6b6b", ST_OFF: "#777777"}

    @staticmethod
    def process_state(pid: int | None) -> str:
        """run — процесс жив; dead — запускали, но он завершился; off — не запускали."""
        if pid and psutil.pid_exists(pid):
            return MainWindow.ST_RUN
        return MainWindow.ST_DEAD if pid else MainWindow.ST_OFF

    def server_running(self) -> bool:
        return self.process_state(self.server_pid) == self.ST_RUN

    def client_running(self) -> bool:
        return self.process_state(self.client_pid) == self.ST_RUN

    # ------------------------------------------------ состояние кнопки запуска

    LB_LAUNCH, LB_STARTING, LB_STOP = "launch", "starting", "stop"

    def launch_subject(self) -> str | None:
        """Кем «управляет» кнопка: сервером или клиентом.

        Приоритет у сервера — он поднимается первым и дольше. Если галка
        сервера снята, кнопка начинает относиться к клиенту: при живом сервере
        это позволяет перезапускать один клиент, не трогая сервер.
        """
        lp = self.launch_page
        if lp.chk_server.isChecked():
            return "server"
        if lp.chk_client.isChecked():
            return "client"
        return None

    def launch_state(self) -> str:
        subject = self.launch_subject()
        if self._starting:
            return self.LB_STARTING
        running = self.server_running() if subject == "server" else self.client_running()
        return self.LB_STOP if subject and running else self.LB_LAUNCH

    def _update_launch_button(self) -> None:
        state = self.launch_state()
        text, icon = {
            self.LB_LAUNCH: (tr("main.launch_btn", "Запустить"), FIF.PLAY),
            self.LB_STARTING: (tr("main.starting_btn", "Запускается"), FIF.SYNC),
            self.LB_STOP: (tr("main.stop_btn", "Остановить"), FIF.POWER_BUTTON),
        }[state]
        lp = self.launch_page
        lp.btn_launch.setText(text)
        lp.btn_launch.setIcon(icon)
        lp.btn_launch.setEnabled(state != self.LB_STARTING)
        # Пока идёт запуск, галки заблокированы: они определяют, чем управляет
        # кнопка, и смена на полпути рассогласовала бы её с тем, что реально
        # стартует в этот момент.
        busy = state == self.LB_STARTING
        lp.chk_server.setEnabled(not busy)
        lp.chk_client.setEnabled(not busy)
        self._update_running_locks(busy)
        if getattr(self, "mini", None) and not self.mini.isHidden():
            self.mini.refresh_status()

    def busy_with_processes(self) -> bool:
        """Идёт запуск или что-то уже работает — пресет менять нельзя."""
        return self._starting or self.server_running() or self.client_running()

    def _update_running_locks(self, busy: bool) -> None:
        """Блокирует всё, что меняет текущий пресет, пока он «в работе».

        Смена пресета или ветки на ходу рассогласовала бы показанное с реально
        запущенным: кнопка, статус и логи относились бы к одному пресету, а
        процессы — к другому. Создание пресета тоже блокируется: мастер по
        завершении переключается на созданный.
        """
        locked = busy or self.server_running() or self.client_running()
        lp = self.launch_page
        if not hasattr(self, "_lockable"):
            # исходные подсказки запоминаем один раз, чтобы вернуть их при разблокировке
            # pack_engine — тоже сюда: запущенная игра держит PBO открытыми,
            # и перепаковка при следующем запуске всё равно не пройдёт
            self._lockable = [(w, w.toolTip())
                              for w in (lp.preset_combo, lp.branch_combo,
                                        lp.b_new, lp.b_del, lp.pack_engine)]
        tip = tr("main.locked_running", "Недоступно, пока запущен сервер или клиент")
        for widget, own_tip in self._lockable:
            widget.setEnabled(not locked)
            widget.setToolTip(tip if locked else own_tip)
        if getattr(self, "mini", None) is not None:
            self.mini.preset_combo.setEnabled(not locked)

    def launch_button_clicked(self) -> None:
        if self.launch_state() == self.LB_STOP:
            self._stop_selected()
        else:
            self._launch()

    def _stop_selected(self) -> None:
        """Гасит то, что отмечено галками: обе — и сервер, и клиент; одна —
        только его. Так при живом сервере можно перезапустить один клиент."""
        lp = self.launch_page
        srv, cli = lp.chk_server.isChecked(), lp.chk_client.isChecked()
        if srv and cli:
            n = kill_all()          # заодно подчистит осиротевшие процессы
        else:
            n = 0
            if srv and kill_pid(self.server_pid):
                n += 1
            if cli and kill_pid(self.client_pid):
                n += 1
        if srv:
            self.server_pid = None
        if cli:
            self.client_pid = None
        self._append_log(tr("main.stopped", "Завершено процессов: {n}", n=n))
        self._update_launch_button()

    def _log_stopped(self) -> None:
        """Отмечает в логе момент, когда процесс перестал существовать.

        Опрос идёт раз в секунду, поэтому пишем только переход «был жив ->
        исчез», иначе строка сыпалась бы каждую секунду.
        """
        for attr, label in (("server_pid", tr("common.server", "Сервер")),
                            ("client_pid", tr("common.client", "Клиент"))):
            pid = getattr(self, attr)
            was = self._alive.get(attr, False)
            alive = bool(pid) and psutil.pid_exists(pid)
            if was and not alive:
                self._append_log(tr("main.log_stopped", "Статус: {n} отключён", n=label),
                                 "warning")
                side = SERVER if attr == "server_pid" else CLIENT
                self.launch_status.set_stopped(side)
                self.monitors[side].stop()
            self._alive[attr] = alive

    def _update_status(self) -> None:
        self._log_stopped()
        self._update_launch_button()

        def state(pid: int | None, name: str, color_run: str) -> str:
            if pid and psutil.pid_exists(pid):
                return (f'<span style="color:{color_run};">●</span> '
                        + tr("main.st_run", "{n}: работает (PID {p})", n=name, p=pid))
            if pid:
                return ('<span style="color:#ff6b6b;">●</span> '
                        + tr("main.st_dead", "{n}: завершился", n=name))
            return ('<span style="color:#777;">●</span> '
                    + tr("main.st_off", "{n}: не запущен", n=name))

        self.launch_page.status_label.setText(
            state(self.server_pid, tr("common.server", "Сервер"), "#4caf50") + "  "
            + state(self.client_pid, tr("common.client", "Клиент"), "#4caf50"))
        self.launch_page.status_label.setTextFormat(Qt.TextFormat.RichText)
        if getattr(self, "mini", None) and not self.mini.isHidden():
            self.mini.refresh_status()

    # ------------------------------------------------------------------ прочее

    def _settings_saved(self) -> None:
        # Перепроверяем пути после сохранения: наблюдатель Steam ловит только
        # смену состояния самого Steam, а путь мог вернуться в настройки и
        # помимо него — например, пользователь сохранил страницу со старым
        # значением в поле. Без этого удалённый компонент остался бы записан.
        self._drop_removed_paths()
        self.registry = ModRegistry(self.settings)
        self.registry.scan()
        self._bind_preset()
        self._update_branch_availability()
        self._notify("success", tr("settings.saved", "Настройки сохранены."))

    def _drop_removed_paths(self) -> None:
        """Проверяет все отслеживаемые компоненты разом."""
        states = self.steam_watcher.states()
        for key in SETTINGS_APPS:
            self._drop_if_removed(key, states.get(key))

    def _update_branch_availability(self) -> None:
        """Experimental-ветка доступна в списке, только если хотя бы одна из
        её папок (клиент/сервер) реально указана и существует."""
        s = self.settings
        # именно is_install, а не «папка существует»: после удаления игры из
        # Steam каталог часто остаётся (наши симлинки, serverDZ.cfg и прочее),
        # и ветка выглядела бы доступной, хотя запускать уже нечего
        exp_ok = is_install(s.client_exp, CLIENT_EXE) or is_install(s.server_exp, SERVER_EXE)
        combo = self.launch_page.branch_combo
        combo.setItemEnabled(1, exp_ok)
        if not exp_ok and combo.currentIndex() == 1:
            combo.setCurrentIndex(0)

        # Запаковка требует и pboProject, и DayZ Tools (pboProject зовёт
        # Оба режима — это pboProject, поэтому доступность у них общая:
        # он сам зовёт бинаризатор из DayZ Tools и без них падает.
        engine = self.launch_page.pack_engine
        ok = (Path(find_pbo_project_exe(s.mikero_tools)).is_file()
              and bool(s.dayz_tools) and Path(s.dayz_tools).is_dir())
        for data in ("normal", "full"):
            idx = engine.findData(data)
            engine.setItemEnabled(idx, ok)
            if not ok and engine.currentIndex() == idx:
                engine.setCurrentIndex(0)   # «Не перепаковывать»
        if not ok:
            engine.setToolTip(tr("main.repack_unavailable",
                                 "Перепаковка недоступна: нужны pboProject и DayZ Tools."))
        else:
            engine.setToolTip("")

    def _about(self) -> None:
        import re
        from PySide6.QtCore import Qt as _Qt
        text = tr("main.about",
                  "Утилита для запуска тестовой среды DayZ Standalone "
                  "и отладки модов.\n\n"
                  "Лицензия GPLv3 — бесплатно навсегда.\n"
                  "https://github.com/KRdayzmodding/KR_ServerManager\n\n"
                  "by [Kramtsov Arms]")
        # ссылки — кликабельными
        rich = re.sub(r"(https?://\S+)", r'<a href="\1">\1</a>',
                      html.escape(text)).replace("\n", "<br>")
        box = MessageBox("KR Server Manager", text, self)  # сначала plain — для расчёта размеров
        box.contentLabel.setTextFormat(_Qt.TextFormat.RichText)
        box.contentLabel.setTextInteractionFlags(_Qt.TextInteractionFlag.TextBrowserInteraction)
        box.contentLabel.setOpenExternalLinks(True)
        box.contentLabel.setText(rich)
        box.cancelButton.hide()
        box.buttonLayout.insertStretch(1)
        box.exec()

    # ---------------------------------------------------------------- трей

    def _setup_tray(self) -> None:
        """Иконка в трее + мини-окно. Крестик главного окна не закрывает
        приложение, а прячет его: в цикле отладки мода менеджер нужен
        постоянно, но разворачивать его целиком ради одной кнопки незачем."""
        self.mini = MiniWindow(self)
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("KR Server Manager")

        menu = SystemTrayMenu(parent=self)
        menu.addAction(Action(FIF.VIEW, tr("tray.restore", "Развернуть"),
                              triggered=self.restore_from_tray))
        menu.addSeparator()
        menu.addAction(Action(FIF.CLOSE, tr("tray.quit", "Закрыть"),
                              triggered=self.quit_app))
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.restore_from_tray()

    def restore_from_tray(self) -> None:
        self.mini.hide()
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def quit_app(self) -> None:
        """Настоящий выход. Запущенный сервер намеренно не трогаем: это
        отдельный процесс, и он должен пережить закрытие менеджера."""
        self._quitting = True
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802 — API Qt
        if not self._quitting:
            event.ignore()
            self.hide()
            self.mini.show_at_saved_pos()
            return
        self.mini.close()
        for w in self.packlog_windows.values():
            w.close()
        self.tray.hide()
        for w in (self.log_server, self.log_client):
            w.close()
        event.accept()
        QApplication.quit()
