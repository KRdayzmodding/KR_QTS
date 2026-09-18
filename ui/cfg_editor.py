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

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel, CheckBox, ComboBox, InfoBar, InfoBarPosition,
    LineEdit, PushButton, SearchLineEdit, StrongBodyLabel,
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


class CfgCard(QWidget):
    """Конфиг сервера внутри карточки на «Запуске».

    Кнопка сохранения своя: конфиг это файл, и писать его на каждое нажатие
    тумблера нельзя.

    Раньше рядом жила отдельная страница с тем же списком ключей — второй вход
    в одно и то же место, лишний пункт в панели разделов и лишний переход. От
    неё сюда переехало то, чего в карточке не было: имя файла, который сейчас
    правим, предупреждение о кодировке и «Перечитать».
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
        # Заголовок ужимаем: в немецком он просит 490 px и в одиночку держал
        # минимальную ширину всей карточки выше бюджета страницы.
        head.addWidget(shrink(StrongBodyLabel(tr("cfg.card_title",
                                                 "Конфиг сервера (serverDZ.cfg)"))), 1)
        self.unsaved = CaptionLabel("")
        self.unsaved.setStyleSheet(f"color:{tokens.color('warning')};")
        head.addWidget(self.unsaved)
        head.addStretch(1)
        self.btn_reload = PushButton(FIF.SYNC, tr("cfg.reload", "Перечитать"))
        self.btn_reload.clicked.connect(self.reload)
        head.addWidget(self.btn_reload)
        self.btn_save = PushButton(FIF.SAVE, tr("common.save", "Сохранить"))
        self.btn_save.clicked.connect(self.save)
        head.addWidget(self.btn_save)
        box.addWidget(Rule())
        box.addLayout(head)

        # Какой файл правим — видно без наведения мыши: конфигов у человека
        # столько же, сколько пресетов, и правка не того файла обнаруживается
        # только на запуске.
        self.path_label = shrink(CaptionLabel(tr("cfg.no_file", "Конфиг не загружен")))
        box.addWidget(self.path_label)
        self.enc_label = shrink(CaptionLabel(""))
        self.enc_label.setStyleSheet(f"color:{tokens.color('warning')};")
        self.enc_label.setVisible(False)
        box.addWidget(self.enc_label)

        self.keys = CfgKeys()
        self.keys.changed.connect(self._touch)
        box.addWidget(self.keys)

        hint = shrink(CaptionLabel(tr(
            "cfg.hint2",
            "Снятая галка означает, что ключа в файле нет и сервер возьмёт своё "
            "умолчание. Комментарии и порядок строк сохраняются, файл пишется "
            "в UTF-8 без BOM.")))
        box.addWidget(hint)

    def _touch(self) -> None:
        self.unsaved.setText(tr("cfg.dirty", "Есть несохранённые изменения"))

    def set_path(self, path: Path | None) -> None:
        self._path = Path(path) if path else None
        self.reload()

    def reload(self) -> None:
        """Читает файл заново — и при смене пресета, и по кнопке.

        Кнопка нужна потому, что конфиг правят не только отсюда: редактор
        текста, другой инструмент, наш же ярлык. Без неё карточка показывала бы
        то, чего в файле уже нет, до самой смены пресета.
        """
        self.unsaved.setText("")
        self.enc_label.setVisible(False)
        self.cfg = None
        if not self._path or not self._path.is_file():
            self.path_label.setText(tr("cfg.no_file", "Конфиг не загружен"))
            self.keys.load({})
            self.setEnabled(False)
            return
        self.setEnabled(True)
        try:
            self.cfg = ServerCfg(self._path)
        except OSError as e:
            self.path_label.setText(str(e))
            self.keys.load({})
            return
        self.path_label.setText(str(self._path))
        if self.cfg.encoding != "utf-8":
            self.enc_label.setText(tr("cfg.bad_enc",
                                      "Кодировка {enc} — при сохранении станет UTF-8 без BOM",
                                      enc=self.cfg.encoding))
            self.enc_label.setVisible(True)
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
        self.enc_label.setVisible(False)
        InfoBar.success(title=tr("cfg.saved", "Конфиг сохранён в UTF-8 без BOM."), content="",
                        parent=self.window(), duration=3000,
                        position=InfoBarPosition.TOP_RIGHT)
