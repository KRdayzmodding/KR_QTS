"""Добавление своей карты — той, которой нет во встроенном списке.

Источник — папка с готовой миссией на диске: именно так карты и приходят от
авторов, репозиторий на GitHub есть у единиц. Эта же папка становится
шаблоном: из неё создаётся миссия пресета, из неё же пересоздаётся по кнопке.
Скачивать нечего, поэтому «Обновить шаблон» для таких карт не работает.

Список своих карт общий на все пресеты и лежит рядом с настройками, см.
core.missions.USER_CATALOG_FILE.
"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QFormLayout, QFileDialog
from qfluentwidgets import (
    LineEdit, PushButton, PrimaryPushButton, ToolButton, CaptionLabel,
    FluentIcon as FIF,
)

from core import missions
from core.i18n import tr
from core.missions import CatalogEntry
from ui.theme import ThemedDialog


def looks_like_mission(folder: Path) -> bool:
    """Похоже ли на папку миссии DayZ.

    Проверка нестрогая: состав миссий у разных карт отличается, и запретить
    человеку добавить свою из-за нашей придирчивости хуже, чем пропустить
    чужую папку — та честно упрётся в предстартовую проверку.
    """
    return ((folder / "db").is_dir() or (folder / "cfgeconomycore.xml").is_file()
            or (folder / "init.c").is_file())


class CustomMapDialog(ThemedDialog):
    """Создание и правка своей карты. entry — правим существующую."""

    def __init__(self, entry: CatalogEntry | None = None, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.removed = False
        self.setWindowTitle(tr("mission.custom_title", "Своя карта"))
        self.resize(600, 320)

        col = QVBoxLayout(self)
        form = QFormLayout()

        self.title = LineEdit()
        self.title.setPlaceholderText(tr("mission.custom_title_hint",
                                         "Как называть в списке карт"))
        self.title.textChanged.connect(self._recheck)
        form.addRow(tr("mission.custom_name", "Название"), self.title)

        folder_row = QHBoxLayout()
        self.folder = LineEdit()
        self.folder.setPlaceholderText(tr("mission.custom_folder_hint",
                                          "Папка с миссией"))
        self.folder.textChanged.connect(self._folder_changed)
        b_pick = ToolButton(FIF.FOLDER)
        b_pick.clicked.connect(self._pick_folder)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(b_pick)
        form.addRow(tr("mission.custom_folder", "Папка с миссией"), folder_row)

        self.world = LineEdit()
        self.world.setPlaceholderText("kot_map")
        self.world.textChanged.connect(self._recheck)
        self.world.setToolTip(tr(
            "mission.custom_world_tip",
            "Суффикс миссии — то, что стоит после точки: dayzOffline.chernarusplus, "
            "kot.kot_map. Подставляется сам по имени выбранной папки."))
        form.addRow(tr("mission.custom_world", "Мир"), self.world)

        self.map_mod = LineEdit()
        self.map_mod.setPlaceholderText(tr("mission.custom_optional", "необязательно"))
        self.map_mod.setToolTip(tr(
            "mission.custom_map_mod_tip",
            "Steam Workshop ID мода карты. Нужен только для предупреждения перед "
            "запуском, если мод не подписан."))
        form.addRow(tr("mission.custom_map_mod", "Мод карты (Workshop ID)"), self.map_mod)

        self.mods = LineEdit()
        self.mods.setPlaceholderText("@KR_BlankMap, @CF")
        self.mods.setToolTip(tr("mission.custom_mods_tip",
                                "Моды, которые добавятся в пресет вместе с картой."))
        form.addRow(tr("mission.custom_mods", "Моды карты"), self.mods)
        col.addLayout(form)

        self.error = CaptionLabel("")
        self.error.setStyleSheet("color:#d32f2f;")
        self.error.setWordWrap(True)
        col.addWidget(self.error)
        col.addStretch(1)

        btns = QHBoxLayout()
        self.b_del = PushButton(FIF.DELETE, tr("common.delete", "Удалить"))
        self.b_del.clicked.connect(self._remove)
        self.b_del.setVisible(entry is not None)
        btns.addWidget(self.b_del)
        btns.addStretch(1)
        b_cancel = PushButton(tr("common.cancel", "Отмена"))
        b_cancel.clicked.connect(self.reject)
        self.b_ok = PrimaryPushButton(FIF.SAVE, tr("common.save", "Сохранить"))
        self.b_ok.clicked.connect(self._save)
        btns.addWidget(b_cancel)
        btns.addWidget(self.b_ok)
        col.addLayout(btns)

        if entry is not None:
            self.title.setText(entry.title)
            self.folder.setText(entry.folder)
            self.world.setText(entry.world)
            self.map_mod.setText(entry.map_mod)
            self.mods.setText(", ".join(m.get("path", "") for m in entry.mods))
        self._recheck()

    # ------------------------------------------------------------------

    def _pick_folder(self) -> None:
        p = QFileDialog.getExistingDirectory(
            self, tr("mission.custom_pick", "Папка с миссией"), self.folder.text())
        if p:
            self.folder.setText(p)

    def _folder_changed(self, text: str) -> None:
        """Мир подставляем по имени папки: «kot.kot_map» -> «kot_map».

        Только в пустое поле: если человек вписал своё, перебивать его
        догадкой нельзя.
        """
        name = Path(text.strip().rstrip("\\/")).name
        if "." in name and not self.world.text().strip():
            self.world.setText(name.rsplit(".", 1)[1])
        self._recheck()

    def problem(self) -> str:
        """Что мешает сохранить. Пусто — всё в порядке."""
        if not self.title.text().strip():
            return tr("mission.custom_no_title", "Укажите название.")
        raw = self.folder.text().strip()
        if not raw:
            return tr("mission.custom_no_folder", "Укажите папку с миссией.")
        folder = Path(raw)
        if not folder.is_dir():
            return tr("mission.custom_bad_folder", "Папки не существует: {p}", p=raw)
        if not looks_like_mission(folder):
            return tr("mission.custom_not_mission",
                      "Не похоже на миссию: внутри нет ни db, ни cfgeconomycore.xml, "
                      "ни init.c.")
        world = self.world.text().strip()
        if not world:
            return tr("mission.custom_no_world", "Укажите мир — суффикс после точки.")
        if not re.fullmatch(r"[A-Za-z0-9_]+", world):
            return tr("mission.custom_bad_world",
                      "В имени мира допустимы только латиница, цифры и подчёркивание.")
        return ""

    def _recheck(self) -> None:
        problem = self.problem()
        self.error.setText(problem)
        self.b_ok.setEnabled(not problem)

    def _remove(self) -> None:
        if self.entry is None:
            return
        ok, err = missions.remove_user_map(self.entry.id)
        if not ok:
            self.error.setText(err)
            return
        self.removed = True
        self.accept()

    def result_entry(self) -> CatalogEntry:
        """Собранная запись — по ней же и сохраняем."""
        world = self.world.text().strip()
        folder = self.folder.text().strip()
        mods = [{"path": m.strip()} for m in self.mods.text().split(",") if m.strip()]
        # id держим устойчивым: у правки он остаётся прежним, у новой карты
        # складывается из мира и папки — две карты одного мира из разных папок
        # не сольются в одну запись
        map_id = self.entry.id if self.entry else f"user.{world}.{_short(folder)}"
        return CatalogEntry(id=map_id, title=self.title.text().strip(), world=world,
                            repo="", branch="", path="", mods=mods,
                            map_mod=self.map_mod.text().strip(), folder=folder)

    def _save(self) -> None:
        self._recheck()
        if self.problem():
            return
        entry = self.result_entry()
        ok, err = missions.add_user_map(entry)
        if not ok:
            self.error.setText(err)
            return
        self.entry = entry
        self.accept()


def _short(text: str) -> str:
    """Короткая устойчивая метка пути — для id записи.

    Хеш здесь не про защиту, а про то, чтобы две карты одного мира из разных
    папок не слились в одну запись. Поэтому blake2 с коротким выводом, а не
    sha1: тот и не быстрее, и вечно вызывает вопросы у проверок.
    """
    import hashlib
    return hashlib.blake2s(text.lower().encode("utf-8"), digest_size=4).hexdigest()
