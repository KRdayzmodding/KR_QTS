"""Создание ключа подписи: имя, папка, и что дальше делать с открытой половиной.

Окно крошечное и появляется раз в жизни проекта, поэтому вся его работа — не
дать ошибиться в двух полях и честно сказать, что получилось. Ключи делает
чужая программа (см. core/signkey), мы только спрашиваем имя и место.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QFormLayout, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    BodyLabel, CaptionLabel, LineEdit, PrimaryPushButton, PushButton, ToolButton,
    FluentIcon as FIF,
)

from core import signkey
from core.i18n import tr
from core.settings import APP_DIR, Settings
from ui import tokens
from ui.theme import ThemedDialog


class SignKeyDialog(ThemedDialog):
    """Спрашивает имя и папку, создаёт пару ключей, отдаёт путь к закрытому."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.created = ""           # путь к .biprivatekey, если получилось
        self.setWindowTitle(tr("key.title", "Создание ключа подписи"))
        self.resize(*tokens.WIN_S)

        box = QVBoxLayout(self)
        box.setContentsMargins(tokens.SPACE_L, tokens.SPACE_L,
                               tokens.SPACE_L, tokens.SPACE_L)
        box.setSpacing(tokens.SPACE_S)

        about = CaptionLabel(tr(
            "key.about",
            "Закрытым ключом подписываются собранные PBO, открытый кладётся "
            "в папку keys сервера. Пара делается один раз на проект: заведёте "
            "новую — прежние подписи сервер перестанет принимать."))
        about.setWordWrap(True)
        box.addWidget(about)

        form = QFormLayout()
        form.setSpacing(tokens.SPACE_S)
        self.name = LineEdit()
        # Имя проекта — разумное умолчание: по нему потом и опознают подпись.
        self.name.setText(_default_name(settings))
        self.name.setPlaceholderText("KR")
        self.name.textChanged.connect(self._check)
        form.addRow(BodyLabel(tr("key.name", "Имя ключа")), self.name)

        row = QHBoxLayout()
        row.setSpacing(tokens.SPACE_XS)
        self.folder = LineEdit()
        self.folder.setText(str(APP_DIR / "keys"))
        self.folder.textChanged.connect(self._check)
        pick = ToolButton(FIF.FOLDER)
        pick.clicked.connect(self._pick)
        row.addWidget(self.folder, 1)
        row.addWidget(pick)
        form.addRow(BodyLabel(tr("key.folder", "Папка")), row)
        box.addLayout(form)

        self.note = CaptionLabel("")
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        box.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel = PushButton(tr("common.cancel", "Отмена"))
        self.cancel.clicked.connect(self.reject)
        self.make = PrimaryPushButton(FIF.ADD, tr("key.make", "Создать"))
        self.make.clicked.connect(self._create)
        buttons.addWidget(self.cancel)
        buttons.addWidget(self.make)
        box.addLayout(buttons)

        self._check()

    # ----------------------------------------------------------------- ввод

    def _pick(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "", self.folder.text())
        if chosen:
            self.folder.setText(chosen)

    def _check(self) -> None:
        """Держит кнопку в согласии с полями и объясняет, чего не хватает."""
        why = signkey.can_create(self.settings)
        name = self.name.text().strip()
        if not why and not signkey.NAME_RE.match(name):
            why = tr("key.bad_name",
                     "Имя: латиница, цифры, дефис и подчёркивание, до 32 знаков")
        elif not why and not self.folder.text().strip():
            why = tr("key.no_folder", "Выберите папку")
        elif not why:
            exists = Path(self.folder.text().strip()) / (name + signkey.PRIVATE_SUFFIX)
            if exists.is_file():
                why = tr("key.exists", "Такой ключ уже есть: {p}", p=str(exists))
        self.make.setEnabled(not why)
        self.note.setText(why)
        self.note.setStyleSheet(
            f"color:{tokens.color('warning' if why else 'text_dim')};")

    # --------------------------------------------------------------- работа

    def _create(self) -> None:
        ok, result = signkey.create(self.settings, self.name.text(),
                                    self.folder.text())
        if not ok:
            self.note.setText(result)
            self.note.setStyleSheet(f"color:{tokens.color('error')};")
            return
        self.created = result
        self.accept()


def _default_name(settings: Settings) -> str:
    """Имя по умолчанию — префикс проекта, если он годится в имя ключа."""
    prefix = (settings.project_prefix or "").strip()
    return prefix if signkey.NAME_RE.match(prefix) else ""
