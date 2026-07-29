"""Диалог настроек pboProject: понятные галки/поля вместо сырой строки флагов CLI.

Разбирает и собирает settings.pack_flags — формат строки не меняется, так что
всё, что пользователь вписал вручную раньше (в т.ч. незнакомые нам флаги),
не теряется (см. «Другие флаги» внизу диалога).
"""
from __future__ import annotations

import re
import shlex

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout, QScrollArea, QWidget, QFileDialog,
)
from qfluentwidgets import (
    LineEdit, ComboBox, PushButton, PrimaryPushButton, ToolButton,
    BodyLabel, CaptionLabel, StrongBodyLabel, FluentIcon as FIF,
)

from core.i18n import tr
from ui.theme import ThemedDialog

_SECTION_MAIN = ["P", "N"]
_SECTION_FILES = ["B", "C", "D", "H", "T", "G", "Q"]
_SECTION_COMPRESS = ["Z", "O"]
_SECTION_ADVANCED: list[str] = []


class TriStateFlag(PushButton):
    """Переключатель опции pboProject на три положения.

    Пусто — опцию не передаём вовсе (pboProject возьмёт значение из своих
    настроек GUI), «+» — включить, «−» — выключить. Третье положение здесь не
    прихоть: у Mikero отсутствие ключа и ключ со знаком «минус» означают разное,
    и обычная галка это состояние выразить не может.

    Наружу выдаёт себя как ComboBox (currentData/setCurrentIndex) — остальной
    диалог собирает строку флагов через них и менять его не пришлось.
    """
    _ORDER = (None, True, False)
    _LOOK = {
        None:  ("",  "#888888"),
        True:  ("+", "#4caf50"),
        False: ("−", "#ff6b6b"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = None
        self.setFixedSize(38, 30)
        self.setToolTip(tr("pbo.tri_tip",
                           "Клик переключает: пусто — не передавать опцию, "
                           "«+» — включить, «−» — выключить."))
        self.clicked.connect(self._cycle)
        self._refresh()

    def _refresh(self) -> None:
        text, color = self._LOOK[self._value]
        self.setText(text)
        self.setStyleSheet(f"PushButton{{font-size:15pt;font-weight:700;color:{color};}}")

    def _cycle(self) -> None:
        self._value = self._ORDER[(self._ORDER.index(self._value) + 1) % 3]
        self._refresh()

    # --- совместимость с прежним ComboBox
    def currentData(self):
        return self._value

    def setCurrentIndex(self, index: int) -> None:
        self._value = {0: None, 1: True, 2: False}.get(index)
        self._refresh()


def _bool_meta() -> dict[str, tuple[str, str]]:
    """буква -> (лейбл, подсказка). Вызовы tr() с буквальными аргументами —
    иначе tools/extract_strings.py (статический разбор AST) их не найдёт
    и при перегенерации lang/ru.json эти ключи потеряются."""
    return {
        "P": (tr("pbo.p", "Без паузы (пакетный режим)"),
              tr("pbo.p_tip", "Обязательно для автоматической сборки — без этого pboProject "
                 "может открыть GUI и ждать участия пользователя, из-за чего сборка зависнет.")),
        "K": (tr("pbo.k", "Подписывать PBO"),
              tr("pbo.k_tip", "Создаёт .bisign рядом с pbo и кладёт публичный ключ в keys/. "
                 "Если ниже указан приватный ключ, подпись включается автоматически "
                 "независимо от этого переключателя.")),
        "N": (tr("pbo.n", "Подробный лог"),
              tr("pbo.n_tip", "Много дополнительной информации в выводе — полезно при поиске "
                 "причины ошибки, но заметно замедляет сборку.")),
        "B": (tr("pbo.b", "Бинаризовать sqm/cpp"),
              tr("pbo.b_tip", "Проверяет mission.sqm и config.cpp на ошибки через пробную бинаризацию.")),
        "C": (tr("pbo.c", "Полная пересборка (очищать temp)"),
              tr("pbo.c_tip", "«Все ставки сняты» — пересобирается вообще всё, включая то, что не менялось.")),
        "D": (tr("pbo.d", "Удалять png после конвертации"),
              tr("pbo.d_tip", "png, успешно сконвертированные в paa, удаляются из временной папки.")),
        "H": (tr("pbo.h", "Не конвертировать png (только DayZ)"),
              tr("pbo.h_tip", "DayZ иногда использует png напрямую — отключает попытку конвертации в paa.")),
        "T": (tr("pbo.t", "Обрезать (truncate) p3d (только DayZ)"), ""),
        "G": (tr("pbo.g", "Конвертировать wav/wss в ogg"),
              tr("pbo.g_tip", "Только для подписчиков соответствующего сервиса Mikero.")),
        "Q": (tr("pbo.q", "Удалять wav/wss после конвертации в ogg"), ""),
        "Z": (tr("pbo.z", "Сжимать pbo"),
              tr("pbo.z_tip", "Список исключений из сжатия — отдельным полем ниже.")),
        "O": (tr("pbo.o", "Обфускация"),
              tr("pbo.o_tip", "Защищает от просмотра исходников в hex-редакторе, но обфусцированный "
                 "pbo нельзя будет распаковать обратно.")),
    }


def _text_meta() -> dict[str, tuple[str, str, str, str]]:
    """ключ_виджета -> (буква_флага, лейбл, подсказка, тип: "file"|"text")."""
    return {
        "K_file": ("K", tr("pbo.k_file", "Приватный ключ (.biprivatekey)"),
                  tr("pbo.k_file_tip", "Нужен, если включена подпись PBO выше."), "file"),
        "Z_excl": ("Z", tr("pbo.z_excl", "Исключить из сжатия"),
                  tr("pbo.z_excl_tip", "Файлы/маски через запятую, которые не нужно сжимать "
                     "(например *.paa,*.ogg)."), "text"),
        "X_excl": ("X", tr("pbo.x_excl", "Исключить из PBO"),
                  tr("pbo.x_excl_tip", "Файлы/маски через запятую, которые вообще не попадут в pbo."), "text"),
        "A": ("A", tr("pbo.appid", "AppID (только платный DLC)"),
              tr("pbo.appid_tip", "Оставьте пустым, если это не платный DLC-контент."), "text"),
    }


def _quote_if_needed(val: str) -> str:
    """Оборачивает значение в кавычки, если в нём есть пробел — pboProject (как и
    core/packer.py) требует кавычки для значений с пробелами, иначе naive-разбор
    строки флагов на аргументы порвёт одно значение на несколько токенов."""
    return f'"{val}"' if " " in val else val


def _parse(flags: str, bool_letters: set[str],
          text_letters: set[str]) -> tuple[dict[str, bool], dict[str, str], list[str]]:
    """Разбирает строку флагов на (булевы флаги, флаги-значения по букве, непонятое).

    shlex (posix=False) — чтобы значения в кавычках с пробелами (пути, списки
    масок) разбирались как один токен, а не рвались по каждому пробелу.
    """
    bools: dict[str, bool] = {}
    texts: dict[str, str] = {}
    extra: list[str] = []
    try:
        tokens = shlex.split(flags, posix=True)
    except ValueError:
        tokens = flags.split()  # незакрытая кавычка и т.п. — не валим диалог
    for tok in tokens:
        # Ключи, которые задавать нельзя, и которые могли остаться в старых
        # сохранённых строках:
        #   S — pboProject не принимает его ни в каком виде (rc=1, пустой вывод);
        #   $ — разрешает собирать pbo без префикса, из-за него терялся $PBOPREFIX$;
        #   W — в разных версиях это либо «warnings are errors», либо рабочий
        #       диск; задавать опцию с неизвестным смыслом нельзя.
        if tok in ("-S", "+S", "-$", "+$", "-W", "+W"):
            continue
        m = re.match(r'^([+-])(\$|[A-Za-z])$', tok)
        if m and m.group(2).upper() in bool_letters:
            bools[m.group(2).upper()] = (m.group(1) == "+")
            continue
        m = re.match(r'^[+-]?([A-Za-z])=(.*)$', tok)
        if m and m.group(1).upper() in text_letters:
            texts[m.group(1).upper()] = m.group(2).strip('"')
            continue
        extra.append(tok)
    return bools, texts, extra


class PboProjectDialog(ThemedDialog):
    """Настройки CLI-флагов pboProject — с пояснениями, без сырой строки."""

    def __init__(self, pack_flags: str, clean_meta: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("pbo.title", "Настройки PboProject"))
        self.resize(560, 620)
        bool_meta = _bool_meta()
        text_meta = _text_meta()
        letter_by_key = {k: v[0] for k, v in text_meta.items()}
        bools, texts, extra = _parse(pack_flags, set(bool_meta), set(letter_by_key.values()))

        self._combos: dict[str, TriStateFlag] = {}
        self._texts: dict[str, LineEdit] = {}
        self._letter_by_key = letter_by_key

        outer = QVBoxLayout(self)
        hint = BodyLabel(tr("pbo.hint",
                            "Флаги командной строки pboProject. «Не указано» — использовать "
                            "то, что осталось настроено в самом pboProject (непредсказуемо "
                            "между запусками); отметьте явно, если важно конкретное поведение."))
        hint.setWordWrap(True)
        outer.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # без этого viewport остаётся системным белым в тёмной теме
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        inner = QWidget()
        inner.setObjectName("pboFlags")
        inner.setStyleSheet("QWidget#pboFlags{background:transparent;}")
        scroll.setWidget(inner)
        v = QVBoxLayout(inner)

        def bool_section(title: str, letters: list[str]) -> QFormLayout:
            v.addWidget(StrongBodyLabel(title))
            form = QFormLayout()
            form.setSpacing(8)
            for letter in letters:
                label, tip = bool_meta[letter]
                self._add_bool_row(form, letter, label, tip)
            v.addLayout(form)
            return form

        bool_section(tr("pbo.section_main", "Основное"), _SECTION_MAIN)
        bool_section(tr("pbo.section_files", "Обработка файлов"), _SECTION_FILES)

        form_compress = bool_section(tr("pbo.section_compress", "Сжатие и защита"), _SECTION_COMPRESS)
        for key in ("Z_excl", "X_excl"):
            letter, label, tip, kind = text_meta[key]
            self._add_text_row(form_compress, key, label, tip, kind, texts.get(letter, ""))

        v.addWidget(StrongBodyLabel(tr("pbo.section_signing", "Подпись")))
        form_sign = QFormLayout()
        form_sign.setSpacing(8)
        label, tip = bool_meta["K"]
        self._add_bool_row(form_sign, "K", label, tip)
        letter, label, tip, kind = text_meta["K_file"]
        self._add_text_row(form_sign, "K_file", label, tip, kind, texts.get(letter, ""))
        v.addLayout(form_sign)

        form_adv = bool_section(tr("pbo.section_advanced", "Прочее"), _SECTION_ADVANCED)
        letter, label, tip, kind = text_meta["A"]
        self._add_text_row(form_adv, "A", label, tip, kind, texts.get(letter, ""))

        v.addWidget(StrongBodyLabel(tr("pbo.section_misc", "Разное")))
        form_misc = QFormLayout()
        form_misc.setSpacing(8)
        self.clean_meta_combo = ComboBox()
        self.clean_meta_combo.addItems([tr("pbo.no", "Нет"), tr("pbo.yes", "Да")])
        self.clean_meta_combo.setCurrentIndex(1 if clean_meta else 0)
        clean_label = BodyLabel(tr("pbo.clean_meta", "Удалять *.meta в сорсах перед запаковкой"))
        clean_label.setToolTip(tr("pbo.clean_meta_tip",
                                  "*.meta — мусор от Workbench, мешает точному сравнению дат сорсов и pbo."))
        form_misc.addRow(clean_label, self.clean_meta_combo)
        v.addLayout(form_misc)

        self.extra_edit = LineEdit()
        if extra:
            v.addWidget(StrongBodyLabel(tr("pbo.section_extra", "Другие флаги")))
            extra_hint = CaptionLabel(tr("pbo.extra_hint",
                                        "Распознаны как есть из прежних настроек — добавляются "
                                        "в конец без изменений."))
            extra_hint.setWordWrap(True)
            v.addWidget(extra_hint)
            self.extra_edit.setText(" ".join(extra))
            v.addWidget(self.extra_edit)

        v.addStretch(1)
        outer.addWidget(scroll, 1)

        btns = QHBoxLayout()
        b_cancel = PushButton(tr("common.cancel", "Отмена"))
        b_cancel.clicked.connect(self.reject)
        b_ok = PrimaryPushButton(tr("common.save", "Сохранить"))
        b_ok.clicked.connect(self.accept)
        btns.addStretch(1)
        btns.addWidget(b_cancel)
        btns.addWidget(b_ok)
        outer.addLayout(btns)

        for letter, combo in self._combos.items():
            val = bools.get(letter)
            combo.setCurrentIndex({None: 0, True: 1, False: 2}[val])

    def _add_bool_row(self, form: QFormLayout, letter: str, label_text: str, tip: str) -> None:
        flag = TriStateFlag()
        row_label = BodyLabel(f"{label_text} ({letter})")
        if tip:
            row_label.setToolTip(tip)
            flag.setToolTip(f"{tip}\n\n{flag.toolTip()}")
        # переключатель слева, подпись справа — глаз идёт по колонке значков,
        # а не выискивает их в конце разных по длине строк
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(flag)
        row.addWidget(row_label, 1)
        form.addRow(row)
        self._combos[letter] = flag

    def _add_text_row(self, form: QFormLayout, key: str, label_text: str, tip: str,
                      kind: str, value: str) -> None:
        edit = LineEdit()
        edit.setText(value)
        if tip:
            edit.setToolTip(tip)
        row_label = BodyLabel(label_text)
        if tip:
            row_label.setToolTip(tip)
        if kind == "file":
            row = QHBoxLayout()
            btn = ToolButton(FIF.FOLDER)

            def browse():
                p, _ = QFileDialog.getOpenFileName(
                    self, tr("pbo.pick_key", "Файл приватного ключа"), edit.text(),
                    "biprivatekey (*.biprivatekey);;" + tr("common.all_files", "Все файлы") + " (*.*)")
                if p:
                    edit.setText(p)

            btn.clicked.connect(browse)
            row.addWidget(edit, 1)
            row.addWidget(btn)
            form.addRow(row_label, row)
        else:
            form.addRow(row_label, edit)
        self._texts[key] = edit

    # виджеты, чьё значение — список масок через запятую (пробелы в них не
    # нужны и лишь ломают разбор строки флагов на аргументы, см. _quote_if_needed)
    _COMMA_LIST_KEYS = ("Z_excl", "X_excl")

    def result_flags(self) -> str:
        tokens: list[str] = []
        for letter, combo in self._combos.items():
            val = combo.currentData()
            if val is True:
                tokens.append(f"+{letter}")
            elif val is False:
                tokens.append(f"-{letter}")
        key_val = self._texts["K_file"].text().strip()
        if key_val:
            # путь к ключу подразумевает включённую подпись — не дублируем
            # состояние отдельным +K/-K
            tokens = [t for t in tokens if t not in ("+K", "-K")]
            tokens.append(f"+K={_quote_if_needed(key_val)}")
        for key, edit in self._texts.items():
            if key == "K_file":
                continue
            letter = self._letter_by_key[key]
            val = edit.text().strip()
            if not val:
                continue
            if key in self._COMMA_LIST_KEYS:
                # пробелы вокруг запятых — частая опечатка при ручном вводе списка;
                # без очистки .split() в core/packer.py рвёт один параметр на
                # несколько «аргументов», и pboProject тут же падает без вывода
                val = ",".join(p.strip() for p in val.split(",") if p.strip())
            tokens.append(f"-{letter}={_quote_if_needed(val)}")
        extra_val = self.extra_edit.text().strip()
        if extra_val:
            tokens.extend(extra_val.split())
        return " ".join(tokens)

    def result_clean_meta(self) -> bool:
        return self.clean_meta_combo.currentIndex() == 1
