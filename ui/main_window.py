"""Главное окно (Fluent): боковая навигация — Запуск / Моды / Конфиг / Настройки."""
from __future__ import annotations

import html
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QApplication,
    QSystemTrayIcon, QSplitter,
)
from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, FluentIcon as FIF,
    ComboBox, CheckBox, PushButton, PrimaryPushButton, TransparentToolButton,
    BodyLabel, StrongBodyLabel, CaptionLabel, CardWidget, InfoBar, InfoBarPosition, MessageBox,
    SystemTrayMenu, Action, qconfig,
)

from core import filepatch, logsource, packer, packlog, updater, winconsole, winhide
from core.i18n import tr
from core.launcher import LaunchWorker, dayz_running, kill_pid
from core.mods import ModRegistry
from core.preflight import run_checks
from core.presets import ServerPreset, MODE_DIAG
from core.settings import (
    Settings, STABLE, EXPERIMENTAL, CLIENT_EXE, SERVER_EXE, PATH_NOT_INSTALLED,
    check_path, find_pbo_project_exe, is_install,
)
from core.steam_urls import SETTINGS_APPS
from core.version import APP_NAME, VERSION
from ui.cfg_editor import CfgEditor
from ui.log_window import LogWindow
from ui.mods_panel import ModsPanel
from ui.preflight_dialog import PreflightDialog
from ui.preset_editor import AdvancedPresetDialog, LazyPresetWizard
from ui.settings_page import SettingsPage
from ui.steam_watch import SteamWatcher, status_text
from ui.mini_window import MiniWindow
from ui.packing_log import PackingLog
from ui.launch_status import (LaunchStatus, LaunchMonitor, READY_LAYER,
                              SERVER, CLIENT, PROC_RUN, PROC_STOPPING)
from ui.packlog_window import PackLogWindow
from ui.theme import app_icon, link_html, outside_icon

_STATUS_COLORS = {"info": "#d4d4d4", "success": "#4caf50",
                  "warning": "#e5c07b", "error": "#ff6b6b",
}
# Пауза перед показом накопившихся сообщений: за неё прилетает вся пачка
# событий одного обвала, и человек читает их одним окном, а не вереницей.
_ALERT_MERGE_MS = 400
# Сколько ждём закрытия по-хорошему, прежде чем убить
_STOP_WAIT_SEC = 25
_CONSOLE_QSS = ("QPlainTextEdit{background:#1e1e1e;color:#d4d4d4;"
                "border:1px solid #333;border-radius:6px;padding:4px;}")


class LaunchInterface(QWidget):
    """Страница «Запуск»: пресет, ветка, галки, кнопки, статус, журнал запуска."""

    def __init__(self, win: MainWindow):
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
        self.chk_hide_window = CheckBox(tr("main.hide_server_window",
                                           "Скрыть окно сервера"))
        self.chk_hide_window.setToolTip(tr(
            "main.hide_server_window_tip",
            "Сервер запустится без своего окна. Всё, что оно показывает, будет "
            "выводиться сюда, в журнал запуска."))
        row.addWidget(self.chk_hide_window)
        row.addStretch(1)
        self.status_label = StrongBodyLabel("")
        row.addWidget(self.status_label)
        srv.addLayout(row)

        row2 = QHBoxLayout()
        self.btn_launch = PrimaryPushButton(FIF.PLAY, tr("main.launch_btn", "Запустить"))
        self.btn_launch.setMinimumHeight(38)
        self.btn_logs = PushButton(FIF.DOCUMENT, tr("main.show_logs",
                                                    "Логи клиента/сервера"))
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
        self.btn_sources = PushButton(FIF.SYNC, tr("main.mods_with_sources",
                                                   "Перепаковка модов"))
        self.btn_sources.setMinimumHeight(38)
        self.btn_packlogs = PushButton(FIF.ZIP_FOLDER, tr("main.show_packlogs",
                                                          "Логи запаковки"))
        self.btn_packlogs.setMinimumHeight(38)
        self.btn_packlogs.setToolTip(tr("main.show_packlogs_tip",
                                        "Логи pboProject по последней запаковке: "
                                        "отдельно сборка pbo, отдельно бинаризация."))
        row3.addWidget(self.btn_sources, 1)
        row3.addWidget(self.btn_packlogs, 1)
        pack.addLayout(row3)

        # Журнал запуска и — когда окно сервера спрятано — его консоль под ним.
        # Двумя областями, а не одной лентой: это разные потоки. Наш журнал
        # редкий и осмысленный, консоль сервера частая и подробная; смешав их,
        # мы утопили бы первое во втором.
        self.launch_log = QPlainTextEdit()
        self.launch_log.setReadOnly(True)
        self.launch_log.setFont(QFont("Consolas", 9))
        self.launch_log.setStyleSheet(_CONSOLE_QSS)

        self.console_box = QWidget()
        cbox = QVBoxLayout(self.console_box)
        cbox.setContentsMargins(0, 0, 0, 0)
        cbox.setSpacing(4)
        cbox.addWidget(CaptionLabel(tr("main.server_console", "Консоль сервера")))
        self.console_log = QPlainTextEdit()
        self.console_log.setReadOnly(True)
        self.console_log.setMaximumBlockCount(5000)
        self.console_log.setFont(QFont("Consolas", 9))
        self.console_log.setStyleSheet(_CONSOLE_QSS)
        cbox.addWidget(self.console_log, 1)
        # появляется только у сервера, запущенного без своего окна
        self.console_box.setVisible(False)

        self.log_split = QSplitter(Qt.Orientation.Vertical)
        self.log_split.addWidget(self.launch_log)
        self.log_split.addWidget(self.console_box)
        self.log_split.setStretchFactor(0, 1)
        self.log_split.setStretchFactor(1, 1)
        layout.addWidget(self.log_split, 1)


