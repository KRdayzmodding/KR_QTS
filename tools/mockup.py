"""Прототип интерфейса: страницы можно потыкать, ничего не запуская.

Отдельная программа, а не режим приложения. Смысл — согласовать вид и
поведение до того, как переделывать рабочий код: кнопки здесь ничего не
делают, данные подставные, настройки на диске не трогаются вовсе.

Почему на Qt, а не картинкой или веб-макетом: макет в другой технологии врёт.
Метрики контролов, шрифт, тёмная тема, поведение при масштабе 150% — всё это
видно только на тех же виджетах, на которых потом будет собрано приложение.
Здесь та же qfluentwidgets и те же токены из ui/tokens.py, поэтому увиденное
переезжает в программу почти без правок.

Запуск:

    python tools/mockup.py

Сверху — служебная полоса самого прототипа (тема и состояние). В приложении её
не будет: она нужна, чтобы посмотреть каждый экран во всех состояниях, не
поднимая настоящий сервер.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt, QEasingCurve, QPropertyAnimation, QPoint
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QGridLayout,
    QApplication, QHBoxLayout, QVBoxLayout, QWidget, QPlainTextEdit, QFrame,
    QSizePolicy,
)
from qfluentwidgets import (
    HyperlinkLabel, SmoothScrollArea, FlowLayout, RoundMenu, Action, MessageBoxBase,
    CheckBox, LineEdit, SearchLineEdit, ToolButton, TogglePushButton, qconfig,
    BodyLabel, CaptionLabel, CardWidget, ComboBox, FluentIcon as FIF,
    FluentWindow, IconWidget, NavigationItemPosition,
    PrimaryPushButton, PushButton, SegmentedWidget, StrongBodyLabel, SubtitleLabel,
    SwitchButton, TitleLabel, Theme, TransparentToolButton, setTheme, setThemeColor,
)

from ui import tokens

# Состояния, в которых нужно уметь смотреть каждый экран.
ST_IDLE, ST_STARTING, ST_RUNNING, ST_FAILED = "idle", "starting", "running", "failed"
ST_MIXED = "mixed"          # сервер жив, клиент упал — стороны в разных состояниях
ST_EMPTY = "empty"          # пресетов ещё нет — экран не про запуск, а про создание
STATES = {
    ST_EMPTY: "Пресетов ещё нет",
    ST_IDLE: "Ничего не запущено",
    ST_STARTING: "Запускается",
    ST_RUNNING: "Сервер и клиент работают",
    ST_MIXED: "Клиент упал",
    ST_FAILED: "Запуск сорван",
}

# Состояние каждой стороны отдельно: из него берутся и индикаторы, и то, что
# предлагает большая кнопка.
SIDES = {
    ST_EMPTY: ("off", "off"),
    ST_IDLE: ("off", "off"),
    ST_STARTING: ("wait", "wait"),
    ST_RUNNING: ("run", "run"),
    ST_MIXED: ("run", "dead"),
    ST_FAILED: ("dead", "off"),
}

PRESET = "test_cher"
MAP_NAME = "Chernarus"
PORT = 2302

FAKE_LOG = {
    ST_STARTING: [
        ("Запаковка (2): KR_Furniture, kr_proxy", "info"),
        ("kr_furniture_cfg.pbo .......... [ok] (812 ms)", "success"),
        ("KR_FURNITURE.pbo .............. [packing] ..", "warning"),
    ],
    ST_RUNNING: [
        ("Запаковка (2): KR_Furniture, kr_proxy", "info"),
        ("kr_furniture_cfg.pbo .......... [ok] (812 ms)", "success"),
        ("KR_FURNITURE.pbo .............. [ok] (5 140 ms)", "success"),
        ("Сервер: запущен, PID 24116", "success"),
        ("Скриптовая память: 3_Game 41% · 4_World 63% · 5_Mission 22%", "info"),
        ("Клиент: запущен через DayZ_BE.exe, PID 24980", "success"),
    ],
    ST_MIXED: [
        ("Сервер: запущен, PID 24116", "success"),
        ("Клиент: запущен через DayZ_BE.exe, PID 24980", "success"),
        ("Клиент завершился (код 1). Сервер продолжает работать.", "warning"),
    ],
    ST_FAILED: [
        ("Сервер: запущен, PID 24116", "success"),
        ("Запуск сорван: 4_World не скомпилировался", "error"),
        ("  scripts/4_World/kr_core.c:118 — undefined variable 'm_Owner'", "error"),
    ],
}

# Что показывают вкладки журнала, кроме «Запуска».
TAB_LOG = {
    "server": [
        ("12:04:11 [SERVER] Mission read: test_cher.chernarusplus", "info"),
        ("12:04:19 [SERVER] Connecting to database", "info"),
        ("12:04:31 [SERVER] Player \"Kramtsov\" connected (76561198…)", "success"),
        ("12:05:02 [ERROR] Cannot find object 'kr_shelf_02'", "error"),
    ],
    "client": [
        ("12:04:52 [CLIENT] Loading mission", "info"),
        ("12:04:58 [CLIENT] Connected to 127.0.0.1:2302", "success"),
        ("12:05:02 [WARNING] Texture not found: kr_shelf_co.paa", "warning"),
    ],
    "pack": [
        ("kr_furniture_cfg.pbo .......... [ok] (812 ms)", "success"),
        ("KR_FURNITURE.pbo .............. [ok] (5 140 ms) [W: 2]", "warning"),
        ("kr_proxy.pbo .................. [ok] (2 380 ms)", "success"),
    ],
}

PATH_SAMPLE = ('…' + chr(92) + 'profiles' + chr(92) + 'test_cher'
               + chr(92) + 'script_2026-09-05.log')

CMDLINE = ("DayZDiag_x64.exe -server -config=configs/test_cher.cfg "
           "-mission=mpmissions/test_cher.chernarusplus -profiles=profiles/test_cher "
           "-port=2302 -mod=@CF;@KR_Furniture -filePatching -scriptDebug=true")

def shrink(label):
    """Разрешает подписи ужиматься.

    Метка с переносом всё равно требует ширину всей строки целиком, пока ей не
    сказать, что её желаемая ширина никого не интересует. Из-за этого одна
    строка «Запаковывать изменённые моды перед запуском» требовала 602 px и
    растягивала окно до полутора тысяч.
    """
    label.setWordWrap(True)
    label.setMinimumWidth(1)
    # Preferred, а не Ignored: Ignored означает «желаемая ширина неинтересна», и
    # раскладка ужимает метку до минимума — текст встаёт столбиком по слову в
    # строке. Нужно другое: желаемую ширину учитывать, а требовать её — нет.
    label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    return label


class Section(CardWidget):
    """Сворачиваемый раздел: шапка с итогом, под ней строки.

    Своя, а не ExpandGroupSettingCard из библиотеки: та считает высоту
    содержимого по своим меркам — её строки одинаковой высоты, а у нас в строке
    два-три ряда текста. Из-за расхождения под содержимым оставалась пустая
    полоса и в раскрытом, и в свёрнутом виде.

    Свёрнутая шапка обязана показывать итог: «Базовый · модов: 3», «Выключена —
    правки не попадут в игру». Иначе сворачивание прячет состояние, и человек
    запускает сервер, не зная, что запаковка выключена.
    """

    def __init__(self, icon, title: str, rows: list[QWidget], parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        self.head = QWidget(self)
        self.head.setCursor(Qt.CursorShape.PointingHandCursor)
        hrow = QHBoxLayout(self.head)
        hrow.setContentsMargins(tokens.SPACE_M, tokens.SPACE_S,
                                tokens.SPACE_M, tokens.SPACE_S)
        hrow.setSpacing(tokens.SPACE_S)
        ic = IconWidget(icon, self.head)
        ic.setFixedSize(18, 18)
        hrow.addWidget(ic)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(StrongBodyLabel(title))
        self.summary = shrink(CaptionLabel(""))
        text.addWidget(self.summary)
        hrow.addLayout(text, 1)
        self.chevron = TransparentToolButton(FIF.CHEVRON_DOWN_MED)
        self.chevron.setFixedSize(24, 24)
        self.chevron.clicked.connect(self.toggle)
        hrow.addWidget(self.chevron)
        col.addWidget(self.head)
        self.head.mousePressEvent = lambda _e: self.toggle()

        self.body = QWidget(self)
        brow = QVBoxLayout(self.body)
        brow.setContentsMargins(tokens.SPACE_M, 0, tokens.SPACE_M, tokens.SPACE_S)
        brow.setSpacing(tokens.SPACE_XS)
        for r in rows:
            brow.addWidget(r)
        col.addWidget(self.body)

        self._open = True
        self._ani = QPropertyAnimation(self.body, b"maximumHeight", self)
        self._ani.setDuration(180)                     # шкала движения из раздела 10
        self._ani.setEasingCurve(QEasingCurve.Type.OutQuad)
        # Подключаемся один раз: перецепление обработчика на каждый щелчок
        # заставляло Qt ругаться на отключение несуществующей связи.
        self._ani.finished.connect(self._after)

    def _after(self) -> None:
        # свёрнутое тело прячем совсем, иначе от него остаётся полоска в пиксель
        if not self._open:
            self.body.setVisible(False)

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)

    def is_open(self) -> bool:
        return self._open

    def set_open(self, open_: bool) -> None:
        if open_ != self._open:
            self.toggle()

    def toggle(self) -> None:
        self._open = not self._open
        full = self.body.sizeHint().height()
        self.chevron.setIcon(FIF.CHEVRON_DOWN_MED if self._open else FIF.CHEVRON_RIGHT)
        if self._open:
            self.body.setVisible(True)
        self._ani.stop()
        self._ani.setStartValue(full if not self._open else 0)
        self._ani.setEndValue(full if self._open else 0)
        self._ani.start()


def rows_card(icon, title: str, summary: str, rows: list[QWidget]) -> Section:
    card = Section(icon, title, rows)
    card.set_summary(summary)
    return card


CONTROL_SLOT = 190      # ширина места под контрол: колонки выравниваются по нему


def slot(control) -> QWidget:
    """Кладёт контрол в слот постоянной ширины, прижимая вправо.

    Без этого поле на 80 px и поле на 170 px дают разные колонки, и две сетки
    в одной карточке читаются как две разные таблицы.
    """
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addStretch(1)
    lay.addWidget(control)
    # минимум, а не потолок: узкие контролы выстраиваются по одной вертикали,
    # широкие (поле ввода, список) не обрезаются
    box.setMinimumWidth(CONTROL_SLOT)
    return box


def setting_row(title: str, desc: str, control) -> QWidget:
    """Строка настройки: название и пояснение слева, контрол справа.

    Тот самый вид, к которому мы идём вместо «метка: поле»: пояснение видно
    без наведения мыши, а ширину задаёт контрол, а не длина текста.
    """
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, tokens.SPACE_XXS, 0, tokens.SPACE_XXS)
    lay.setSpacing(tokens.SPACE_M)
    text = QVBoxLayout()
    text.setSpacing(0)
    text.addWidget(shrink(StrongBodyLabel(title)))
    if desc:
        text.addWidget(shrink(CaptionLabel(desc)))
    holder = QWidget()
    holder.setLayout(text)
    holder.setMinimumWidth(220)      # ниже этого текст читать невозможно
    lay.addWidget(holder, 1)
    lay.addWidget(slot(control), 0, Qt.AlignmentFlag.AlignVCenter)
    return row


class StateBadge(QFrame):
    """Индикатор состояния: кружок цвета роли со значком того, что происходит.

    Значок показывает состояние, а не действие: ⏹ — остановлено, ▶ — работает,
    ⟳ — переходное, ✕ — сорвано. Это принципиально: ▶ в значении «нажми, чтобы
    запустить» превращает индикатор в мнимую кнопку, в которую тыкают. Здесь
    ровно наоборот — ▶ горит, когда сервер уже идёт.

    Подложка кружка сделана заливкой того же цвета в четверть силы: получается
    лампочка, а не кнопка — нет ни рамки, ни отклика на наведение.
    """

    LOOK = {
        ST_IDLE: (FIF.PAUSE_BOLD, "muted"),
        ST_STARTING: (FIF.SYNC, "warning"),
        ST_RUNNING: (FIF.PLAY_SOLID, "success"),
        ST_MIXED: (FIF.CANCEL_MEDIUM, "warning"),
        ST_FAILED: (FIF.CANCEL_MEDIUM, "error"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.icon = IconWidget(self)
        self.icon.setFixedSize(16, 16)
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignCenter)
        self.set_state(ST_IDLE)

    def set_state(self, state: str) -> None:
        icon, role = self.LOOK.get(state, self.LOOK[ST_IDLE])
        color = tokens.color(role)
        self.icon.setIcon(icon.icon(color=QColor(color)))
        self.setStyleSheet(f"StateBadge{{background:{tokens.tint(role)};"
                           f"border-radius:17px;}}")


class StatusDot(QWidget):
    """Кружок состояния с подписью. Цвет берётся из ролей, а не задаётся здесь."""

    ROLES = {"run": "success", "wait": "warning", "dead": "error", "off": "muted"}
    WORDS = {"run": "работает", "wait": "запускается", "dead": "упал", "off": "не запущен"}

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_XXS)
        self.dot = QFrame(self)
        self.dot.setFixedSize(10, 10)
        # подпись индикатора короткая — переносить её незачем, иначе
        # «Сервер: не запущен» ломается на две строки при первой же тесноте
        self.text = CaptionLabel("")
        self.text.setMinimumWidth(1)
        # Кнопка у стороны появляется не всегда, а только когда у человека
        # возникает второе намерение, которое большая кнопка выразить не может:
        # клиент упал, но закончить он хочет не перезапуском, а остановкой
        # сервера. Клиент поднялся — кнопка уходит.
        self.act = PushButton(FIF.PAUSE_BOLD, "Остановить")
        self.act.setMinimumWidth(1)
        self.act.hide()
        row.addWidget(self.dot)
        row.addWidget(self.text)
        row.addWidget(self.act)
        self.set_state("off")

    def set_state(self, state: str) -> None:
        color = tokens.color(self.ROLES.get(state, "muted"))
        self.dot.setStyleSheet(f"background:{color};border-radius:5px;")
        self.text.setText(f"{self.name}: {self.WORDS.get(state, '')}")

    def offer_stop(self, on: bool) -> None:
        """Показать у стороны кнопку остановки. Вне описанного случая — скрыта."""
        self.act.setToolTip(f"Остановить {self.name.lower()}")
        self.act.setVisible(on)


class Hero(CardWidget):
    """Карточка состояния: то, ради чего человек открывает программу.

    Сейчас эта информация набрана подписью в углу строки с галками. Здесь —
    крупно и рядом с действием: состояние, метрики и одна кнопка, которая
    называет то, что сделает.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(tokens.SPACE_L, tokens.SPACE_M,
                               tokens.SPACE_L, tokens.SPACE_M)
        box.setSpacing(tokens.SPACE_S)

        top = QHBoxLayout()
        top.setSpacing(tokens.SPACE_S)
        self.badge = StateBadge(self)
        head = QVBoxLayout()
        head.setSpacing(2)
        self.state = shrink(SubtitleLabel(STATES[ST_IDLE]))
        self.sub = shrink(CaptionLabel(""))
        head.addWidget(self.state)
        head.addWidget(self.sub)
        top.addWidget(self.badge)
        top.addLayout(head, 1)

        badges = QHBoxLayout()
        badges.setSpacing(tokens.SPACE_M)
        self.dot_server = StatusDot("Сервер")
        self.dot_client = StatusDot("Клиент")
        badges.addWidget(self.dot_server)
        badges.addWidget(self.dot_client)
        top.addLayout(badges)
        box.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(tokens.SPACE_XS)
        # Выбор состава — модификатор кнопки, а не отдельная настройка: стоит
        # слева от неё, читается одной фразой «сервер и клиент — запустить».
        # Порядок частей — как читаем: сначала по одному, потом вместе.
        self.sides = SegmentedWidget()
        for key, text in (("server", "Сервер"), ("client", "Клиент"),
                          ("both", "Сервер и клиент")):
            # _checked первым: clicked у кнопки передаёт своё состояние, и без
            # этой заглушки булево значение занимает место ключа
            self.sides.addItem(routeKey=key, text=text,
                               onClick=lambda _checked=False, k=key: self.sides_changed(k))
        self.sides.setCurrentItem("both")
        row.addWidget(self.sides)
        row.addSpacing(tokens.SPACE_S)
        self.btn = PrimaryPushButton(FIF.PLAY, "Запустить сервер и клиент")
        self.btn.setMinimumHeight(40)
        # минимальная ширина Fluent-кнопки считается по тексту: «Запаковать
        # сейчас» требует 288 px, и несколько таких кнопок в ряд растягивают
        # окно вдвое. Ширину задаёт раскладка, а не длина надписи.
        self.btn.setMinimumWidth(1)
        self.sides_changed = lambda _k: None      # подменяется страницей
        # Кнопки логов здесь нет: логи живут вкладками журнала на этом же
        # экране, а полный режим открывается «Подробно» рядом с ними. Кнопка
        # делала бы работу вкладки, занимая место у главного действия.
        row.addWidget(self.btn, 1)
        box.addLayout(row)

    def apply(self, state: str, sides: str) -> None:
        what = {"both": "сервер и клиент", "server": "сервер", "client": "клиент"}[sides]
        self.state.setText(STATES[state])
        self.badge.set_state(state)
        text = {
            ST_IDLE: "Готов к запуску · прошлый запуск 12 минут назад",
            ST_STARTING: "Запаковка модов, затем старт сервера…",
            ST_RUNNING: "Аптайм 12 мин · память 3,1 ГБ · игроков 1",
            ST_MIXED: "Сервер работает 12 мин · клиент завершился, сервер не тронут",
            ST_FAILED: "Скрипты не скомпилировались — подробности в журнале",
        }[state]
        self.sub.setText(text)
        # Кнопка приводит систему к выбранному составу: если часть уже работает,
        # предлагает недостающее, а не «всё заново».
        self.btn.setText({
            ST_IDLE: f"Запустить {what}",
            ST_STARTING: "Отменить запуск",
            ST_RUNNING: f"Остановить {what}",
            ST_MIXED: "Запустить клиент",
            ST_FAILED: f"Запустить {what} заново",
        }[state])
        self.btn.setIcon(FIF.PAUSE if state in (ST_STARTING, ST_RUNNING) else FIF.PLAY)
        srv, cli = SIDES.get(state, ("off", "off"))
        self.dot_server.set_state(srv)
        self.dot_client.set_state(cli)
        # Сервер работает, а клиент нет: большая кнопка зовёт поднять клиент,
        # значит второе намерение — закончить — остаётся без кнопки. Её и даём.
        # У клиента такой кнопки нет: упал сервер — это гарантированный
        # перезапуск, второго намерения там не бывает.
        self.dot_server.offer_stop(srv == "run" and cli in ("dead", "off")
                                   and state != ST_IDLE)
        self.dot_client.offer_stop(False)


