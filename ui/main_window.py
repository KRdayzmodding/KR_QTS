"""Главное окно: пресеты, ветка, вкладки Запуск/Моды/Конфиг, статусы процессов."""
from __future__ import annotations

import html
from pathlib import Path

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton,
    QTabWidget, QCheckBox, QLabel, QPlainTextEdit, QMessageBox, QApplication,
)

from core import logsource
from core.i18n import tr
from core.launcher import LaunchWorker, kill_all, resolve_path
from core.mods import ModRegistry
from core.preflight import run_checks
from core.presets import ServerPreset
from core.settings import Settings, STABLE, EXPERIMENTAL
from ui.cfg_editor import CfgEditor
from ui.log_window import LogWindow
from ui.mods_panel import ModsPanel
from ui.preflight_dialog import PreflightDialog
from ui.preset_editor import (
    AdvancedPresetDialog, LazyPresetWizard, choose_creation_mode,
)
from ui.settings_dialog import SettingsDialog

_STATUS_COLORS = {"info": "#d4d4d4", "warning": "#e5c07b", "error": "#ff6b6b"}


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.registry = ModRegistry(settings)
        self.registry.scan()
        self.presets: list[ServerPreset] = ServerPreset.load_all()
        self.current: ServerPreset | None = None
        self.worker: LaunchWorker | None = None
        self.server_pid: int | None = None
        self.client_pid: int | None = None
        self.ignored_checks: set[str] = set()  # «игнорировать до перезапуска»

        self.setWindowTitle("KR Server Manager")
        self.resize(1000, 700)

        self.log_server = LogWindow(tr("main.server_log", "Логи сервера"))
        self.log_client = LogWindow(tr("main.client_log", "Логи клиента"))

        self._build_menu()
        self._build_ui()
        self._reload_presets()

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(1000)
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start()

    # ------------------------------------------------------------------ UI

    def _build_menu(self) -> None:
        m_file = self.menuBar().addMenu(tr("menu.file", "Файл"))
        act_settings = QAction(tr("menu.settings", "Настройки…"), self)
        act_settings.triggered.connect(self._open_settings)
        act_exit = QAction(tr("menu.exit", "Выход"), self)
        act_exit.triggered.connect(self.close)
        m_file.addAction(act_settings)
        m_file.addSeparator()
        m_file.addAction(act_exit)

        m_help = self.menuBar().addMenu(tr("menu.help", "Справка"))
        act_about = QAction(tr("menu.about", "О программе"), self)
        act_about.triggered.connect(self._about)
        m_help.addAction(act_about)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Верхняя полоса: пресет + ветка
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("main.preset", "Пресет:")))
        self.preset_combo = QComboBox()
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)
        top.addWidget(self.preset_combo, 1)
        b_new = QPushButton(tr("main.preset_new", "Создать"))
        b_new.clicked.connect(self._new_preset)
        b_edit = QPushButton(tr("main.preset_edit", "Изменить"))
        b_edit.clicked.connect(self._edit_preset)
        b_del = QPushButton(tr("main.preset_del", "Удалить"))
        b_del.clicked.connect(self._delete_preset)
        top.addWidget(b_new)
        top.addWidget(b_edit)
        top.addWidget(b_del)
        top.addSpacing(16)
        top.addWidget(QLabel(tr("main.branch", "Ветка:")))
        self.branch_combo = QComboBox()
        self.branch_combo.addItem("Stable", STABLE)
        self.branch_combo.addItem("Experimental", EXPERIMENTAL)
        self.branch_combo.currentIndexChanged.connect(self._branch_changed)
        top.addWidget(self.branch_combo)
        layout.addLayout(top)

        # Вкладки
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # --- Вкладка «Запуск»
        launch_tab = QWidget()
        lt = QVBoxLayout(launch_tab)
        row = QHBoxLayout()
        self.chk_server = QCheckBox(tr("main.chk_server", "Сервер"))
        self.chk_client = QCheckBox(tr("main.chk_client", "Клиент"))
        self.chk_server.toggled.connect(self._launch_flags_changed)
        self.chk_client.toggled.connect(self._launch_flags_changed)
        row.addWidget(self.chk_server)
        row.addWidget(self.chk_client)
        row.addStretch(1)
        lt.addLayout(row)

        row2 = QHBoxLayout()
        self.btn_launch = QPushButton(tr("main.launch", "▶  Запустить"))
        self.btn_launch.setMinimumHeight(40)
        self.btn_launch.clicked.connect(self._launch)
        self.btn_stop = QPushButton(tr("main.stop", "■ Остановить всё"))
        self.btn_stop.setMinimumHeight(40)
        self.btn_stop.clicked.connect(self._stop_all)
        btn_logs = QPushButton(tr("main.show_logs", "Показать логи"))
        btn_logs.setMinimumHeight(40)
        btn_logs.clicked.connect(self._show_logs)
        row2.addWidget(self.btn_launch, 2)
        row2.addWidget(self.btn_stop, 1)
        row2.addWidget(btn_logs, 1)
        lt.addLayout(row2)

        self.status_label = QLabel("")
        lt.addWidget(self.status_label)

        self.launch_log = QPlainTextEdit()
        self.launch_log.setReadOnly(True)
        self.launch_log.setFont(QFont("Consolas", 9))
        self.launch_log.setStyleSheet("QPlainTextEdit{background:#1e1e1e;color:#d4d4d4;}")
        lt.addWidget(self.launch_log, 1)
        self.tabs.addTab(launch_tab, tr("main.tab_launch", "Запуск"))

        # --- Вкладка «Моды»
        self.mods_panel = ModsPanel()
        self.tabs.addTab(self.mods_panel, tr("main.tab_mods", "Моды"))

        # --- Вкладка «Конфиг сервера»
        self.cfg_editor = CfgEditor()
        self.tabs.addTab(self.cfg_editor, tr("main.tab_cfg", "Конфиг сервера"))

    # ------------------------------------------------------------------ пресеты

    def _reload_presets(self, select: str | None = None) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.presets = ServerPreset.load_all()
        for p in self.presets:
            self.preset_combo.addItem(p.name, p.name)
        self.preset_combo.blockSignals(False)
        if not self.presets:
            self.current = None
            self._bind_preset()
            return
        idx = 0
        if select:
            for i, p in enumerate(self.presets):
                if p.name == select:
                    idx = i
                    break
        self.preset_combo.setCurrentIndex(idx)
        self._preset_changed(idx)

    def _preset_changed(self, idx: int) -> None:
        self.current = self.presets[idx] if 0 <= idx < len(self.presets) else None
        self._bind_preset()

    def _bind_preset(self) -> None:
        p = self.current
        self.chk_server.blockSignals(True)
        self.chk_client.blockSignals(True)
        self.chk_server.setChecked(p.launch_server if p else True)
        self.chk_client.setChecked(p.launch_client if p else True)
        self.chk_server.blockSignals(False)
        self.chk_client.blockSignals(False)
        if p:
            self.branch_combo.blockSignals(True)
            self.branch_combo.setCurrentIndex(0 if p.branch == STABLE else 1)
            self.branch_combo.blockSignals(False)
        self.mods_panel.set_context(self.registry, p)
        self._bind_cfg()
        self._bind_log_dirs()

    def _bind_cfg(self) -> None:
        p = self.current
        if p and p.server_config:
            path = resolve_path(p.server_config, self.settings.client_root(self._branch()))
            self.cfg_editor.set_path(Path(path))
        else:
            self.cfg_editor.set_path(None)

    def _bind_log_dirs(self) -> None:
        p = self.current
        branch = self._branch()
        self.log_server.set_directory(
            logsource.server_log_dir(p, self.settings, branch) if p else None)
        self.log_client.set_directory(logsource.client_log_dir(branch))

    def _branch(self) -> str:
        return self.branch_combo.currentData() or STABLE

    def _branch_changed(self, _idx: int) -> None:
        if self.current:
            self.current.branch = self._branch()
            self.current.save()
        self._bind_cfg()
        self._bind_log_dirs()

    def _launch_flags_changed(self) -> None:
        if self.current:
            self.current.launch_server = self.chk_server.isChecked()
            self.current.launch_client = self.chk_client.isChecked()
            self.current.save()

    def _new_preset(self) -> None:
        mode = choose_creation_mode(self)
        if mode == "lazy":
            wiz = LazyPresetWizard(self.settings, self)
            if wiz.exec() and wiz.result_preset:
                self._reload_presets(select=wiz.result_preset.name)
        elif mode == "advanced":
            preset = ServerPreset()
            dlg = AdvancedPresetDialog(preset, self.settings, self)
            if dlg.exec():
                self._reload_presets(select=preset.name)

    def _edit_preset(self) -> None:
        if not self.current:
            return
        dlg = AdvancedPresetDialog(self.current, self.settings, self)
        if dlg.exec():
            self._reload_presets(select=self.current.name)

    def _delete_preset(self) -> None:
        if not self.current:
            return
        ret = QMessageBox.question(
            self, tr("main.del_title", "Удаление пресета"),
            tr("main.del_confirm", "Удалить пресет «{n}»?", n=self.current.name))
        if ret == QMessageBox.StandardButton.Yes:
            self.current.delete()
            self._reload_presets()

    # ------------------------------------------------------------------ запуск

    def _append_log(self, msg: str, level: str = "info") -> None:
        color = _STATUS_COLORS.get(level, "#d4d4d4")
        self.launch_log.appendHtml(f'<span style="color:{color};">{html.escape(msg)}</span>')

    def _launch(self) -> None:
        p = self.current
        if not p:
            QMessageBox.information(self, "KR Server Manager",
                                    tr("main.no_preset", "Сначала создайте пресет."))
            return
        if not p.launch_server and not p.launch_client:
            QMessageBox.information(self, "KR Server Manager",
                                    tr("main.nothing", "Отметьте, что запускать: сервер и/или клиент."))
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
        cfg_path = resolve_path(p.server_config, self.settings.client_root(branch))
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
        prof = resolve_path(p.profiles, self.settings.client_root(branch))
        if prof:
            Path(prof).mkdir(parents=True, exist_ok=True)

        self.btn_launch.setEnabled(False)
        self._append_log(tr("main.launching", "— Запуск «{n}» ({b}) —", n=p.name, b=branch))
        self.worker = LaunchWorker(p, self.settings, branch, self.registry)
        self.worker.log.connect(self._append_log)
        self.worker.server_started.connect(self._on_server_started)
        self.worker.client_started.connect(self._on_client_started)
        self.worker.finished_ok.connect(lambda: self._launch_done(None))
        self.worker.failed.connect(self._launch_done)
        self.worker.start()

    def _on_server_started(self, pid: int) -> None:
        self.server_pid = pid
        self._bind_log_dirs()
        if not self.log_server.isVisible():
            self.log_server.show()

    def _on_client_started(self, pid: int) -> None:
        self.client_pid = pid

    def _launch_done(self, error: str | None) -> None:
        self.btn_launch.setEnabled(True)
        if error:
            self._append_log(error, "error")
            QMessageBox.critical(self, tr("main.launch_failed", "Запуск не удался"), error)
        else:
            self._append_log(tr("main.launch_ok", "Запуск завершён."))

    def _stop_all(self) -> None:
        n = kill_all()
        self._append_log(tr("main.stopped", "Завершено процессов: {n}", n=n))

    def _show_logs(self) -> None:
        self._bind_log_dirs()
        self.log_server.show()
        self.log_client.show()
        self.log_server.raise_()
        self.log_client.raise_()

    def _update_status(self) -> None:
        def state(pid: int | None, name: str) -> str:
            if pid and psutil.pid_exists(pid):
                return tr("main.st_run", "{n}: работает (PID {p})", n=name, p=pid)
            if pid:
                return tr("main.st_dead", "{n}: завершился", n=name)
            return tr("main.st_off", "{n}: не запущен", n=name)

        self.status_label.setText(
            state(self.server_pid, tr("main.server", "Сервер")) + "    |    " +
            state(self.client_pid, tr("main.client", "Клиент")))

    # ------------------------------------------------------------------ прочее

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.registry = ModRegistry(self.settings)
            self.registry.scan()
            self._bind_preset()

    def _about(self) -> None:
        QMessageBox.about(
            self, "KR Server Manager",
            tr("main.about",
               "KR Server Manager\n\nЛаунчер и менеджер модов для DayZ-разработки.\n"
               "Лицензия GPLv3 — бесплатно навсегда.\n"
               "https://github.com/KRdayzmodding/KR_ServerManager"))

    def closeEvent(self, event) -> None:  # noqa: N802 — API Qt
        for w in (self.log_server, self.log_client):
            w.close()
        event.accept()
        QApplication.quit()
