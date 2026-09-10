"""Редактор serverDZ.cfg: все известные ключи, а не только написанные в файле.

Раньше здесь была таблица «переменная → текст», и она показывала ровно то, что
уже есть в файле. Ответить на вопрос «а что вообще можно настроить» было
нечем: ключ, которого в файле нет, не показывался, добавить его было нельзя, а
булевы значения набирались цифрами.

Теперь наоборот: список идёт от справочника (67 ключей), а файл только говорит,
какие из них включены. Галка слева — «писать этот ключ в файл»; снял галку —
ключ уходит из файла, и сервер берёт своё умолчание.

Значения типизированы: тумблер там, где 0/1, выбор там, где вариантов
несколько, поле там, где число или текст. Цифру «2» в графе «проверка
подписей» помнить больше не нужно.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, CheckBox, ComboBox, InfoBar, InfoBarPosition,
    LineEdit, PrimaryPushButton, PushButton, SearchLineEdit, SmoothScrollArea,
    StrongBodyLabel,
    SwitchButton, FluentIcon as FIF,
)

from core import servercfg
from core.i18n import tr
from core.servercfg import BOOL, BOOLSTR, CHOICE, ServerCfg, VarSpec
from ui import tokens
from ui.rows import Columns, Rule, setting_row, shrink, subheading

OTHER = "other"          # группа для ключей, которых нет в справочнике


class _Row:
    """Одна настройка: галка «в файле», контрол и умение отдать значение.

    Держим отдельным объектом, а не разбираем виджеты обратно: разбор формы
    ради сохранения — источник ошибок вида «поменял поле, а сохранилось
    старое».
    """

    def __init__(self, spec: VarSpec, owner: CfgKeys) -> None:
        self.spec = spec
        self.editor = owner
        self.check = CheckBox()
        self.check.setToolTip(tr("cfg.in_file", "Писать этот ключ в файл"))
        self.control = self._make_control()
        self.widget = setting_row(spec.name, spec.tooltip(), self.control,
                                  prefix=self.check)
        self.check.stateChanged.connect(owner._touch)

    # ------------------------------------------------------------- контролы

    def _make_control(self):
        kind = self.spec.kind
        if kind in (BOOL, BOOLSTR):
            sw = SwitchButton()
            sw.setOnText("")
            sw.setOffText("")
            sw.checkedChanged.connect(self._changed)
            return sw
        if kind == CHOICE:
            box = ComboBox()
            for value, label in self.spec.choices:
                box.addItem(label, userData=value)
            box.setFixedWidth(140)
            box.currentIndexChanged.connect(self._changed)
            return box
        edit = LineEdit()
        edit.setFixedWidth(170)
        edit.textEdited.connect(self._changed)
        return edit

    def _changed(self, *_a) -> None:
        """Поменял значение — ключ должен попасть в файл.

        Иначе получается ловушка: человек выставил значение, сохранил и не
        понял, почему ничего не изменилось, — галку он не заметил.
        """
        if not self.check.isChecked():
            self.check.setChecked(True)
        self.editor._touch()

    # -------------------------------------------------------------- значения

    def set_value(self, value: str | None) -> None:
        """value = None означает «в файле этого ключа нет»."""
        present = value is not None
        self.check.setChecked(present)
        shown = value if present else self.spec.default
        kind = self.spec.kind
        if kind == BOOL:
            self.control.setChecked(str(shown).strip() in ("1", "true", "True"))
        elif kind == BOOLSTR:
            self.control.setChecked(str(shown).strip().lower() == "true")
        elif kind == CHOICE:
            idx = self.control.findData(str(shown).strip())
            self.control.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            self.control.setText(str(shown))
            # Показать начало значения, а не хвост: длинный путь миссии иначе
            # виден с середины слова и опознаётся не сразу.
            self.control.setCursorPosition(0)

    def value(self) -> str | None:
        if not self.check.isChecked():
            return None
        kind = self.spec.kind
        if kind == BOOL:
            return "1" if self.control.isChecked() else "0"
        if kind == BOOLSTR:
            return "true" if self.control.isChecked() else "false"
        if kind == CHOICE:
            return str(self.control.currentData())
        return self.control.text().strip()

    def matches(self, query: str) -> bool:
        if not query:
            return True
        return query in self.spec.name.lower() or query in self.spec.hint.lower()


class CfgKeys(QWidget):
    """Список известных ключей конфига: поиск, группы, строки со значениями.

    Не знает ни про файл, ни про сохранение — ему дают значения и спрашивают,
    что должно оказаться в файле. Благодаря этому он одинаково работает и
    страницей, и внутри карточки на «Запуске».
    """

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: dict[str, _Row] = {}
        self.groups: dict[str, tuple[QWidget, Columns]] = {}
        # Пока раскладываем прочитанные значения по контролам, каждый из них
        # шлёт сигнал «поменялось». Без этого признака окно объявляло
        # несохранённые изменения сразу после открытия файла.
        self._loading = False

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(tokens.SPACE_XS)

        self.search = SearchLineEdit()
        self.search.setPlaceholderText(
            tr("cfg.search", "Найти среди {n} ключей…").format(n=len(servercfg.SPECS)))
        self.search.setMaximumWidth(320)
        self.search.textChanged.connect(self._filter)
        box.addWidget(self.search)

        self.nothing = CaptionLabel(tr("cfg.nothing", "Ничего не нашлось."))
        self.nothing.hide()
        box.addWidget(self.nothing)

        self.inner_box = QVBoxLayout()
        self.inner_box.setContentsMargins(0, 0, 0, 0)
        self.inner_box.setSpacing(tokens.SPACE_XS)
        box.addLayout(self.inner_box)

        for group in servercfg.GROUPS:
            self._add_group(group, servercfg.specs_of_group(group))

    # ---------------------------------------------------------------- группы

    def _add_group(self, group: str, specs: list[VarSpec]) -> None:
        if not specs:
            return
        title = tr(f"cfg.group.{group}", servercfg.GROUP_NAMES.get(group, group))
        head = subheading(title, line=bool(self.groups))
        widgets = []
        for spec in specs:
            row = _Row(spec, self)
            self.rows[spec.name] = row
            widgets.append(row.widget)
        cols = Columns(widgets)
        self.inner_box.addWidget(head)
        self.inner_box.addWidget(cols)
        self.groups[group] = (head, cols)

    def _touch(self, *_a) -> None:
        if self._loading:
            return
        self.changed.emit()

    def _filter(self, text: str) -> None:
        query = (text or "").strip().lower()
        found = 0
        for group, (head, cols) in self.groups.items():
            visible = [r.widget for r in self.rows.values()
                       if r.spec.group == group and r.matches(query)]
            cols.set_active(visible)
            head.setVisible(bool(visible))
            cols.setVisible(bool(visible))
            found += len(visible)
        self.nothing.setVisible(found == 0)

    # ---------------------------------------------------------------- данные

    def load(self, values: dict) -> None:
        """Расставляет значения. Ключа нет в словаре — значит нет и в файле."""
        self._loading = True
        try:
            self._drop_unknown_group()
            for name, row in self.rows.items():
                row.set_value(values.get(name))
            # Ключи, которых нет в справочнике: чужой мод, опечатка, новая
            # версия игры. Прятать их нельзя — сохранение тогда молча вынесло
            # бы их из файла; показываем как есть, текстом.
            unknown = [n for n in values if n not in servercfg.BY_NAME]
            if unknown:
                specs = [VarSpec(name=n, kind="str", group=OTHER,
                                 default=values[n],
                                 hint=tr("cfg.unknown_hint",
                                         "Ключа нет в справочнике — программа "
                                         "его не трогает."))
                         for n in unknown]
                self._add_group(OTHER, specs)
                for spec in specs:
                    self.rows[spec.name].set_value(values[spec.name])
        finally:
            self._loading = False
        self._filter(self.search.text())

    def _drop_unknown_group(self) -> None:
        for name, row in list(self.rows.items()):
            if row.spec.group == OTHER:
                row.widget.setParent(None)
                del self.rows[name]
        if OTHER in self.groups:
            head, cols = self.groups.pop(OTHER)
            head.setParent(None)
            cols.setParent(None)

    def wanted(self) -> dict:
        """Что должно оказаться в файле. None — ключа быть не должно."""
        return {name: row.value() for name, row in self.rows.items()}


class CfgEditor(QWidget):
    """Страница редактора: файл, кодировка, сохранение — вокруг списка ключей."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg: ServerCfg | None = None
        self._path: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_L, tokens.SPACE_L,
                                  tokens.SPACE_L, tokens.SPACE_L)
        layout.setSpacing(tokens.SPACE_S)

        top = QHBoxLayout()
        top.setSpacing(tokens.SPACE_S)
        # Путь длинный, и требовать под него ширину нельзя: окно из-за одной
        # подписи начинало требовать почти тысячу пикселей.
        self.path_label = shrink(BodyLabel(tr("cfg.no_file", "Конфиг не загружен")))
        self.enc_label = BodyLabel("")
        self.enc_label.setStyleSheet(f"color:{tokens.color('warning')};")
        self.unsaved = CaptionLabel("")
        self.unsaved.setStyleSheet(f"color:{tokens.color('warning')};")
        btn_reload = PushButton(FIF.SYNC, tr("cfg.reload", "Перечитать"))
        btn_reload.clicked.connect(self.reload)
        btn_save = PrimaryPushButton(FIF.SAVE, tr("common.save", "Сохранить"))
        btn_save.clicked.connect(self.save)
        top.addWidget(self.path_label, 1)
        top.addWidget(self.enc_label)
        top.addWidget(self.unsaved)
        top.addWidget(btn_reload)
        top.addWidget(btn_save)
        layout.addLayout(top)

        # Содержимое в прокрутке: 67 строк в окно не помещаются ни при какой
        # ширине, а распирать окно до высоты содержимого нельзя.
        scroll = SmoothScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(SmoothScrollArea.Shape.NoFrame)
        # Вбок страница не ездит никогда: содержимое перекладывается в меньшее
        # число колонок, а не уезжает за край. Иначе внизу появляется вторая
        # полоса прокрутки, и до правого контрола надо доскроллить.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}"
                             " QWidget#cfgInner{background:transparent;}")
        inner = QWidget()
        inner.setObjectName("cfgInner")
        inner_box = QVBoxLayout(inner)
        # справа — место под полосу прокрутки: без него контролы правой
        # колонки упираются в неё и обрезаются
        inner_box.setContentsMargins(0, 0, tokens.SPACE_XL, 0)
        inner_box.setSpacing(tokens.SPACE_XS)
        self.keys = CfgKeys()
        self.keys.changed.connect(self._touch)
        inner_box.addWidget(self.keys)
        inner_box.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        hint = CaptionLabel(tr(
            "cfg.hint2",
            "Снятая галка означает, что ключа в файле нет и сервер возьмёт своё "
            "умолчание. Комментарии и порядок строк сохраняются, файл пишется "
            "в UTF-8 без BOM."))
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def _touch(self) -> None:
        self.unsaved.setText(tr("cfg.dirty", "Есть несохранённые изменения"))

    # ---------------------------------------------------------------- данные

    def set_path(self, path: Path | None) -> None:
        self._path = path
        self.reload()

    def reload(self) -> None:
        self.cfg = None
        self.enc_label.setText("")
        self.unsaved.setText("")
        if not self._path or not self._path.is_file():
            self.path_label.setText(tr("cfg.no_file", "Конфиг не загружен"))
            self.keys.load({})
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
        self.keys.load(self.cfg.values())

    def save(self) -> None:
        if not self.cfg:
            return
        from core.launcher import dayz_running
        if dayz_running():
            InfoBar.warning(title=tr("cfg.save_busy", "Сервер запущен — сохранение отменено"),
                            content=tr("cfg.save_busy_body",
                                       "Остановите сервер: изменения cfg он всё равно не "
                                       "подхватит на лету, а при выходе может перезаписать файл."),
                            parent=self, duration=6000, position=InfoBarPosition.TOP_RIGHT)
            return
        try:
            self.cfg.apply(self.keys.wanted())
            self.cfg.save()
        except OSError as e:
            InfoBar.error(title=tr("cfg.save_err_title", "Ошибка сохранения"), content=str(e),
                          parent=self, duration=5000, position=InfoBarPosition.TOP_RIGHT)
            return
        self.enc_label.setText("")
        self.unsaved.setText("")
        InfoBar.success(title=tr("cfg.saved", "Конфиг сохранён в UTF-8 без BOM."), content="",
                        parent=self, duration=3000, position=InfoBarPosition.TOP_RIGHT)