class MainWindow(FluentWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.registry = ModRegistry(settings)
        self.registry.scan()
        self.presets: list[ServerPreset] = []
        self.current: ServerPreset | None = None
        # модальные сообщения из наблюдателей — по очереди, см. _alert
        self._adopted = False           # стороны подхвачены, а не запущены нами
        # мягкая остановка: с какого момента ждём закрытия каждой стороны
        self._stopping: dict[str, float] = {}
        # консоль сервера в журнал — когда его окно спрятано, см. _console_start
        self._console_tailer: logsource.LogTailer | None = None
        self._console_win: winconsole.WindowConsole | None = None
        self._console_prof: Path | None = None
        self._console_timer = QTimer(self)
        self._console_timer.setInterval(500)
        self._console_timer.timeout.connect(self._console_poll)
        self._alerts: list[tuple[str, str]] = []
        self._alert_busy = False
        self.worker: LaunchWorker | None = None
        self.server_pid: int | None = None
        self.client_pid: int | None = None
        self._alive: dict[str, bool] = {}      # для отметки об отключении в логе
        self._quitting = False                 # выход только через меню трея
        self._starting = False                 # идёт запуск: кнопка «Запускается»
        self._launch_logged = False            # «Запуск завершён» — один раз на запуск
        # обновление: available -> downloading -> ready
        self._upd_release = None
        self._upd_state = ""
        self._upd_percent = 0
        self._upd_worker = None
        self._upd_dl = None
        self._upd_dialog = None
        self.ignored_checks: set[str] = set()  # «игнорировать до перезапуска»

        self.setWindowTitle("KR Quick Test Server")
        # Иконка приложения уже задана в main.py, но заголовок FluentWindow
        # свой, не системный: он подхватывает картинку по сигналу
        # windowIconChanged, а при наследовании от QApplication тот не приходит
        # — без явной установки в шапке остаётся пустое место.
        # иконка монохромная и светлая: на светлой шапке её не видно, поэтому
        # там она инвертируется. На панель задач и в «Пуск» уходит исходная —
        # подробности в _apply_icon. Перевыставляется при смене темы на лету,
        # включая случай «следовать теме Windows».
        self._apply_icon()
        qconfig.themeChanged.connect(self._apply_icon)
        self.resize(1060, 720)

        self.log_server = LogWindow(tr("main.server_log", "Логи сервера"),
                                    accent="#2e7d32", banner_text="SERVER", key=SERVER)
        self.log_client = LogWindow(tr("main.client_log", "Логи клиента"),
                                    accent="#1565c0", banner_text="CLIENT", key=CLIENT)
        for win in (self.log_server, self.log_client):
            win.set_on_top(getattr(settings, f"log_on_top_{win.key}", False))
            win.on_top_changed = self._log_on_top_changed

        # Страницы
        self.launch_page = LaunchInterface(self)
        self.mods_panel = ModsPanel()
        self.mods_panel.setObjectName("modsInterface")
        self.mods_panel.log_cb = self._append_log
        # вкладка модов пересобирает реестр в фоне и отдаёт новый экземпляр —
        # главное окно и мини-окно должны перейти на него, иначе останутся
        # с прежним списком модов
        self.mods_panel.registry_changed = self._registry_rescanned
        # смена метки «серверный» перекладывает мод по строкам запуска прямо в
        # файлах пресетов — тот, что открыт у нас, надо перечитать, иначе
        # запустимся по устаревшему списку из памяти
        self.mods_panel.presets_changed.connect(self._presets_changed_outside)
        self.pack_table = PackingLog(self.launch_page.launch_log)
        self.launch_status = LaunchStatus(self.launch_page.launch_log)
        # у сервера и клиента свои RPT в разных папках — свой наблюдатель на каждого
        self.monitors = {side: LaunchMonitor(side, self) for side in (SERVER, CLIENT)}
        for mon in self.monitors.values():
            mon.usage.connect(self._on_usage)
            mon.crashed.connect(self._on_crash)
            mon.errored.connect(self._on_script_error)
            mon.danger.connect(self._on_memory_danger)
            mon.limit.connect(self._on_memory_limit)
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
        # Пункт обновления живёт в панели навигации: она видна с любой
        # страницы, и признак остаётся на глазах постоянно, ничего не
        # перекрывая и не требуя реакции. Появляется только когда есть что
        # сказать — см. _update_nav_item.
        self._upd_item = self.navigationInterface.addItem(
            routeKey="update", icon=FIF.UPDATE, text=tr("upd.nav", "Обновление"),
            onClick=self._open_update, selectable=False,
            position=NavigationItemPosition.BOTTOM)
        self._upd_item.setVisible(False)
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
        lp.chk_hide_window.setChecked(settings.hide_server_window)
        lp.chk_hide_window.toggled.connect(self._hide_window_changed)
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
        lp.pack_engine.setCurrentIndex(max(idx, 0))
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

    def _presets_changed_outside(self) -> None:
        """Пресеты правили мимо нас — перечитать, сохранив выбранный."""
        self._reload_presets(select=self.current.file_stem() if self.current else None)

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

    def _registry_rescanned(self, registry: ModRegistry) -> None:
        self.registry = registry
        self._update_sources_button()

    def _apply_icon(self) -> None:
        """Перевыставляет иконки: снаружи окна серая, в шапке — под тему.

        Внутри окна фон известен точно, мы сами его рисуем, — там максимальный
        контраст. Снаружи фон нам не принадлежит, и подстраиваться не под что,
        см. ui.theme.outside_icon.
        """
        outside = outside_icon()
        self.setWindowIcon(outside)
        QApplication.instance().setWindowIcon(outside)
        # строго после setWindowIcon: оно само шлёт в шапку свою иконку по
        # сигналу windowIconChanged, и наш вариант должен лечь поверх
        self.titleBar.setIcon(app_icon())

    def _log_on_top_changed(self, key: str, on: bool) -> None:
        """Галка «поверх всех» — своя у каждого окна логов."""
        setattr(self.settings, f"log_on_top_{key}", on)
        self.settings.save()

    def adopt_running(self) -> None:
        """Подхватывает клиент и сервер, работающие с прошлого раза.

        Менеджер можно закрыть, а сервер оставить — это сделано намеренно. Но
        новый экземпляр про него не знал: показывал «остановлен», предлагал
        запустить и молчал про занятый порт. Человек либо поднимал второй сервер
        поверх первого, либо шёл убивать процесс через диспетчер.

        Опознание идёт по командной строке процесса, см. core.adopt. Чужой
        сервер не трогаем, но сообщаем о нём: упереться в занятый порт и не
        понять почему — худшее из состояний.
        """
        from core import adopt
        from core.layout import resolve_profiles

        profiles = {}
        for p in self.presets:
            prof = resolve_profiles(p.profiles, self.settings, p.branch, p.mode)
            if prof:
                profiles[p.name] = prof
        try:
            found = adopt.find(profiles)
        except Exception as e:      # noqa: BLE001 — подхват не обязан ронять запуск окна
            self._append_log(tr("adopt.failed", "Не удалось опросить процессы: {e}", e=e),
                             "warning")
            return
        if not found:
            return

        mine = [r for r in found if r.mine]
        alien = [r for r in found if not r.mine]
        for r in alien:
            self._append_log(tr(
                "adopt.alien",
                "На машине работает DayZ ({s}, PID {pid}), но это не наш запуск"
                "{port}. Порт может быть занят.",
                s=self._side_name(SERVER if r.side == adopt.SERVER else CLIENT),
                pid=r.pid,
                port=tr("adopt.alien_port", ", порт {p}", p=r.port) if r.port else ""),
                "warning")
        if not mine:
            return

        # Пресет выбираем по найденному серверу: логи и конфиг должны смотреть
        # именно на него, а не на то, что осталось выбранным с прошлого раза.
        srv = next((r for r in mine if r.side == adopt.SERVER), None)
        target = srv or mine[0]
        for i, p in enumerate(self.presets):
            if p.name == target.preset:
                self.launch_page.preset_combo.setCurrentIndex(i)
                break

        cfg = None
        if self.current and self.current.server_config:
            from core.layout import resolve_config
            cfg = resolve_config(self.current.server_config, self.settings,
                                 self._branch(), self.current.mode)
        self.launch_status.start(
            self._server_name(self.current, cfg) if srv and self.current else "",
            self._client_name(self.current)
            if self.current and any(r.side == adopt.CLIENT for r in mine) else "")
        for r in mine:
            side = SERVER if r.side == adopt.SERVER else CLIENT
            if side == SERVER:
                self.server_pid = r.pid
            else:
                self.client_pid = r.pid
            self._adopted = True
            self.launch_status.set_process_state(side, PROC_RUN)
            self._append_log(tr("adopt.taken",
                                "Подхвачен работающий {s} (PID {pid}), пресет «{n}»",
                                s=self._side_name(side), pid=r.pid, n=r.preset), "success")
        self._bind_log_dirs(adopt=True)
        self._start_monitors_for_adopted()
        if self.server_pid:
            self._console_start()
        self._update_launch_button()

    def _start_monitors_for_adopted(self) -> None:
        """Наблюдатели за логами подхваченных сторон.

        Скриптовую память и ошибки они возьмут из уже написанных файлов: сессия
        началась до нас, и «текущей» для неё считается всё, что есть.
        """
        from core.layout import resolve_profiles
        p = self.current
        if not p:
            return
        branch = self._branch()
        if self.server_pid:
            prof = resolve_profiles(p.profiles, self.settings, branch, p.mode)
            self.monitors[SERVER].start(Path(prof) if prof else None, adopt=True)
        if self.client_pid:
            self.monitors[CLIENT].start(logsource.client_log_dir(branch), adopt=True)

    def _bind_log_dirs(self, adopt: bool | None = None) -> None:
        """adopt — стороны уже работали до нас: лежащие файлы и есть их сессия.

        Значение по умолчанию берётся из состояния окна, а не считается ложью.
        Перепривязка случается не только при подхвате: её делают открытие окон
        логов, смена ветки, выбор пресета. Каждая такая перепривязка со
        сброшенным признаком стирала бы подхваченную сессию — и логи, только
        что показанные, снова превращались бы в «ещё не запускались».

        Обычно окно логов запоминает, что было в папке до запуска, и «текущей
        сессией» считает появившееся после — иначе показывало бы прошлый запуск
        как свежий. При подхвате это правило надо снять: сессия началась раньше
        нас, и её файл как раз лежит в папке.
        """
        if adopt is None:
            adopt = self._adopted
        p = self.current
        branch = self._branch()
        self.log_server.set_directory(
            logsource.server_log_dir(p, self.settings, branch) if p else None,
            adopt=adopt)
        self.log_client.set_directory(logsource.client_log_dir(branch), adopt=adopt)

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

    def _hide_window_changed(self, on: bool) -> None:
        """Запоминаем выбор: он относится к следующему запуску, а не к разовому."""
        self.settings.hide_server_window = on
        self.settings.save()

    def _console_start(self) -> None:
        """Начинает выводить консоль сервера в журнал запуска.

        Нужна ровно тогда, когда окно сервера спрятано: то, что человек привык
        видеть в нём, должно появиться там, куда он смотрит. При видимом окне
        это был бы дубль — те же строки в двух местах.

        Источник — server_console.log, его задаёт logFile в serverDZ.cfg. Это
        тот же поток, что показывает окно сервера, слово в слово.
        """
        self._console_stop()
        p = self.current
        if not p or not self.settings.hide_server_window:
            return
        from core.layout import resolve_profiles
        prof = resolve_profiles(p.profiles, self.settings, self._branch(), p.mode)
        if not prof:
            return
        self.launch_page.console_log.clear()
        self.launch_page.console_box.setVisible(True)
        self._console_prof = Path(prof)
        # Сначала пробуем читать окно сервера: файл отстаёт на десятки секунд,
        # окно обновляется сразу. Если окна не найдётся — уйдём на файл сами,
        # см. _console_fallback.
        if self.server_pid:
            self._console_win = winconsole.WindowConsole(self.server_pid, self)
            self._console_win.lines.connect(self._console_lines)
            self._console_win.unavailable.connect(self._console_fallback)
            self._console_win.start()
        else:
            self._console_fallback()

    def _console_fallback(self) -> None:
        """Окна нет — читаем файл. Хуже по свежести, но работает всегда.

        Файл общий для всех запусков сервера, за день в нём накапливается
        несколько тысяч строк от разных сессий. Свой запуск читаем с конца —
        всё, что допишется, наше. Подхваченный — с последней отметки начала
        сессии: его начало было до нас, но в файле оно помечено.
        """
        if self._console_prof is None:
            return
        self._console_tailer = logsource.LogTailer(
            self._console_prof, pattern_filter="server_console.log",
            start_from=logsource.CONSOLE_SESSION_MARK if self._adopted else "end")
        self._console_timer.start()

    def _console_stop(self) -> None:
        self._console_timer.stop()
        self._console_tailer = None
        self._console_prof = None
        if self._console_win is not None:
            self._console_win.stop()
            self._console_win = None
        self.launch_page.console_box.setVisible(False)

    def _console_lines(self, lines: list) -> None:
        view = self.launch_page.console_log
        for line in lines:
            color = _STATUS_COLORS.get(logsource.classify(line), "#d4d4d4")
            view.appendHtml(f'<span style="color:{color};">{html.escape(line)}</span>')

    def _console_poll(self) -> None:
        if self._console_tailer is None:
            return
        view = self.launch_page.console_log
        for line in self._console_tailer.poll():
            line = line.rstrip()
            if not line:
                continue
            color = _STATUS_COLORS.get(logsource.classify(line), "#d4d4d4")
            view.appendHtml(f'<span style="color:{color};">{html.escape(line)}</span>')

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

    def _on_script_error(self, side: str, report) -> None:
        """Ошибка в скриптах: движок написал crash-лог, но работать продолжает.

        NULL pointer и прочие исключения времени выполнения — это дефекты в
        коде мода, а не сорванный запуск. Сервер после них живёт, за сессию их
        набирается сколько угодно, и каждое окно поперёк экрана было бы
        издевательством. Поэтому только счётчик рядом с состоянием стороны —
        подробности человек посмотрит в логах, когда сам захочет.
        """
        self.launch_status.add_error(side, report)

    def _on_crash(self, side: str, report) -> None:
        """Запуск сорвался — скрипты не собрались.

        Это единственное место, где сказано, из-за чего именно: файл и строка.
        Поэтому и в журнал крупно, и отдельным окном — пропустить это нельзя,
        сервер попросту не поднимется.
        """
        self.launch_status.set_crash(side, report)
        self._append_alarm(tr("status.crash_log", "{s}: запуск сорван — {r}",
                              s=self._side_name(side), r=report.summary()))
        where = report.file and tr("status.crash_where", "Файл: {f}, строка {n}",
                                   f=report.file, n=report.line) or ""
        self._alert(
            tr("status.crash_title", "Запуск сорван: {s}", s=self._side_name(side)),
            "\n\n".join(x for x in (
                report.headline,
                where,
                report.message,
                tr("status.crash_hint", "Подробности — в {p}", p=report.path.name),
            ) if x))

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
        self._alert(
            tr("status.mem_limit_title", "Достигнут лимит скриптовой памяти"),
            tr("status.mem_limit_body",
               "{s}: слой {l} достиг лимита скриптовой памяти — занято {u} из {t} кБ.\n\n"
               "С таким набором модов запуск не состоится — нужно скорректировать "
               "список подключённых модов.",
               s=self._side_name(side), l=usage.layer,
               u=usage.used_kb, t=usage.total_kb))

    def _alert(self, title: str, body: str) -> None:
        """Модальное сообщение по очереди, а не поверх предыдущего.

        Эти окна приходят из наблюдателей по таймеру, а таймер продолжает
        работать и пока открыто модальное окно — так устроен цикл событий Qt.
        Значит второе сообщение способно открыться изнутри первого. У MessageBox
        своя затемняющая маска поверх родителя; две наложенные маски оставляют
        внешнее окно недоступным после закрытия внутреннего, и программа
        выглядит зависшей намертво.

        Поэтому сообщения не вкладываются, а ждут очереди. И показываются не из
        обработчика сигнала, а следующим тактом: открывать модальное окно
        посреди чужого разбора событий — само по себе способ найти неприятность.
        """
        self._alerts.append((title, body))
        if self._alert_busy:
            return
        self._alert_busy = True
        QTimer.singleShot(_ALERT_MERGE_MS, self._drain_alerts)

    def _drain_alerts(self) -> None:
        """Показывает накопившееся одним окном.

        Обвал запуска редко бывает одиночным: скрипты не собрались, слой упёрся
        в память, сторона завершилась — всё в пределах одного мгновения. Гнать
        это вереницей окон, каждое со своим «Понятно», — наказание за чужую
        ошибку в коде. Поэтому короткая пауза перед показом: за неё прилетает
        вся пачка, и человек читает её разом.
        """
        try:
            while self._alerts:
                batch, self._alerts = self._alerts, []
                if len(batch) == 1:
                    title, body = batch[0]
                else:
                    title = tr("status.alerts_title", "Проблемы при запуске")
                    body = "\n\n".join(f"{t}\n{b}" for t, b in batch)
                box = MessageBox(title, body, self)
                box.yesButton.setText(tr("common.ok", "Понятно"))
                box.cancelButton.hide()
                box.exec()
        finally:
            # даже если окно бросит исключение, очередь не должна встать навсегда
            self._alert_busy = False

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

        self._adopted = False   # запускаем сами: сессия начинается сейчас
        self._starting = True
        self._launch_logged = False
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
        не дожидаясь конца всей процедуры запуска (дальше ещё клиент).

        Статус «запущен» здесь не ставим: занятый порт — ещё не готовность,
        скрипты в этот момент только компилируются. Это делает 5_Mission.
        """
        self._starting = False
        self._update_launch_button()

    def _on_server_started(self, pid: int) -> None:
        # В журнал не пишем: стартовавший процесс ещё ничего не значит, скрипты
        # только начали компилироваться. PID виден в строке статуса, сама
        # готовность — в блоке, по слою 5_Mission.
        self.server_pid = pid
        self.launch_status.set_connecting(SERVER)
        self._bind_log_dirs()
        self._console_start()

    def _on_client_started(self, pid: int) -> None:
        self.client_pid = pid
        self.launch_status.set_connecting(CLIENT)

    def _on_usage(self, side: str, usage) -> None:
        """Расход памяти слоя — и заодно признак готовности стороны.

        Правило общее для сервера и клиента: 5_Mission компилируется последним,
        пока его нет — сторона ещё грузится. Признак берётся из собственного
        лога стороны, поэтому у клиента работает и когда сервер поднимаем не мы.
        """
        self.launch_status.set_usage(side, usage)
        if usage.layer == READY_LAYER:
            self.launch_status.set_running(side)
            self._check_launch_complete()

    def _check_launch_complete(self) -> None:
        """«Запуск завершён» — когда готовы все стороны, которые запускали.

        Раньше строка появлялась по возврату потока запуска, то есть сразу
        после того, как процессы созданы: сервер в этот момент ещё компилирует
        скрипты, а клиент висит на загрузке. Запускали одну сторону — ждём одну,
        обе — ждём обе.
        """
        if self._launch_logged:
            return
        active = [k for k, side in self.launch_status.sides.items() if side.active]
        # через side_state, а не через готовность напрямую: сторона, успевшая
        # подняться и тут же упасть, завершённым запуском не считается
        if not active or not all(self.side_state(k) == self.ST_RUN for k in active):
            return
        self._launch_logged = True
        self._append_log(tr("main.launch_ok", "Запуск завершён."), "success")
        self._notify("success", tr("main.launch_ok", "Запуск завершён."))

    def _launch_done(self, error: str | None) -> None:
        self._starting = False
        self._update_launch_button()
        if error:
            self._append_log(error, "error")
            self._notify("error", tr("main.launch_failed", "Запуск не удался"), error)
        else:
            # про успех сообщит _check_launch_complete, когда стороны реально
            # поднимутся: здесь процессы только созданы
            self._check_launch_complete()

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

    # Состояния стороны — общие для строки в шапке, кружков мини-окна и блока
    # в журнале. Индикаторов трое, правило одно: считать их по отдельности —
    # верный способ показать в одном месте «работает», а в другом «запускается».
    ST_RUN, ST_STARTING, ST_DEAD, ST_OFF = "run", "starting", "dead", "off"
    ST_STOPPING = "stopping"
    STATE_COLORS = {ST_RUN: "#4caf50", ST_STARTING: "#e5c07b",
                    # выключается — тот же жёлтый, что и «запускается»: оба про
                    # переход, и оба означают «подожди, ещё не устоялось»
                    ST_STOPPING: "#e5c07b",
                    ST_DEAD: "#ff6b6b", ST_OFF: "#777777"}

    @staticmethod
    def process_state(pid: int | None) -> str:
        """run — процесс жив; dead — запускали, но он завершился; off — не запускали."""
        if pid and psutil.pid_exists(pid):
            return MainWindow.ST_RUN
        return MainWindow.ST_DEAD if pid else MainWindow.ST_OFF

    def side_pid(self, side: str) -> int | None:
        return self.server_pid if side == SERVER else self.client_pid

    def side_state(self, side: str) -> str:
        """Единственный источник состояния стороны для всех индикаторов.

        Живого процесса мало: он появляется задолго до готовности — сервер ещё
        компилирует скрипты, клиент висит на загрузке. Запущенной сторона
        считается, когда в её логе появился расход памяти слоя 5_Mission: он
        компилируется последним. До этого — «запускается».
        """
        if ("server_pid" if side == SERVER else "client_pid") in self._stopping:
            return self.ST_STOPPING
        proc = self.process_state(self.side_pid(side))
        if proc != self.ST_RUN:
            return proc
        return self.ST_RUN if self.launch_status.is_ready(side) else self.ST_STARTING

    def server_running(self) -> bool:
        """Есть ли что останавливать. Кнопка запуска смотрит именно на процесс,
        а не на готовность: зависший на загрузке клиент тоже нужно уметь убить."""
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
                                        lp.b_new, lp.b_del, lp.pack_engine,
                                        # окно уже создано или нет — на ходу
                                        # этот выбор ничего не изменит
                                        lp.chk_hide_window)]
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
        только его. Так при живом сервере можно перезапустить один клиент.

        Способ берётся из настроек. Мягкий просит окна закрыться и отпускает
        интерфейс: сервер завершается своим порядком за несколько секунд, и всё
        это время он честно показан «выключается», а не мгновенно исчезает.
        Жёсткий убивает сразу — быстро, но обрывает сохранение на полуслове.
        """
        lp = self.launch_page
        srv, cli = lp.chk_server.isChecked(), lp.chk_client.isChecked()
        soft = getattr(self.settings, "stop_method", "soft") != "hard"
        for want, side, attr in ((srv, SERVER, "server_pid"),
                                 (cli, CLIENT, "client_pid")):
            if not want:
                continue
            pid = getattr(self, attr)
            if soft and pid and winhide.ask_close(pid):
                # процесс ещё жив — pid не сбрасываем, иначе перестанем за ним
                # следить и не заметим, что он так и не закрылся
                self.launch_status.set_process_state(side, PROC_STOPPING)
                self._stopping[attr] = time.monotonic()
                self._append_log(tr("main.log_stopping", "Статус: {n} выключается",
                                    n=self._side_name(side)))
                continue
            kill_pid(pid)
            setattr(self, attr, None)
            self._stopping.pop(attr, None)
        self._update_launch_button()

    def _watch_stopping(self) -> None:
        """Досматривает мягкую остановку: закрылся — хорошо, завис — убиваем.

        Ждать бесконечно нельзя: сервер может не отреагировать на просьбу
        вовсе, и тогда кнопка навсегда осталась бы в «выключается».
        """
        for attr, side in (("server_pid", SERVER), ("client_pid", CLIENT)):
            started = self._stopping.get(attr)
            if started is None:
                continue
            pid = getattr(self, attr)
            if not pid or not psutil.pid_exists(pid):
                setattr(self, attr, None)
                self._stopping.pop(attr, None)
                continue
            if time.monotonic() - started > _STOP_WAIT_SEC:
                self._append_log(tr("main.log_stop_forced",
                                    "{n} не закрылся сам — завершаем принудительно",
                                    n=self._side_name(side)), "warning")
                kill_pid(pid)
                setattr(self, attr, None)
                self._stopping.pop(attr, None)

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
                # статус блока обновит _update_status по состоянию процесса —
                # здесь только глушим наблюдателя за логами
                self.monitors[SERVER if attr == "server_pid" else CLIENT].stop()
                if attr == "server_pid":
                    self._console_stop()   # сервера нет — читать его консоль нечем
            self._alive[attr] = alive

    def _update_sources_button(self) -> None:
        """Перепаковывать нечего, пока ни одному моду не заданы сорсы.

        Кнопка в этом случае гаснет, но подсказка объясняет почему — иначе
        неактивная кнопка выглядит поломкой.
        """
        mods = [m for m in self.registry.all() if m.sources] if self.registry else []
        btn = self.launch_page.btn_sources
        btn.setEnabled(bool(mods))
        btn.setToolTip(tr("main.mods_with_sources_tip",
                          "Локальные моды, у которых заданы папки сорсов — "
                          "оттуда же их можно перепаковать.") if mods else
                       tr("main.no_mods_with_sources",
                          "Нет модов, которым указаны сорсы"))

    def _update_status(self) -> None:
        self._watch_stopping()
        self._log_stopped()
        self._update_sources_button()
        # блок в журнале узнаёт о процессах отсюда же, а не отдельным путём
        for side in (SERVER, CLIENT):
            self.launch_status.set_process_state(side, self.process_state(
                self.side_pid(side)))
        self._update_launch_button()

        def state(side: str, name: str) -> str:
            st = self.side_state(side)
            text = {
                self.ST_RUN: tr("main.st_run", "{n}: работает (PID {p})",
                                n=name, p=self.side_pid(side)),
                self.ST_STARTING: tr("main.st_starting", "{n}: запускается (PID {p})",
                                     n=name, p=self.side_pid(side)),
                self.ST_DEAD: tr("main.st_dead", "{n}: завершился", n=name),
            }.get(st, tr("main.st_off", "{n}: не запущен", n=name))
            return f'<span style="color:{self.STATE_COLORS[st]};">●</span> {text}'

        self.launch_page.status_label.setText(
            state(SERVER, tr("common.server", "Сервер")) + "  "
            + state(CLIENT, tr("common.client", "Клиент")))
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

    # ------------------------------------------------------------ обновление

    def start_update_check(self) -> None:
        """Фоновая проверка версии. Зовётся после показа окна, не до.

        Уже скачанное обновление важнее проверки: если оно ждёт перезапуска,
        спрашивать GitHub незачем.
        """
        ready = updater.pending()
        if ready:
            self._upd_release = ready
            self._upd_state = "ready"
            self._update_nav_item()
            return
        if not self.settings.check_updates:
            return
        self._upd_worker = updater.CheckWorker(self)
        self._upd_worker.done.connect(self._on_update_checked)
        self._upd_worker.start()

    def check_updates_now(self) -> None:
        """Проверка по кнопке из настроек — вручную, невзирая на галку."""
        if self._upd_worker and self._upd_worker.isRunning():
            return
        self._notify("info", tr("upd.checking", "Проверяю обновления…"), duration=3000)
        self._upd_worker = updater.CheckWorker(self)
        self._upd_worker.done.connect(self._on_manual_checked)
        self._upd_worker.start()

    def _on_manual_checked(self, rel) -> None:
        if updater.is_update(rel):
            self._on_update_checked(rel)
            self._open_update()
        elif rel is None:
            self._notify("warning", tr("upd.check_failed",
                                       "Не удалось проверить обновления"),
                         tr("upd.check_failed_body",
                            "Нет сети или релизы недоступны."))
        else:
            self._notify("success", tr("upd.uptodate", "Установлена последняя версия"),
                         tr("upd.uptodate_body", "Версия {v}", v=VERSION))

    def _on_update_checked(self, rel) -> None:
        # None — нет сети, нет релизов или репозиторий закрыт: молчим
        if not updater.is_update(rel):
            return
        self._upd_release = rel
        self._upd_state = "available"
        self._update_nav_item()
        # окно само не открываем: человек мог запускать сервер в спешке.
        # Пункт в навигации виден постоянно — этого достаточно.

    def _update_nav_item(self) -> None:
        """Подпись и цвет пункта под текущее состояние."""
        item = self._upd_item
        rel = self._upd_release
        if not rel:
            item.setVisible(False)
            return
        text = {
            "available": tr("upd.nav_available", "Доступна версия {v}", v=rel.version),
            "downloading": tr("upd.nav_downloading", "Скачивание… {p}%", p=self._upd_percent),
            "ready": tr("upd.nav_ready", "Перезапустить для установки"),
        }.get(self._upd_state, tr("upd.nav", "Обновление"))
        item.setText(text)
        item.setVisible(True)
        if getattr(self, "mini", None):
            self.mini.set_update_mark(self._upd_state == "ready")

    def _open_update(self) -> None:
        """Окно с описанием изменений — только по клику пользователя."""
        rel = self._upd_release
        if not rel:
            return
        if self._upd_state == "ready":
            self._offer_restart(rel)
            return
        from ui.update_dialog import UpdateDialog
        dlg = UpdateDialog(rel, downloading=self._upd_state == "downloading", parent=self)
        # окно остаётся открытым на время загрузки и само служит индикатором,
        # поэтому старт и завершение приходят сигналами, а не по коду выхода
        dlg.download_requested.connect(lambda: self._start_download(rel))
        dlg.restart_requested.connect(lambda: self._offer_restart(rel))
        self._upd_dialog = dlg
        # запомнили, что чейнджлог этой версии показан — больше не навязываем
        if self.settings.update_seen != rel.version:
            self.settings.update_seen = rel.version
            self.settings.save()
        dlg.exec()
        self._upd_dialog = None

    def _start_download(self, rel) -> None:
        if self._upd_dl and self._upd_dl.isRunning():
            return
        self._upd_state = "downloading"
        self._upd_percent = 0
        self._update_nav_item()
        self._upd_dl = updater.DownloadWorker(rel, self)
        self._upd_dl.progress.connect(self._on_update_progress)
        self._upd_dl.done.connect(lambda _p: self._on_update_downloaded(rel))
        self._upd_dl.failed.connect(self._on_update_failed)
        self._upd_dl.start()

    def _on_update_progress(self, got: int, total: int) -> None:
        self._upd_percent = int(got * 100 / total) if total else 0
        self._update_nav_item()
        if self._upd_dialog:
            self._upd_dialog.set_progress(got, total)

    def _on_update_downloaded(self, rel) -> None:
        self._upd_state = "ready"
        self._update_nav_item()
        self._notify("success", tr("upd.done_title", "Обновление скачано"),
                     tr("upd.done_body", "Версия {v} установится при перезапуске.",
                        v=rel.version), duration=8000)
        if self._upd_dialog:
            # окно открыто — превращаем кнопку в «перезапустить» прямо в нём,
            # второе окно поверх первого было бы навязчиво
            self._upd_dialog.set_ready()
        else:
            self._offer_restart(rel)

    def _on_update_failed(self, msg: str) -> None:
        self._upd_state = "available"
        self._update_nav_item()
        if self._upd_dialog:
            self._upd_dialog.set_failed(msg)
        self._notify("error", tr("upd.failed", "Не удалось скачать обновление"), msg)

    def _offer_restart(self, rel) -> None:
        from ui.update_dialog import RestartDialog
        dlg = RestartDialog(rel, self)
        dlg.exec()
        if dlg.restart_now:
            self._append_log(tr("upd.restarting", "Перезапуск для установки обновления…"))
            self._install_update(rel)

    def _install_update(self, rel) -> None:
        """Распаковывает обновление и передаёт установку помощнику."""
        from ui import update_install
        err = update_install.install(rel, self)
        if err:
            self._notify("error",
                         tr("upd.install_failed", "Обновление не установлено"), err)
            return
        self.quit_app()

    def _about(self) -> None:
        import re
        from PySide6.QtCore import Qt as _Qt
        text = tr("main.about",
                  "Версия {v}\n\n"
                  "Утилита для запуска тестовой среды DayZ Standalone "
                  "и отладки модов.\n\n"
                  "Лицензия GPLv3 — бесплатно навсегда.\n"
                  "https://github.com/KRdayzmodding/KR_QTS\n\n"
                  "by [Kramtsov Arms]", v=VERSION)
        # ссылки — кликабельными и своего цвета: синий по умолчанию от Qt на
        # тёмном фоне почти неразличим, см. ui.theme.link_color
        rich = re.sub(r"(https?://\S+)", lambda m: link_html(m.group(1)),
                      html.escape(text)).replace("\n", "<br>")
        box = MessageBox(APP_NAME, text, self)  # сначала plain — для расчёта размеров
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
        self.tray = QSystemTrayIcon(outside_icon(), self)
        self.tray.setToolTip("KR Quick Test Server")

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

    def closeEvent(self, event) -> None:  # имя метода задаёт Qt
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