class LaunchPage(QWidget):
    """Страница «Запуск» в предлагаемом виде."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("launchMock")
        # Содержимое живёт в прокрутке: развёрнутые карточки не должны распирать
        # окно так, что его больше нельзя ужать. Без этого окно требовало 851 px
        # по высоте — больше, чем рабочая область ноутбука 1366×768.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = SmoothScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(SmoothScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}"
                             " QWidget#launchInner{background:transparent;}")
        inner = QWidget()
        inner.setObjectName("launchInner")
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        col = QVBoxLayout(inner)
        col.setContentsMargins(tokens.SPACE_L, tokens.SPACE_L,
                               tokens.SPACE_L, tokens.SPACE_L)
        col.setSpacing(tokens.SPACE_XS)

        col.addWidget(TitleLabel("Запуск"))

        self.hero = Hero(self)
        col.addWidget(self.hero)

        self.mod_set = ComboBox()
        self.mod_set.addItems(list(MOD_SETS))
        self.mod_set.setFixedWidth(200)
        self.mod_set.currentTextChanged.connect(self._mod_set_changed)
        # Ссылка здесь была чужой идиомой: в десктопном окне действие — это
        # кнопка. Строка устроена как все остальные: слева предмет и его
        # состояние, справа то, чем на него влияют.
        b_mods = PushButton(FIF.EDIT, "Изменить")
        b_mods.setMinimumWidth(1)
        b_mods.clicked.connect(lambda: ModsDialog(self.window()).exec())
        self.mods_line = shrink(CaptionLabel(""))
        self.mods_row = setting_row("Подключённые моды", "", b_mods)
        # подпись строки — сам список модов, он же меняется вместе с набором
        self.mods_row.layout().itemAt(0).widget().layout().addWidget(self.mods_line)
        mods_rows = [
            setting_row("Набор модов",
                        "Готовый список, общий для всех пресетов. Изменишь состав "
                        "вручную — набор станет «Свой список».", self.mod_set),
            self.mods_row,
        ]
        self.mods_card = rows_card(FIF.APPLICATION, "Моды", "", mods_rows)
        col.addWidget(self.mods_card)
        self._mod_set_changed("Базовый")

        self.sw_pack = SwitchButton()
        self.sw_pack.setOnText("")
        self.sw_pack.setOffText("")
        self.sw_pack.setChecked(True)
        # Два варианта — это кнопки, а не список: выбор виден целиком, без
        # раскрытия. Выпадающий список остаётся там, где вариантов много или
        # они прибавляются: пресеты, карты, наборы модов.
        self.mode = SegmentedWidget()
        for key, text in (("normal", "Обычная"), ("full", "Полная")):
            self.mode.addItem(routeKey=key, text=text,
                              onClick=lambda _checked=False: self._pack_summary())
        self.mode.setCurrentItem("normal")
        self.pack_card = rows_card(FIF.ZIP_FOLDER, "Запаковка модов", "", [
            # Название настройки — то, что она включает, а не когда это
            # происходит. Пояснение — про результат для человека: его правки
            # окажутся в игре, а не про то, какие файлы с чем сравниваются.
            setting_row("Запаковывать при запуске",
                        "Мод, у которого сорсы новее его PBO, запакуется перед "
                        "стартом — правки попадут в игру.",
                        self.sw_pack),
            setting_row("Способ",
                        "Полная чистит temp и пересобирает всё, включая "
                        "неизменившееся, — дольше, но надёжнее.", self.mode),
        ])
        col.addWidget(self.pack_card)

        # Одна плашка на всё, что настраивают редко: параметры запуска и
        # serverDZ.cfg. Свёрнута по умолчанию, в шапке — итог. Пять отдельных
        # разделов здесь занимали бы 252 px и уводили журнал за край экрана.
        self.preset = PresetSections()
        divider = subheading("Конфиг сервера (serverDZ.cfg)", line=True)
        self.setup_card = rows_card(
            FIF.SETTING, "Настройки сервера",
            "параметры запуска и serverDZ.cfg",
            list(self.preset.params_rows) + [divider] + list(self.preset.cfg_rows))
        self.setup_card.set_open(False)
        col.addWidget(self.setup_card)
        self.sw_pack.checkedChanged.connect(lambda _v: self._pack_summary())
        self._pack_summary()
        # Ручной запаковки здесь нет намеренно: это действие, а не настройка,
        # и его место там, где видно объекты — на экране модов. Иначе к четырём
        # нынешним входам в запаковку добавился бы пятый.

        # Итоговая командная строка — то, чего нам не хватало: видно, что
        # именно уйдёт в exe, и все переключатели выше объясняются сами.
        self.cmd_row_w = QWidget()
        cmd_row = QHBoxLayout(self.cmd_row_w)
        cmd_row.setSpacing(tokens.SPACE_XXS)
        self.b_cmd = TransparentToolButton(FIF.CHEVRON_RIGHT)
        self.b_cmd.setFixedSize(22, 22)
        self.b_cmd.clicked.connect(self._toggle_cmd)
        cmd_row.addWidget(self.b_cmd)
        cmd_row.addWidget(StrongBodyLabel("Итоговая командная строка"))
        cmd_row.setContentsMargins(0, 0, 0, 0)
        cmd_row.addStretch(1)
        col.addWidget(self.cmd_row_w)
        self.cmd = QPlainTextEdit(CMDLINE)
        self.cmd.setReadOnly(True)
        self.cmd.setFixedHeight(64)
        self.cmd.setFont(tokens.mono_font(9))
        tokens.apply_console(self.cmd)
        self.cmd.hide()
        col.addWidget(self.cmd)

        # Журнал и его пустое состояние — сейчас на этом месте просто пустой
        # прямоугольник, который ничего не сообщает.
        # Логи — вкладками в одном месте, а не четырьмя отдельными окнами.
        # Сейчас «Логи клиента/сервера» открывает сразу два окна, «Логи
        # запаковки» — ещё два.
        self.j_head = QWidget()
        jrow = QHBoxLayout(self.j_head)
        jrow.setContentsMargins(0, tokens.SPACE_XS, 0, 0)
        jrow.setSpacing(tokens.SPACE_M)
        jrow.addWidget(StrongBodyLabel("Журнал"))
        self.tabs = SegmentedWidget(self)
        for key, name in (("launch", "Запуск"), ("server", "Сервер"),
                          ("client", "Клиент"), ("pack", "Запаковка")):
            self.tabs.addItem(routeKey=key, text=name,
                              onClick=lambda _c=False, k=key: self._tab_changed(k))
        self.tabs.setCurrentItem("launch")
        jrow.addWidget(self.tabs)
        jrow.addStretch(1)
        # Вкладка — быстрый взгляд. Полный инструмент (виды файлов, поиск,
        # «только совпадения», поверх всех окон, очистка) открывается отдельным
        # окном. Оно же отвечает на «нужно видеть сервер и клиент разом»:
        # открепил обе вкладки — вот они рядом.
        self.b_detail = PushButton(FIF.CHEVRON_RIGHT_MED, "Подробно")
        self.b_detail.setToolTip("Открыть эту вкладку отдельным окном: поиск по "
                                 "логам, выбор файлов, поверх всех окон")
        self.b_detail.setMinimumWidth(1)
        self.b_detail.clicked.connect(self._detach)
        jrow.addWidget(self.b_detail)
        col.addWidget(self.j_head)
        self.empty = QFrame(self)
        self.empty.setMinimumHeight(120)
        ebox = QVBoxLayout(self.empty)
        ebox.setSpacing(tokens.SPACE_XXS)
        ebox.addStretch(1)
        ic = IconWidget(FIF.HISTORY, self.empty)
        ic.setFixedSize(32, 32)
        ebox.addWidget(ic, 0, Qt.AlignmentFlag.AlignHCenter)
        # setAlignment центрирует текст внутри метки, а саму метку по строке
        # расставляет раскладка — поэтому выравнивание нужно в обоих местах,
        # иначе ограниченная по ширине подпись прижимается влево.
        t = StrongBodyLabel("Пока ничего не запускалось")
        t.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        ebox.addWidget(t, 0, Qt.AlignmentFlag.AlignHCenter)
        h = shrink(CaptionLabel("Журнал запуска появится здесь: запаковка, старт "
                                "сервера, скриптовая память и причина срыва."))
        h.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        h.setFixedWidth(460)
        ebox.addWidget(h, 0, Qt.AlignmentFlag.AlignHCenter)
        ebox.addStretch(1)
        col.addWidget(self.empty, 1)

        # Пресетов ещё нет: экран не про запуск, а про создание. Всё остальное
        # прячется, чтобы не предлагать действия над тем, чего не существует.
        self.no_presets = QFrame(self)
        npb = QVBoxLayout(self.no_presets)
        npb.addStretch(1)
        np_icon = IconWidget(FIF.ADD_TO, self.no_presets)
        np_icon.setFixedSize(36, 36)
        npb.addWidget(np_icon, 0, Qt.AlignmentFlag.AlignHCenter)
        np_t = StrongBodyLabel("Пресетов ещё нет")
        np_t.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        npb.addWidget(np_t, 0, Qt.AlignmentFlag.AlignHCenter)
        np_h = shrink(CaptionLabel("Пресет — это набор настроек одного тестового "
                                   "сервера: карта, моды, порт, автоматика. "
                                   "Создание займёт три шага."))
        np_h.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        np_h.setMaximumWidth(460)
        npb.addWidget(np_h, 0, Qt.AlignmentFlag.AlignHCenter)
        npb.addSpacing(tokens.SPACE_S)
        np_btn = PrimaryPushButton(FIF.ADD, "Создать пресет")
        np_btn.setMinimumWidth(1)
        np_btn.clicked.connect(lambda: NewPresetDialog(parent=self.window()).exec())
        npb.addWidget(np_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        npb.addStretch(1)
        self.no_presets.hide()
        col.addWidget(self.no_presets, 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(120)
        self.log.setFont(tokens.mono_font())
        tokens.apply_console(self.log)
        self.log.hide()
        col.addWidget(self.log, 1)

        self._sides = "both"
        self._was_running = False
        # В простое нужны настройки. «Моды» раскрыты — состав смотрят перед
        # каждым запуском; «Запаковка» свёрнута — её задают один раз, а итог
        # виден в шапке. При запуске сворачивается всё: тогда нужен журнал.
        self._pre_open = [True, False, False]
        self.pack_card.set_open(False)
        self.hero.sides_changed = self._sides_changed
        self.set_state(ST_IDLE)

    # ------------------------------------------------------------- поведение

    def _detach(self) -> None:
        """Подробная работа с логами — сразу сервер и клиент.

        Одного окна мало: в разборе почти всегда нужны обе стороны — что сказал
        сервер и что увидел клиент в ту же секунду. Быстрый взгляд на одну
        сторону закрывают вкладки на главном экране.
        """
        from PySide6.QtWidgets import QApplication as _App
        self._detached = getattr(self, "_detached", [])
        wins = [LogWindowMock("server", self), LogWindowMock("client", self)]
        screen = _App.primaryScreen().availableGeometry()
        w, h, margin = wins[0].width(), wins[0].height(), 24
        side_by_side = screen.width() >= w * 2 + margin * 3
        for i, win in enumerate(wins):
            if side_by_side:
                win.move(screen.left() + margin + i * (w + margin), screen.top() + margin)
            else:
                win.move(screen.left() + margin, screen.top() + margin + i * (h + margin))
            win.show()
            self._detached.append(win)   # держим ссылки, иначе окна соберёт GC

    def _open_tab(self, key: str) -> None:
        self.tabs.setCurrentItem(key)
        self._tab_changed(key)

    def _tab_changed(self, key: str) -> None:
        """Переключение вкладки журнала. В прототипе тексты подставные."""
        self._tab = key
        self.set_state(self._state)

    def _mod_set_changed(self, name: str) -> None:
        self.mods_line.setText(MOD_SETS.get(name, ""))
        n = len(MOD_SETS.get(name, "").split(",")) if name != "Свой список" else 12
        self.mods_card.set_summary(f"{name} · модов: {n}")

    def _pack_summary(self) -> None:
        on = self.sw_pack.isChecked()
        mode = "полная" if self.mode.currentRouteKey() == "full" else "обычная"
        self.pack_card.set_summary(
            f"При запуске · {mode}" if on else "Выключена — правки не попадут в игру")

    def _toggle_cmd(self) -> None:
        show = not self.cmd.isVisible()
        self.cmd.setVisible(show)
        self.b_cmd.setIcon(FIF.CHEVRON_DOWN_MED if show else FIF.CHEVRON_RIGHT)

    def _sides_changed(self, key: str) -> None:
        self._sides = key
        self.hero.apply(self._state, key)

    # Пока сервер работает, настройки запуска не нужны, а журнал нужен. Сворачиваем
    # их на время работы и возвращаем как было по остановке: если человек сам
    # свернул карточку до запуска, его выбор не должен потеряться.
    RUN_STATES = (ST_STARTING, ST_RUNNING, ST_MIXED)

    def set_state(self, state: str) -> None:
        self._state = state
        empty = state == ST_EMPTY
        self.no_presets.setVisible(empty)
        for w in (self.hero, self.mods_card, self.pack_card, self.setup_card,
                  self.cmd_row_w, self.j_head):
            w.setVisible(not empty)
        if empty:
            self.log.hide()
            self.empty.hide()
            self.cmd.hide()
            return
        running = state in self.RUN_STATES
        cards = [self.mods_card, self.pack_card, self.setup_card]
        if running and not self._was_running:
            self._pre_open = [c.is_open() for c in cards]
            for c in cards:
                c.set_open(False)
        elif not running and self._was_running:
            for c, was in zip(cards, self._pre_open):
                c.set_open(was)
        self._was_running = running
        self.hero.apply(state, self._sides)
        lines = (FAKE_LOG.get(state, []) if getattr(self, "_tab", "launch") == "launch"
                 else TAB_LOG.get(self._tab, []))
        self.log.clear()
        for text, level in lines:
            color = tokens.level_colors().get(level, tokens.color("console_fg"))
            self.log.appendHtml(f'<span style="color:{color};">{text}</span>')
        self.log.setVisible(bool(lines))
        self.empty.setVisible(not lines)


# Моды для окна состава: имя, подключён ли, серверный ли. Тип задаётся прямо
# здесь — сейчас за ним приходится уходить на другой экран и возвращаться.
FAKE_MODS = [
    # имя, подключён, серверный, тег, флаг (название, цвет-роль)
    ("@CF", True, False, "Framework", ("Framework", "info")),
    ("@KR_Furniture", True, False, "Мои моды", ("Мой", "warning")),
    ("@VPPAdminTools", True, True, "Админки", ("AdminTools", "success")),
    ("@Community-Online-Tools", False, True, "Админки", ("AdminTools", "success")),
    ("@DayZ-Expansion-Core", False, False, "Expansion", None),
    ("@DayZ-Expansion-Book", False, False, "Expansion", None),
    ("@BuilderItems", False, False, "Строительство", None),
    ("@Namalsk-Island", False, False, "Карты", ("Map", "success")),
]
TAGS = ["Все теги", "Framework", "Мои моды", "Админки", "Expansion",
        "Строительство", "Карты"]


class LogWindowMock(QWidget):
    """Окно логов, переложенное по новым правилам.

    Сохранено из нынешнего: виды логов, поиск с переходами и счётчиком,
    «только совпадения», сессия/все файлы, «поверх всех окон», очистка, папка,
    удаление файлов, путь к папке.

    Изменено:
    * вид логов и «сессия/все файлы» — сегментами вместо списка и пары
      радиокнопок: вариантов два-четыре и они короткие;
    * «только совпадения» и «поверх окон» — кнопками-переключателями: это
      режимы панели, а не пункты формы;
    * удаление файлов уехало в меню «Ещё»: необратимое действие не должно
      стоять вплотную к тем, что нажимают каждый день;
    * плашка во всю ширину с текстом в 16 пунктов заменена компактной меткой —
      она съедала полсотни пикселей высоты, а различать окна хватает и метки.
    """

    def __init__(self, side: str, parent=None):
        super().__init__(None, Qt.WindowType.Window)
        self.side = side
        self.setWindowTitle("Логи сервера" if side == "server" else "Логи клиента")
        self.resize(860, 520)
        # Ниже этого панели инструментов начинают наезжать друг на друга.
        self.setMinimumWidth(520)
        # обычный QWidget фон себе не красит и в тёмной теме остаётся светлым
        self._paint_bg()
        qconfig.themeChanged.connect(self._paint_bg)
        col = QVBoxLayout(self)
        col.setContentsMargins(tokens.SPACE_S, tokens.SPACE_S,
                               tokens.SPACE_S, tokens.SPACE_S)
        col.setSpacing(tokens.SPACE_XS)

        # FlowLayout, а не ряд: при сужении окна элементы переносятся на
        # следующую строку, а не уезжают за край, где их не видно и не нажать.
        first = FlowLayout()
        first.setContentsMargins(0, 0, 0, 0)
        first.setHorizontalSpacing(tokens.SPACE_XS)
        first.setVerticalSpacing(tokens.SPACE_XXS)
        chip = CaptionLabel("СЕРВЕР" if side == "server" else "КЛИЕНТ")
        role = "success" if side == "server" else "info"
        chip.setStyleSheet(f"color:{tokens.color(role)};font-weight:700;")
        first.addWidget(chip)
        kinds = SegmentedWidget()
        items = [("script", "Скрипты"), ("crash", "Падения"), ("rpt", "RPT")]
        if side == "server":
            items.insert(1, ("console", "Консоль"))
        for key, text in items:
            kinds.addItem(routeKey=key, text=text, onClick=lambda _c=False: None)
        kinds.setCurrentItem("script")
        first.addWidget(kinds)
        search = SearchLineEdit()
        search.setPlaceholderText("Поиск по логам…")
        search.setFixedWidth(230)
        first.addWidget(search)
        for icon, tip in ((FIF.UP, "Предыдущее совпадение (Shift+Enter)"),
                          (FIF.DOWN, "Следующее совпадение (Enter)")):
            b = ToolButton(icon)
            b.setToolTip(tip)
            first.addWidget(b)
        first.addWidget(CaptionLabel("3 из 17"))
        only = TogglePushButton("Только совпадения")
        only.setMinimumWidth(1)
        first.addWidget(only)
        col.addLayout(first)

        second = FlowLayout()
        second.setContentsMargins(0, 0, 0, 0)
        second.setHorizontalSpacing(tokens.SPACE_XS)
        second.setVerticalSpacing(tokens.SPACE_XXS)
        scope = SegmentedWidget()
        for key, text in (("session", "Текущая сессия"), ("all", "Все файлы")):
            scope.addItem(routeKey=key, text=text, onClick=lambda _c=False: None)
        scope.setCurrentItem("session")
        second.addWidget(scope)
        b_clear = PushButton(FIF.ERASE_TOOL, "Очистить")
        b_clear.setToolTip("Очищает окно, файлы логов не трогает")
        b_clear.setMinimumWidth(1)
        second.addWidget(b_clear)
        on_top = TogglePushButton(FIF.PIN, "Поверх окон")
        on_top.setMinimumWidth(1)
        second.addWidget(on_top)
        more = TransparentToolButton(FIF.MORE)
        more.setToolTip("Ещё")
        more.clicked.connect(lambda: self._menu(more))
        second.addWidget(more)
        col.addLayout(second)

        # Путь — отдельной строкой: в ряду он растягивался и уносил кнопки за
        # край окна, а сам обрезался.
        path = HyperlinkLabel(PATH_SAMPLE)
        path.setToolTip("Открыть папку логов")
        # путь бывает длиннее окна: не даём ему требовать ширину, иначе он
        # растягивает строку и уходит за край
        path.setMinimumWidth(1)
        path.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        col.addWidget(path)

        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setFont(tokens.mono_font())
        tokens.apply_console(view)
        for text, level in TAB_LOG.get(side, []):
            color = tokens.level_colors().get(level)
            view.appendHtml('<span style="color:' + color + ';">' + text + '</span>')
        col.addWidget(view, 1)

    def _paint_bg(self) -> None:
        self.setStyleSheet(f"LogWindowMock{{background:{tokens.color('window')};}}")

    def _menu(self, anchor) -> None:
        menu = RoundMenu(parent=self)
        menu.addAction(Action(FIF.FOLDER, "Открыть папку логов"))
        menu.addAction(Action(FIF.SYNC, "Загрузить ещё файлы"))
        menu.addSeparator()
        menu.addAction(Action(FIF.DELETE, "Удалить файлы логов"))
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height() + 4)))


class NewPresetDialog(MessageBoxBase):
    """Создание пресета.

    Копия — не отдельное окно, а строка «На основе» здесь же: человек создаёт
    пресет и заодно говорит, откуда взять настройки. Кнопка «Сделать копию» в
    шапке открывает это же окно с уже выбранным основанием.
    """

    def __init__(self, base: str = "", parent=None):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel("Новый пресет"))
        self.viewLayout.addWidget(shrink(CaptionLabel(
            "Конфиг, профиль и миссия создадутся сами, порт возьмётся первый "
            "свободный. Остальное можно поменять потом.")))

        self.name = LineEdit()
        self.name.setPlaceholderText("Например: test_namalsk")
        self.name.setText(f"{base}_2" if base else "")
        self.viewLayout.addWidget(setting_row(
            "Название", "Латиница, цифры, дефис и подчёркивание.", self.name))

        self.mode = SegmentedWidget()
        for key, text in (("diag", "Diag"), ("dedicated", "Dedicated")):
            self.mode.addItem(routeKey=key, text=text, onClick=lambda _c=False: None)
        self.mode.setCurrentItem("diag")
        self.viewLayout.addWidget(setting_row(
            "Режим", "Diag — отладка модов с filepatching. Dedicated — как "
            "настоящий сервер.", self.mode))

        self.map = ComboBox()
        self.map.addItems(["Chernarus", "Livonia", "Sakhal", "Namalsk", "Deer Isle",
                           "Своя карта…"])
        self.map.setFixedWidth(200)
        self.viewLayout.addWidget(setting_row(
            "Карта", "Миссия скачается сама, если её ещё нет.", self.map))

        self.base = ComboBox()
        self.base.addItem("Пустой — настройки по умолчанию")
        self.base.addItems(PRESETS)
        self.base.setFixedWidth(240)
        if base in PRESETS:
            self.base.setCurrentText(base)
        self.viewLayout.addWidget(setting_row(
            "На основе", "Возьмёт моды, параметры и автоматику выбранного "
            "пресета. Конфиг, профиль и миссия всё равно будут свои.", self.base))

        self.yesButton.setText("Создать")
        self.cancelButton.setText("Отмена")
        self.widget.setMinimumWidth(560)


class CopyPresetDialog(MessageBoxBase):
    """Копия пресета — то, чего сейчас нет вовсе: пять похожих серверов делают
    пятью полными проходами мастера."""

    def __init__(self, source: str, parent=None):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel("Копия пресета"))
        self.viewLayout.addWidget(shrink(CaptionLabel(
            f"Скопируются моды, параметры и автоматика пресета «{source}». "
            "Конфиг, профиль и миссия будут созданы свои, порт — первый свободный.")))
        self.name = LineEdit()
        self.name.setText(f"{source}_2")
        self.viewLayout.addWidget(self.name)
        self.yesButton.setText("Создать копию")
        self.cancelButton.setText("Отмена")
        self.widget.setMinimumWidth(420)


class ModsDialog(MessageBoxBase):
    """Состав модов пресета.

    Сохранено из нынешнего окна: фильтр по названию, фильтр по тегу, «включить
    все» / «выключить все», сохранение и применение наборов, подключение
    коллекции Steam, флаги модов, проверка зависимостей, подхват модов, которые
    Steam докачал прямо сейчас.

    Изменено: тип (клиент или сервер) задаётся прямо в строке. Сейчас за ним
    надо уходить на вкладку «Моды», ставить признак «Серверный» и возвращаться,
    и оба окна вынуждены печатать об этом инструкцию.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel("Подключённые моды"))

        top = QHBoxLayout()
        top.setSpacing(tokens.SPACE_XS)
        self.search = SearchLineEdit()
        self.search.setPlaceholderText("Фильтр по названию…")
        self.search.textChanged.connect(lambda _t: self._filter())
        top.addWidget(self.search, 1)
        self.tags = ComboBox()
        self.tags.addItems(TAGS)
        self.tags.setFixedWidth(160)
        self.tags.currentIndexChanged.connect(lambda _i: self._filter())
        top.addWidget(self.tags)
        self.only_on = TogglePushButton("Только подключённые")
        self.only_on.setMinimumWidth(1)
        self.only_on.toggled.connect(lambda _v: self._filter())
        top.addWidget(self.only_on)
        self.viewLayout.addLayout(top)

        acts = QHBoxLayout()
        acts.setSpacing(tokens.SPACE_XS)
        b_all = PushButton("Выбрать все")
        b_all.clicked.connect(lambda: self._set_all(True))
        b_none = PushButton("Снять все")
        b_none.clicked.connect(lambda: self._set_all(False))
        b_sets = PushButton(FIF.SAVE_AS, "Наборы")
        b_sets.clicked.connect(lambda: self._sets_menu(b_sets))
        b_coll = PushButton(FIF.CLOUD_DOWNLOAD, "Из коллекции Steam…")
        for b in (b_all, b_none, b_sets, b_coll):
            b.setMinimumWidth(1)
            acts.addWidget(b)
        acts.addStretch(1)
        self.counter = CaptionLabel("")
        acts.addWidget(self.counter)
        self.viewLayout.addLayout(acts)

        area = SmoothScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(SmoothScrollArea.Shape.NoFrame)
        area.setStyleSheet("QScrollArea{background:transparent;border:none;}"
                           " QWidget#modsInner{background:transparent;}")
        inner = QWidget()
        inner.setObjectName("modsInner")
        box = QVBoxLayout(inner)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        self.rows = []
        for name, on, server, tag, flag in FAKE_MODS:
            self.rows.append(self._row(name, on, server, tag, flag))
            box.addWidget(self.rows[-1]["widget"])
        box.addStretch(1)
        area.setWidget(inner)
        area.setMinimumHeight(250)
        self.viewLayout.addWidget(area)

        self.viewLayout.addWidget(shrink(CaptionLabel(
            "Зависимости проверяются при сохранении: если моду нужен другой мод, "
            "программа предложит подключить его. Моды, докачанные Steam прямо "
            "сейчас, появятся в списке сами.")))

        self.yesButton.setText("Сохранить")
        self.cancelButton.setText("Отмена")
        self.widget.setMinimumWidth(640)
        self._filter()

    def _row(self, name, on, server, tag, flag):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(tokens.SPACE_S)
        chk = CheckBox(name)
        chk.setChecked(on)
        chk.toggled.connect(lambda _v: self._count())
        lay.addWidget(chk)
        if flag:
            mark = CaptionLabel(flag[0])      # флаг мода своим цветом, как в дереве
            mark.setStyleSheet(f"color:{tokens.color(flag[1])};font-weight:600;")
            lay.addWidget(mark)
        lay.addStretch(1)
        kind = SegmentedWidget()
        for key, text in (("client", "Клиент"), ("server", "Сервер")):
            kind.addItem(routeKey=key, text=text, onClick=lambda _c=False: None)
        kind.setCurrentItem("server" if server else "client")
        lay.addWidget(kind)
        return {"widget": w, "chk": chk, "tag": tag, "name": name}

    def _filter(self) -> None:
        text = self.search.text().strip().lower()
        tag = self.tags.currentText()
        for r in self.rows:
            ok = text in r["name"].lower()
            if tag != TAGS[0]:
                ok = ok and r["tag"] == tag
            if self.only_on.isChecked():
                ok = ok and r["chk"].isChecked()
            r["widget"].setVisible(ok)
        self._count()

    def _count(self) -> None:
        on = sum(1 for r in self.rows if r["chk"].isChecked())
        self.counter.setText(f"подключено {on} из {len(self.rows)}")

    def _set_all(self, state: bool) -> None:
        # только видимые: фильтр — часть выбора, иначе «выбрать все» тронет и то,
        # что человек сейчас отфильтровал прочь
        for r in self.rows:
            if r["widget"].isVisible():
                r["chk"].setChecked(state)
        self._count()

    def _sets_menu(self, anchor) -> None:
        menu = RoundMenu(parent=self)
        menu.addAction(Action(FIF.SAVE_AS, "Сохранить как набор…"))
        menu.addSeparator()
        for name in MOD_SETS:
            if name != "Свой список":
                menu.addAction(Action(FIF.TILES, f"Применить «{name}»"))
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height() + 4)))


