"""Главное окно (Fluent): боковая навигация — Запуск / Моды / Конфиг / Настройки."""
from __future__ import annotations

import html
from pathlib import Path

import psutil
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QApplication
from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, FluentIcon as FIF,
    ComboBox, CheckBox, PushButton, PrimaryPushButton, TransparentToolButton,
    BodyLabel, StrongBodyLabel, CardWidget, InfoBar, InfoBarPosition, MessageBox,
)

from core import logsource
from core.i18n import tr
from core.launcher import LaunchWorker, kill_all
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
from ui.settings_page import SettingsPage

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

        # Пресет + ветка
        top = QHBoxLayout()
        top.addWidget(BodyLabel(tr("main.preset", "Пресет:")))
        self.preset_combo = ComboBox()
        self.preset_combo.setMinimumWidth(260)
        top.addWidget(self.preset_combo, 1)
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
        layout.addLayout(top)

        # Карточка запуска
        card = CardWidget()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 12, 16, 12)
        row = QHBoxLayout()
        self.chk_server = CheckBox(tr("common.server", "Сервер"))
        self.chk_client = CheckBox(tr("common.client", "Клиент"))
        row.addWidget(self.chk_server)
        row.addWidget(self.chk_client)
        row.addStretch(1)
        self.status_label = StrongBodyLabel("")
        row.addWidget(self.status_label)
        cl.addLayout(row)

        row2 = QHBoxLayout()
        self.btn_launch = PrimaryPushButton(FIF.PLAY, tr("main.launch_btn", "Запустить"))
        self.btn_launch.setMinimumHeight(38)
        self.btn_stop = PushButton(FIF.CLOSE, tr("main.stop_btn", "Остановить всё"))
        self.btn_stop.setMinimumHeight(38)
        self.btn_logs = PushButton(FIF.DOCUMENT, tr("main.show_logs", "Показать логи"))
        self.btn_logs.setMinimumHeight(38)
        row2.addWidget(self.btn_launch, 2)
        row2.addWidget(self.btn_stop, 1)
        row2.addWidget(self.btn_logs, 1)
        cl.addLayout(row2)
        layout.addWidget(card)

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
        self.ignored_checks: set[str] = set()  # «игнорировать до перезапуска»

        self.setWindowTitle("KR Server Manager")
        self.resize(1060, 720)

        self.log_server = LogWindow(tr("main.server_log", "Логи сервера"))
        self.log_client = LogWindow(tr("main.client_log", "Логи клиента"))

        # Страницы
        self.launch_page = LaunchInterface(self)
        self.mods_panel = ModsPanel()
        self.mods_panel.setObjectName("modsInterface")
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
        lp.chk_server.toggled.connect(self._launch_flags_changed)
        lp.chk_client.toggled.connect(self._launch_flags_changed)
        lp.btn_launch.clicked.connect(self._launch)
        lp.btn_stop.clicked.connect(self._stop_all)
        lp.btn_logs.clicked.connect(self._show_logs)

        self._reload_presets()

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(1000)
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start()

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
        for chk, val in ((lp.chk_server, p.launch_server if p else True),
                         (lp.chk_client, p.launch_client if p else True)):
            chk.blockSignals(True)
            chk.setChecked(val)
            chk.blockSignals(False)
        if p:
            lp.branch_combo.blockSignals(True)
            lp.branch_combo.setCurrentIndex(0 if p.branch == STABLE else 1)
            lp.branch_combo.blockSignals(False)
        self.mods_panel.set_context(self.registry, p, self.settings)
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

    def _new_preset(self) -> None:
        mode = choose_creation_mode(self)
        if mode == "lazy":
            wiz = LazyPresetWizard(self.settings, self)
            if wiz.exec() and wiz.result_preset:
                self._reload_presets(select=wiz.result_preset.file_stem())
        elif mode == "advanced":
            preset = ServerPreset()
            dlg = AdvancedPresetDialog(preset, self.settings, self)
            if dlg.exec():
                self._reload_presets(select=preset.file_stem())

    def _edit_preset(self) -> None:
        if not self.current:
            return
        dlg = AdvancedPresetDialog(self.current, self.settings, self)
        if dlg.exec():
            self._reload_presets(select=self.current.file_stem())

    def _delete_preset(self) -> None:
        p = self.current
        if not p:
            return
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout
        from qfluentwidgets import BodyLabel

        dlg = QDialog(self)
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

    def _notify(self, kind: str, title: str, text: str = "") -> None:
        fn = {"success": InfoBar.success, "warning": InfoBar.warning,
              "error": InfoBar.error}.get(kind, InfoBar.info)
        fn(title=title, content=text, parent=self, duration=4000,
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

        self.launch_page.btn_launch.setEnabled(False)
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
        self.launch_page.btn_launch.setEnabled(True)
        if error:
            self._append_log(error, "error")
            self._notify("error", tr("main.launch_failed", "Запуск не удался"), error)
        else:
            self._append_log(tr("main.launch_ok", "Запуск завершён."))
            self._notify("success", tr("main.launch_ok", "Запуск завершён."))

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

    # ------------------------------------------------------------------ прочее

    def _settings_saved(self) -> None:
        self.registry = ModRegistry(self.settings)
        self.registry.scan()
        self._bind_preset()
        self._notify("success", tr("settings.saved", "Настройки сохранены."))

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

    def closeEvent(self, event) -> None:  # noqa: N802 — API Qt
        for w in (self.log_server, self.log_client):
            w.close()
        event.accept()
        QApplication.quit()
