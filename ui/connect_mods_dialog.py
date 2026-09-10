"""Подключение коллекции мастерской.

Здесь осталось только это. Выбор модов пресета переехал в панель модов: он был
отдельным окном, потом панелью рядом с библиотекой, и оба раза работа над одним
модом делилась между двумя местами. Теперь она в одной таблице — см. ModsPanel.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QTreeWidgetItem, QScrollArea, QWidget,
)
from qfluentwidgets import (
    PushButton, PrimaryPushButton, CaptionLabel, BodyLabel, HyperlinkLabel, FluentIcon as FIF,
)

from core import steam_api, steam_urls
from core.i18n import tr
from core.mods import ModRegistry, ModInfo, SOURCE_STEAM
from ui.steam_watch import SteamWatcher
from ui.theme import ThemedDialog

_GREY = QColor("#888888")
_GREEN = QColor("#2e7d32")

(COL_NAME, COL_TYPE) = range(2)
_KEYED_COLS = (COL_NAME,)


class _SortableItem(QTreeWidgetItem):
    """Сортирует COL_NAME по значению из UserRole+1, а не по тексту (своя копия
    mods_panel.ModTreeItem — та завязана на индексы колонок вкладки «Моды»,
    здесь у диалога другой набор колонок)."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        col = tree.sortColumn() if tree else 0
        if col in _KEYED_COLS:
            a = self.data(col, Qt.ItemDataRole.UserRole + 1)
            b = other.data(col, Qt.ItemDataRole.UserRole + 1)
            if a is not None and b is not None:
                return a < b
        return self.text(col).lower() < other.text(col).lower()


class CollectionFetchWorker(QThread):
    """Загрузка списка модов коллекции Steam Workshop (в фоне, не блокирует UI)."""
    done = Signal(list, dict, str)  # id модов по порядку, {id: название}, текст ошибки

    def __init__(self, collection_id: str, parent=None):
        super().__init__(parent)
        self.collection_id = collection_id

    def run(self) -> None:
        try:
            children = steam_api.get_collection_children(self.collection_id)
        except Exception as e:  # noqa: BLE001 — сеть/битая ссылка — показываем как ошибку
            self.done.emit([], {}, str(e))
            return
        if not children:
            self.done.emit([], {}, tr("collection.empty",
                                      "Коллекция не найдена или пуста."))
            return
        try:
            names = steam_api.get_published_file_names(children)
        except Exception:  # noqa: BLE001 — названия не критичны, покажем голые id
            names = {}
        self.done.emit(children, names, "")


class CollectionDialog(ThemedDialog):
    """Список модов коллекции — присутствующие обычным текстом, отсутствующие
    серым с ссылкой на страницу в Steam."""

    def __init__(self, child_ids: list[str], names: dict[str, str],
                registry: ModRegistry, parent=None):
        super().__init__(parent)
        self.found_mods: list[ModInfo] = []
        missing_ids = []

        self.setWindowTitle(tr("collection.title", "Коллекция Steam"))
        self.resize(480, 440)
        layout = QVBoxLayout(self)

        found_by_id = {m.workshop_id: m for m in registry.all()
                      if m.source == SOURCE_STEAM and m.workshop_id}
        # присутствующие — сверху, отсутствующие — снизу; порядок внутри
        # каждой группы — как в самой коллекции (стабильная сортировка)
        ordered = sorted(child_ids, key=lambda wid: 0 if wid in found_by_id else 1)
        for wid in ordered:
            if wid in found_by_id:
                self.found_mods.append(found_by_id[wid])
            else:
                missing_ids.append(wid)

        hint = CaptionLabel(
            tr("collection.missing_msg",
              "Не хватает модов: {n} из {total}. Подпишитесь на них в Steam, обновите список "
              "модов и повторите подключение коллекции — либо подключите то, что уже есть.",
              n=len(missing_ids), total=len(child_ids))
            if missing_ids else
            tr("collection.all_present", "Все моды коллекции уже есть в реестре."))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # список — в прокручиваемой области с ограниченной высотой: коллекция
        # может быть большой, и без этого окно раздувалось бы под все строки,
        # не помещаясь на экран
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # без этого viewport остаётся системным белым в тёмной теме
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        inner = QWidget()
        inner.setObjectName("collectionList")
        inner.setStyleSheet("QWidget#collectionList{background:transparent;}")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        # виджеты недостающих модов — их состояние обновляет наблюдатель Steam
        self._missing_rows: dict[str, tuple[BodyLabel, BodyLabel, HyperlinkLabel]] = {}
        for wid in ordered:
            found = found_by_id.get(wid)
            row = QHBoxLayout()
            if found:
                row.addWidget(BodyLabel(found.name), 1)
                status = BodyLabel(tr("collection.installed", "Установлен"))
                status.setStyleSheet(f"color: {_GREEN.name()};")
                row.addWidget(status)
            else:
                lbl = BodyLabel(names.get(wid) or wid)
                lbl.setStyleSheet(f"color: {_GREY.name()};")
                row.addWidget(lbl, 1)
                status = BodyLabel("")
                status.hide()
                row.addWidget(status)
                link = HyperlinkLabel(parent=self)
                link.setUrl(QUrl(steam_urls.workshop_item(wid)))
                link.setText(tr("mods.deps_open_workshop", "Открыть в Workshop"))
                row.addWidget(link)
                self._missing_rows[wid] = (lbl, status, link)
            inner_layout.addLayout(row)
        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        # Подписка происходит в Steam, окно об этом само не узнает — поэтому
        # следим за воркшопом и отмечаем моды скачавшимися прямо в списке.
        self.watcher = SteamWatcher(self)
        self.watcher.watch_workshop(steam_urls.APP_DAYZ)
        self.watcher.workshop_changed.connect(self._workshop_changed)
        if self._missing_rows:
            self.watcher.start()

        btns = QHBoxLayout()
        btns.addStretch(1)
        b_cancel = PushButton(tr("common.cancel", "Отмена"))
        b_cancel.clicked.connect(self.reject)
        btns.addWidget(b_cancel)
        if self.found_mods:
            b_connect = PrimaryPushButton(FIF.LINK, tr("collection.connect_present",
                                                        "Подключить имеющиеся ({n})",
                                                        n=len(self.found_mods)))
            b_connect.clicked.connect(self.accept)
            btns.addWidget(b_connect)
        layout.addLayout(btns)

    def _workshop_changed(self, ws) -> None:
        """Отмечает в списке моды, которые Steam качает или уже скачал.

        Строка мода остаётся на месте: перестраивать список под пользователем,
        пока он его читает, неудобнее, чем поменять подпись справа.
        """
        for wid, (lbl, status, link) in self._missing_rows.items():
            if wid in ws.installed:
                lbl.setStyleSheet("")
                status.setText(tr("collection.installed", "Установлен"))
                status.setStyleSheet(f"color: {_GREEN.name()};")
                status.show()
                link.hide()
            elif wid in ws.downloading:
                status.setText(tr("collection.downloading", "Скачивается…"))
                status.setStyleSheet(f"color: {_GREY.name()};")
                status.show()
            else:
                status.hide()
