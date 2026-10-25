"""Диалог предстартовой проверки: критичные и некритичные проблемы."""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QListWidgetItem
from PySide6.QtGui import QColor
from qfluentwidgets import (
    FluentIcon as FIF,
    ListWidget, PushButton, PrimaryPushButton, CheckBox, StrongBodyLabel,
)

from core.i18n import tr
from core.preflight import Problem, CRITICAL, has_critical
from ui.theme import ThemedDialog


class PreflightDialog(ThemedDialog):
    """Показывает найденные проблемы.

    «Пропустить и запустить» доступна, только если критичных проблем нет.
    Галка «игнорировать» скрывает эти же предупреждения до перезапуска программы.
    """

    def __init__(self, problems: list[Problem], parent=None):
        super().__init__(parent)
        self.problems = problems
        self.ignore_ids: set[str] = set()
        # Моды, которых нет нигде: их предлагаем убрать из пресета тут же.
        self.missing_mods = [p.missing_mod for p in problems if p.missing_mod]
        self.drop_missing = False
        self.setWindowTitle(tr("preflight.title", "Проверка перед запуском"))
        self.resize(640, 360)

        layout = QVBoxLayout(self)
        critical = has_critical(problems)
        header = (tr("preflight.blocked", "Найдены критичные проблемы — запуск невозможен:")
                  if critical else
                  tr("preflight.warnings", "Есть предупреждения. Можно продолжить."))
        layout.addWidget(StrongBodyLabel(header))

        lst = ListWidget()
        for p in problems:
            mark = "✖" if p.severity == CRITICAL else "⚠"
            item = QListWidgetItem(f"{mark}  {p.message}")
            item.setForeground(QColor("#d32f2f" if p.severity == CRITICAL else "#b8860b"))
            lst.addItem(item)
        layout.addWidget(lst, 1)

        self.chk_ignore = CheckBox(tr("preflight.ignore",
                                      "Не спрашивать до перезапуска программы"))
        self.chk_ignore.setToolTip(tr(
            "preflight.ignore_tip",
            "Эти же предупреждения больше не показываются, а работа по ним "
            "делается молча: устаревшие моды перепакуются сами."))
        self.chk_ignore.setEnabled(not critical)
        layout.addWidget(self.chk_ignore)

        btns = QHBoxLayout()
        if self.missing_mods:
            # Сообщить о тупике и не дать из него выйти — худшее, что может
            # сделать проверка. Эти моды не существуют ни в одной папке, и
            # единственное осмысленное действие с ними — убрать из пресета.
            btn_drop = PushButton(FIF.DELETE, tr(
                "preflight.drop_missing", "Убрать из пресета ({n})",
                n=len(self.missing_mods)))
            btn_drop.setToolTip(", ".join(self.missing_mods))
            btn_drop.clicked.connect(self._drop_missing)
            btns.addWidget(btn_drop)
        btns.addStretch(1)
        btn_cancel = PushButton(tr("common.cancel", "Отмена"))
        btn_cancel.clicked.connect(self.reject)
        # Подпись — по тому, что случится после нажатия, а не «пропустить»:
        # ничего не пропускается, запуск идёт своим порядком.
        btn_skip = PrimaryPushButton(tr("preflight.launch", "Запустить"))
        btn_skip.setEnabled(not critical)
        btn_skip.setDefault(not critical)
        btn_skip.clicked.connect(self._skip)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_skip)
        layout.addLayout(btns)

    def _drop_missing(self) -> None:
        """Выйти с просьбой убрать эти моды из пресета. Чинит их тот, кто звал."""
        self.drop_missing = True
        self.reject()

    def _skip(self) -> None:
        if self.chk_ignore.isChecked():
            self.ignore_ids = {p.check_id for p in self.problems if p.severity != CRITICAL}
        self.accept()
