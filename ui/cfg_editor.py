"""Вкладка редактора serverDZ.cfg: переменная -> поле ввода, кодировка UTF-8 без BOM."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QMessageBox, QHeaderView,
)

from core.i18n import tr
from core.servercfg import ServerCfg

# Подсказки к самым ходовым переменным
_HINTS_RU = {
    "hostname": "Название сервера в браузере серверов.",
    "password": "Пароль для входа на сервер (пусто — без пароля).",
    "passwordAdmin": "Пароль администратора (команды #login).",
    "maxPlayers": "Максимум игроков.",
    "verifySignatures": "Проверка подписей PBO: 2 — включена (нужны .bikey в keys), 0 — выключена (для разработки).",
    "forceSameBuild": "Пускать только клиентов с той же сборкой игры.",
    "disableVoN": "Отключить голосовой чат.",
    "vonCodecQuality": "Качество кодека голоса (0–30).",
    "disable3rdPerson": "Запретить вид от третьего лица.",
    "disableCrosshair": "Убрать прицел.",
    "serverTime": "Стартовое время сервера: SystemTime или \"YYYY/MM/DD/HH/MM\".",
    "serverTimeAcceleration": "Ускорение игрового времени (множитель).",
    "serverNightTimeAcceleration": "Дополнительное ускорение ночи.",
    "serverTimePersistent": "Сохранять игровое время между рестартами.",
    "instanceId": "Идентификатор инстанса (папка storage_<id> в миссии).",
    "storageAutoFix": "Автопочинка битого persistence-файла.",
    "steamQueryPort": "Порт Steam Query (обычно порт+2).",
    "enableDebugMonitor": "Показать отладочный монитор игрокам.",
    "allowFilePatching": "Пускать клиентов с -filePatching (обязательно для отладки сорсов).",
    "lightingConfig": "Освещение ночи: 0 — яркая, 1 — тёмная.",
    "disableBaseDamage": "Отключить урон по базам.",
    "disableContainerDamage": "Отключить урон по контейнерам.",
    "disableRespawnDialog": "Скрыть диалог выбора точки респауна.",
}


class CfgEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg: ServerCfg | None = None

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.path_label = QLabel(tr("cfg.no_file", "Конфиг не загружен"))
        self.enc_label = QLabel("")
        self.enc_label.setStyleSheet("color:#b8860b;")
        btn_reload = QPushButton(tr("cfg.reload", "Перечитать"))
        btn_reload.clicked.connect(self.reload)
        btn_save = QPushButton(tr("cfg.save", "Сохранить (UTF-8 без BOM)"))
        btn_save.clicked.connect(self.save)
        top.addWidget(self.path_label, 1)
        top.addWidget(self.enc_label)
        top.addWidget(btn_reload)
        top.addWidget(btn_save)
        layout.addLayout(top)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([
            tr("cfg.var", "Переменная"), tr("cfg.value", "Значение"),
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        hint = QLabel(tr("cfg.hint",
                         "Меняются только значения — комментарии и структура файла сохраняются."))
        hint.setStyleSheet("color:#888;")
        layout.addWidget(hint)

        self._path: Path | None = None

    def set_path(self, path: Path | None) -> None:
        self._path = path
        self.reload()

    def reload(self) -> None:
        self.table.setRowCount(0)
        self.cfg = None
        self.enc_label.setText("")
        if not self._path or not self._path.is_file():
            self.path_label.setText(tr("cfg.no_file", "Конфиг не загружен"))
            return
        try:
            self.cfg = ServerCfg(self._path)
        except OSError as e:
            self.path_label.setText(str(e))
            return
        self.path_label.setText(str(self._path))
        if self.cfg.encoding != "utf-8":
            self.enc_label.setText(tr("cfg.bad_enc",
                                      "Кодировка {enc} — при сохранении станет UTF-8 без BOM",
                                      enc=self.cfg.encoding))
        for v in self.cfg.variables():
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(v.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            hint = _HINTS_RU.get(v.name)
            if hint:
                name_item.setToolTip(tr(f"cfgvar.{v.name}", hint))
            val_item = QTableWidgetItem(v.value)
            if hint:
                val_item.setToolTip(tr(f"cfgvar.{v.name}", hint))
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, val_item)

    def save(self) -> None:
        if not self.cfg:
            return
        values = {}
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0).text()
            values[name] = self.table.item(row, 1).text()
        try:
            self.cfg.set_values(values)
            self.cfg.save()
        except OSError as e:
            QMessageBox.critical(self, tr("cfg.save_err_title", "Ошибка сохранения"), str(e))
            return
        self.enc_label.setText("")
        QMessageBox.information(self, tr("cfg.saved_title", "Сохранено"),
                                tr("cfg.saved", "Конфиг сохранён в UTF-8 без BOM."))