PRESETS = ["test_cher", "test_enoch", "test_namalsk", "test_deer", "test_kot"]

# Наборы модов в программе уже есть (ModPreset), но живут внутри модального
# окна подключения — снаружи о них не узнать. Здесь они на виду.
MOD_SETS = {
    "Базовый": "@CF, @KR_Furniture, @VPPAdminTools",
    "Только мой мод": "@CF, @KR_Furniture",
    "Полный тест": "@CF, @KR_Furniture, @VPPAdminTools, @DayZ-Expansion-Core и ещё 8",
    "Свой список": "состав отличается от всех наборов",
}


class PresetBar(QWidget):
    """Текущий пресет — над всеми страницами.

    Пресет задаёт контекст всей программы: от него зависят и запуск, и какой
    файл правит «Конфиг сервера», и какие моды показывает подключение. Пока он
    жил выпадающим списком на одной странице, на остальных было не понять, с
    чем работаешь, — а смена пресета на «Запуске» молча меняла файл под
    редактором конфига на другой странице.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(tokens.SPACE_L, tokens.SPACE_XS,
                               tokens.SPACE_L, tokens.SPACE_XS)
        row.setSpacing(tokens.SPACE_XS)
        self.label = BodyLabel("Пресет")
        row.addWidget(self.label)
        self.none_hint = CaptionLabel("ещё не создан")
        self.none_hint.hide()
        row.addWidget(self.none_hint)
        self.b_new = PrimaryPushButton(FIF.ADD, "Создать пресет")
        self.b_new.setMinimumWidth(1)
        self.b_new.hide()
        row.addWidget(self.b_new)
        self.combo = ComboBox()
        # «Создать» первым пунктом — всегда, есть пресеты или нет: список
        # пресетов и есть то место, где их заводят.
        self.combo.addItem("+  Создать пресет…")
        self.combo.addItems(PRESETS)
        self.combo.setCurrentIndex(1)
        self.combo.setFixedWidth(190)
        self.combo.currentIndexChanged.connect(self._picked)
        row.addWidget(self.combo)
        # без переноса: полоса фиксированной высоты, вторая строка обрезается
        self.info = CaptionLabel(f"{MAP_NAME} · порт {PORT} · Diag")
        self.info.setMinimumWidth(1)
        row.addWidget(self.info)
        row.addStretch(1)
        self.b_edit = TransparentToolButton(FIF.EDIT)
        self.b_edit.setToolTip("Изменить пресет")
        # карандаш раскрывает плашку настроек на том же экране
        self.b_edit.clicked.connect(
            lambda: self.window().launch.setup_card.set_open(True))
        self.b_copy = TransparentToolButton(FIF.COPY)
        self.b_copy.setToolTip("Сделать копию")
        self.b_copy.clicked.connect(self._copy)
        self.b_more = TransparentToolButton(FIF.MORE)
        self.b_more.setToolTip("Ещё")
        self.b_more.clicked.connect(self._menu)
        for b in (self.b_edit, self.b_copy, self.b_more):
            row.addWidget(b)

    def _picked(self, index: int) -> None:
        """Первый пункт — не пресет, а действие: открываем создание и
        возвращаем выбор на тот пресет, что был."""
        if index != 0:
            self._last = index
            return
        self.combo.setCurrentIndex(getattr(self, "_last", 1))
        NewPresetDialog(parent=self.window()).exec()

    def set_empty(self, empty: bool) -> None:
        """Пресетов нет — в шапке нечего показывать, кроме приглашения создать."""
        for w in (self.combo, self.info, self.b_edit, self.b_copy, self.b_more):
            w.setVisible(not empty)
        self.none_hint.setVisible(empty)
        self.b_new.setVisible(empty)

    def _copy(self) -> None:
        NewPresetDialog(self.combo.currentText(), self.window()).exec()

    def _menu(self) -> None:
        """Редкие действия над пресетом — в меню, а не кнопками на виду."""
        menu = RoundMenu(parent=self)
        menu.addAction(Action(FIF.LINK, "Ярлык на рабочий стол"))
        menu.addAction(Action(FIF.FOLDER, "Открыть папку профиля"))
        menu.addSeparator()
        menu.addAction(Action(FIF.BROOM, "Очистить базу данных"))
        menu.addAction(Action(FIF.BROOM, "Очистить профиль"))
        menu.addSeparator()
        menu.addAction(Action(FIF.DELETE, "Удалить пресет"))
        menu.exec(self.b_more.mapToGlobal(QPoint(0, self.b_more.height() + 4)))
        self.setFixedHeight(44)
        # тонкая линия снизу отделяет контекст от содержимого страницы
        self.setStyleSheet(f"PresetBar{{border-bottom:1px solid {tokens.color('border')};}}")


class Rule(QWidget):
    """Разделительная линия, которая рисует себя сама.

    Через таблицу стилей не годится: карточка при наведении мыши перекрашивает
    себя своим стилем, и линия внутри неё исчезала. Собственная отрисовка чужим
    стилем не перебивается.
    """

    def __init__(self, vertical: bool = False, parent=None):
        super().__init__(parent)
        self.vertical = vertical
        if vertical:
            self.setFixedWidth(1)
        else:
            self.setFixedHeight(1)

    def paintEvent(self, e):        # имя метода задаёт Qt
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(tokens.color("divider")))


def subheading(text: str, line: bool = False) -> QWidget:
    """Подзаголовок внутри карточки. С линией — когда отделяет блок от блока."""
    w = QWidget()
    box = QVBoxLayout(w)
    box.setContentsMargins(0, tokens.SPACE_S if line else 0, 0, tokens.SPACE_XXS)
    box.setSpacing(tokens.SPACE_XS)
    if line:
        box.addWidget(Rule())
    box.addWidget(StrongBodyLabel(text))
    return w


class Columns(QWidget):
    """Раскладывает строки настроек в несколько колонок по ширине.

    Строка настройки — это название, пояснение и контрол; в одну колонку такие
    строки занимают вдвое больше высоты, чем нужно, а справа остаётся пустое
    место. Колонок ровно столько, сколько помещается: узкое окно — одна, широкое
    — две или три. Порядок заполнения слева направо, как читают.
    """

    MIN_COL = 430           # ниже этого в колонке не помещаются название и контрол

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        # какие строки показывать — храним явным списком. Опираться на
        # видимость виджетов нельзя: строка, которую ещё ни разу не показывали,
        # для Qt скрыта, и сетка получалась пустой.
        self.rows = list(rows)
        self.active = list(rows)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        # Жёлоб широкий и с линией: иначе контрол левой колонки оказывается
        # ближе к заголовку правой, чем к своему, и читается вместе с ним.
        self.grid.setHorizontalSpacing(tokens.SPACE_L)
        self.grid.setVerticalSpacing(0)
        self._cols = 0
        self._relayout(1)

    def _relayout(self, cols: int) -> None:
        if cols == self._cols:
            return
        self._cols = cols
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None and w not in self.rows:
                w.deleteLater()          # старые разделители
        # содержимое в чётных столбцах, разделители в нечётных
        for i, row in enumerate(self.active):
            self.grid.addWidget(row, i // cols, (i % cols) * 2)
        rows_count = (len(self.active) + cols - 1) // cols
        for c in range(cols):
            self.grid.setColumnStretch(c * 2, 1)
            if c:
                self.grid.addWidget(Rule(vertical=True, parent=self),
                                    0, c * 2 - 1, max(rows_count, 1), 1)

    def set_active(self, rows) -> None:
        """Показать только эти строки — остальные убрать из сетки."""
        for row in self.rows:
            row.setVisible(row in rows)
        self.active = [r for r in self.rows if r in rows]
        cols, self._cols = self._cols, 0
        self._relayout(cols or 1)

    def resizeEvent(self, e):       # имя метода задаёт Qt
        super().resizeEvent(e)
        self._relayout(max(1, self.width() // self.MIN_COL))


class PresetSections:
    """Разделы, описывающие пресет: основное, параметры запуска, конфиг
    сервера, автоматика, обслуживание.

    Не страница и не окно — просто набор карточек, который кладут туда, где он
    нужен. Сейчас они лежат прямо на «Запуске», свёрнутыми.
    """

    # Флаги запуска названы так же, как в командной строке: для мододела это
    # точнее любого перевода — совпадает с документацией и гуглится.
    SERVER_FLAGS = [
        ("-filePatching", "Читать скрипты из папок, а не только из PBO", True),
        ("-scriptDebug=true", "Подробные ошибки скриптов в логе", True),
        ("-dologs", "Писать логи движка", True),
        ("-adminLog", "Журнал действий администраторов", False),
        ("-freezecheck", "Ловить зависания сервера", False),
    ]
    CLIENT_FLAGS = [
        ("-filePatching", "То же для клиента", True),
        ("-noPause", "Не ставить игру на паузу без фокуса", True),
        ("-noSplash", "Пропустить заставки", True),
        ("-window", "Запускать в окне", False),
    ]
    # Ключи конфига: имя, пояснение, тип, значение, писать ли в файл
    CFG = [
        ("hostname", "Название сервера в браузере", "text", "KR Test — test_cher", True),
        ("maxPlayers", "Максимум игроков", "int", "60", True),
        ("verifySignatures", "Проверка подписей PBO", "choice", "Выключена", True),
        ("disable3rdPerson", "Запретить вид от третьего лица", "bool", "", False),
        ("allowFilePatching", "Пускать клиентов с -filePatching", "bool", "", True),
        ("instanceId", "Идентификатор инстанса", "int", "1", True),
    ]

    def __init__(self):
        # строки собираются отдельно от карточек: одни и те же строки нужны и
        # плашке на «Запуске», и странице пресета
        self.params_rows = self._params_rows()
        self.cfg_rows = self._cfg_rows()

    # ------------------------------------------------------------- разделы

    def _main_card(self):
        name = LineEdit()
        name.setText("test_cher")
        name.setFixedWidth(220)
        mode = SegmentedWidget()
        for key, text in (("diag", "Diag"), ("dedicated", "Dedicated")):
            mode.addItem(routeKey=key, text=text, onClick=lambda _c=False: None)
        mode.setCurrentItem("diag")
        branch = SegmentedWidget()
        for key, text in (("stable", "Stable"), ("exp", "Experimental")):
            branch.addItem(routeKey=key, text=text, onClick=lambda _c=False: None)
        branch.setCurrentItem("stable")
        card_map = ComboBox()
        card_map.addItems(["Chernarus", "Livonia", "Sakhal", "Namalsk", "Своя карта…"])
        card_map.setFixedWidth(200)
        port = LineEdit()
        port.setText("2302")
        port.setFixedWidth(120)
        return rows_card(FIF.TAG, "Основное", "test_cher · Chernarus · порт 2302", [
            setting_row("Название", "Латиница, цифры, дефис и подчёркивание.", name),
            setting_row("Режим", "Diag — отладка с filepatching. Dedicated — "
                                 "отдельная серверная программа.", mode),
            setting_row("Ветка", "Stable или Experimental — разные папки игры.", branch),
            setting_row("Карта", "Миссия создастся из шаблона, если её ещё нет.", card_map),
            setting_row("Порт", "Свободен. Steam Query возьмёт 2304.", port),
        ])

    def _params_rows(self):
        self.side = SegmentedWidget()
        for key, text in (("server", "Сервера"), ("client", "Клиента")):
            self.side.addItem(routeKey=key, text=text,
                              onClick=lambda _c=False, k=key: self._show_side(k))
        self.side.setCurrentItem("server")
        rows = [subheading("Параметры запуска"),
                setting_row("Чьи параметры",
                            "Флаги названы так же, как в командной строке игры.",
                            self.side)]
        self.flag_rows = {}
        all_flags = []
        for side, flags in (("server", self.SERVER_FLAGS), ("client", self.CLIENT_FLAGS)):
            self.flag_rows[side] = []
            for flag, why, on in flags:
                sw = SwitchButton()
                sw.setOnText("")
                sw.setOffText("")
                sw.setChecked(on)
                row = setting_row(flag, why, sw)
                self.flag_rows[side].append(row)
                all_flags.append(row)
        self.flags_box = Columns(all_flags)
        self.flags_box.set_active(self.flag_rows["server"])
        self.flags_box.setContentsMargins(0, 0, 0, 0)
        rows.append(self.flags_box)
        extra = LineEdit()
        extra.setPlaceholderText("Например: -cpuCount=4")
        extra.setFixedWidth(260)
        rows.append(setting_row("Дополнительно",
                                "Аргументы, которых нет в списке выше.", extra))
        self._show_side("server")
        return rows

    def _show_side(self, key: str) -> None:
        if hasattr(self, "flags_box"):
            self.flags_box.set_active(self.flag_rows[key])

    def _cfg_rows(self):
        rows = []
        search = SearchLineEdit()
        search.setFixedWidth(280)
        search.setPlaceholderText("Найти среди 67 ключей…")
        search_row = QWidget()
        srow = QHBoxLayout(search_row)
        srow.setContentsMargins(0, 0, 0, tokens.SPACE_XXS)
        srow.addWidget(search)
        srow.addStretch(1)
        rows.append(search_row)
        keys = []
        for key, why, kind, value, write in self.CFG:
            # Галка — в начало строки: она относится к ключу целиком («писать ли
            # его в файл»), а не к значению. Справа при этом остаётся только сам
            # контрол значения, и строка помещается в колонку.
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, tokens.SPACE_XXS, 0, tokens.SPACE_XXS)
            lay.setSpacing(tokens.SPACE_S)
            chk = CheckBox()
            chk.setChecked(write)
            chk.setToolTip("Писать ключ в serverDZ.cfg. Снятая галка убирает его "
                           "из файла — игра возьмёт своё значение по умолчанию")
            lay.addWidget(chk, 0, Qt.AlignmentFlag.AlignVCenter)
            text = QVBoxLayout()
            text.setSpacing(0)
            text.addWidget(shrink(StrongBodyLabel(key)))
            text.addWidget(shrink(CaptionLabel(why)))
            holder = QWidget()
            holder.setLayout(text)
            holder.setMinimumWidth(150)
            lay.addWidget(holder, 1)
            if kind == "bool":
                ctl = SwitchButton()
                ctl.setOnText("")
                ctl.setOffText("")
            elif kind == "choice":
                ctl = SegmentedWidget()
                for k, t in (("off", "Выкл"), ("on", "Вкл")):
                    ctl.addItem(routeKey=k, text=t, onClick=lambda _c=False: None)
                ctl.setCurrentItem("off")
            else:
                ctl = LineEdit()
                ctl.setText(value)
                ctl.setFixedWidth(170 if kind == "text" else 90)
            lay.addWidget(slot(ctl), 0, Qt.AlignmentFlag.AlignVCenter)
            keys.append(row)
        rows.append(Columns(keys))
        more_row = QWidget()
        mrow = QHBoxLayout(more_row)
        mrow.setContentsMargins(0, tokens.SPACE_XXS, 0, 0)
        b_more = PushButton(FIF.CHEVRON_DOWN_MED, "Ещё 61 ключ, включая те, которых нет в файле")
        b_more.setMinimumWidth(1)
        mrow.addWidget(b_more)
        mrow.addStretch(1)
        rows.append(more_row)
        return rows

    def _auto_card(self):
        autostart = SwitchButton()
        autostart.setOnText("")
        autostart.setOffText("")
        revive = SwitchButton()
        revive.setOnText("")
        revive.setOffText("")
        revive.setChecked(True)
        restart = SwitchButton()
        restart.setOnText("")
        restart.setOffText("")
        times = PushButton(FIF.DATE_TIME, "04:00, 12:00, 20:00")
        return rows_card(FIF.ROBOT, "Автоматика", "подъём после падения включён", [
            setting_row("Запускать при старте программы",
                        "В том числе когда программа стартует вместе с Windows.",
                        autostart),
            setting_row("Поднимать после падения",
                        "Зависание опознаётся по RCon: процесс жив, а сервер молчит.",
                        revive),
            setting_row("Перезапускать по расписанию",
                        "Игроков предупредит сообщение в чат.", restart),
            setting_row("Время перезапусков", "Можно задать несколько.", times),
        ])

    def _service_card(self):
        return rows_card(FIF.BROOM, "Обслуживание", "", [
            setting_row("База данных",
                        "Удалит storage_* в миссии: лут, персонажи, постройки.",
                        PushButton("Очистить")),
            setting_row("Папка профиля",
                        "Логи, настройки модов и права админок.",
                        PushButton("Очистить")),
            setting_row("Права админок",
                        "Перезапишет списки админов и пароль VPP в профиле.",
                        PushButton("Обновить")),
            setting_row("Ярлык на рабочем столе",
                        "Запускает этот пресет без открытия окна программы.",
                        PushButton("Создать")),
        ])


class Placeholder(QWidget):
    """Заглушка страницы, до которой ещё не дошли."""

    def __init__(self, name: str, note: str):
        super().__init__()
        self.setObjectName("mock_" + name)
        col = QVBoxLayout(self)
        col.setContentsMargins(tokens.SPACE_L, tokens.SPACE_L,
                               tokens.SPACE_L, tokens.SPACE_L)
        col.addWidget(TitleLabel(name))
        col.addWidget(shrink(BodyLabel(note)))
        col.addStretch(1)


class Mockup(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KR QTS — прототип интерфейса")
        # Размер по умолчанию не больше того, что есть на экране: на ноутбуке
        # 1366×768 рабочая высота около 728 px, и окно в 740 туда не влезает.
        from PySide6.QtWidgets import QApplication as _App
        wide, high = tokens.WIN_MAIN
        screen = _App.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            wide = min(wide, avail.width() - 60)
            high = min(high, avail.height() - 60)
        self.resize(wide, high)

        self.launch = LaunchPage(self)
        self.addSubInterface(self.launch, FIF.PLAY, "Запуск")
        self.addSubInterface(Placeholder("Моды", "Объединённый экран модов — "
                                         "после пресетов."),
                             FIF.APPLICATION, "Моды")
        self.addSubInterface(Placeholder("Настройки", "Карточки настроек с поиском — позже."),
                             FIF.SETTING, "Настройки",
                             position=NavigationItemPosition.BOTTOM)
        # Раскладка библиотеки: [навигация][widgetLayout -> стек страниц].
        # Кладём шапку и стек в свою колонку, чтобы шапка стояла над всеми
        # страницами, а не повторялась внутри каждой.
        self.preset_bar = PresetBar(self)
        holder = QWidget(self)
        colum = QVBoxLayout(holder)
        colum.setContentsMargins(0, 0, 0, 0)
        colum.setSpacing(0)
        colum.addWidget(self.preset_bar)
        self.widgetLayout.removeWidget(self.stackedWidget)
        colum.addWidget(self.stackedWidget)
        self.widgetLayout.addWidget(holder)

        self._add_proto_bar()


    def _set_state(self, key: str) -> None:
        self.launch.set_state(key)
        self.preset_bar.set_empty(key == ST_EMPTY)

    def _add_proto_bar(self) -> None:
        """Полоса самого прототипа. В приложении её не будет."""
        bar = QWidget(self)
        row = QHBoxLayout(bar)
        row.setContentsMargins(tokens.SPACE_S, tokens.SPACE_XXS, tokens.SPACE_S, tokens.SPACE_XXS)
        row.setSpacing(tokens.SPACE_XS)
        row.addWidget(CaptionLabel("прототип:"))
        theme = ComboBox()
        theme.addItems(["Тёмная тема", "Светлая тема"])
        theme.setFixedWidth(150)
        theme.currentIndexChanged.connect(
            lambda i: setTheme(Theme.DARK if i == 0 else Theme.LIGHT))
        row.addWidget(theme)
        state = ComboBox()
        for key, text in STATES.items():
            state.addItem(text, userData=key)
        state.setFixedWidth(190)
        state.currentIndexChanged.connect(
            lambda i: self._set_state(state.itemData(i)))
        # список показывает первый пункт, но сигнал сработал бы только на смену —
        # ставим тот, в котором экран открылся
        state.setCurrentIndex(list(STATES).index(ST_IDLE))
        row.addWidget(state)
        row.addStretch(1)
        bar.setFixedHeight(34)
        # Раскладка FluentWindow горизонтальная: навигация слева, страницы
        # справа. Вставка сюда виджета делает из него третью колонку — именно
        # так полоса и уехала чёрной пустотой на пол-окна. Кладём её первой
        # строкой внутрь самой страницы.
        self.launch.layout().insertWidget(0, bar)


def main() -> int:
    app = QApplication(sys.argv)
    setTheme(Theme.DARK)
    setThemeColor(tokens.ACCENT)
    w = Mockup()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