class CfgCard(QWidget):
    """Конфиг сервера внутри карточки на «Запуске».

    Тот же список ключей, что на отдельной странице, но без пути и кодировки:
    файл здесь и так известен — он принадлежит выбранному пресету. Кнопка
    сохранения своя: конфиг это файл, и писать его на каждое нажатие тумблера
    нельзя.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg: ServerCfg | None = None
        self._path: Path | None = None

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(tokens.SPACE_XS)

        head = QHBoxLayout()
        head.setSpacing(tokens.SPACE_XS)
        head.addWidget(StrongBodyLabel(tr("cfg.card_title",
                                          "Конфиг сервера (serverDZ.cfg)")))
        self.unsaved = CaptionLabel("")
        self.unsaved.setStyleSheet(f"color:{tokens.color('warning')};")
        head.addWidget(self.unsaved)
        head.addStretch(1)
        self.btn_save = PushButton(FIF.SAVE, tr("common.save", "Сохранить"))
        self.btn_save.clicked.connect(self.save)
        head.addWidget(self.btn_save)
        box.addWidget(Rule())
        box.addLayout(head)

        self.keys = CfgKeys()
        self.keys.changed.connect(self._touch)
        box.addWidget(self.keys)

    def _touch(self) -> None:
        self.unsaved.setText(tr("cfg.dirty", "Есть несохранённые изменения"))

    def set_path(self, path: Path | None) -> None:
        self._path = path
        self.unsaved.setText("")
        self.cfg = None
        if not path or not Path(path).is_file():
            self.keys.load({})
            self.setEnabled(False)
            return
        self.setEnabled(True)
        try:
            self.cfg = ServerCfg(Path(path))
        except OSError:
            self.keys.load({})
            return
        self.keys.load(self.cfg.values())

    def save(self) -> None:
        if not self.cfg:
            return
        from core.launcher import dayz_running
        if dayz_running():
            InfoBar.warning(title=tr("cfg.save_busy", "Сервер запущен — сохранение отменено"),
                            content=tr("cfg.save_busy_body",
                                       "Остановите сервер: изменения cfg он всё равно не "
                                       "подхватит на лету, а при выходе может перезаписать файл."),
                            parent=self.window(), duration=6000,
                            position=InfoBarPosition.TOP_RIGHT)
            return
        try:
            self.cfg.apply(self.keys.wanted())
            self.cfg.save()
        except OSError as e:
            InfoBar.error(title=tr("cfg.save_err_title", "Ошибка сохранения"), content=str(e),
                          parent=self.window(), duration=5000,
                          position=InfoBarPosition.TOP_RIGHT)
            return
        self.unsaved.setText("")
        InfoBar.success(title=tr("cfg.saved", "Конфиг сохранён в UTF-8 без BOM."), content="",
                        parent=self.window(), duration=3000,
                        position=InfoBarPosition.TOP_RIGHT)
