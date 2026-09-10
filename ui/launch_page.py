"""Страница «Запуск» — по прототипу из tools/mockup.py.

Что изменилось против прежнего вида. Раньше страница была четырьмя блоками с
галками и шестью кнопками одного веса: главное действие терялось среди
настроек, а состояние сервера было подписью в углу. Теперь наверху карточка
состояния — крупно сказано, что происходит, и одна кнопка, которая называет то,
что сделает. Настройки уехали в сворачиваемые карточки с итогом в шапке.

Главное поведение — приоритет по состоянию: пока ничего не запущено, нужны
настройки, и карточки раскрыты; как только сервер поднялся, они сворачиваются
сами и журнал занимает освободившееся место. При остановке возвращается то, что
было раскрыто до запуска.

Виджеты и их имена сохранены полностью: остальные полторы тысячи строк главного
окна обращаются к ним по именам, и переделка меняет раскладку, а не устройство.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSplitter, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, CardWidget, CheckBox, ComboBox, IconWidget,
    PlainTextEdit, PrimaryPushButton, PushButton, SegmentedWidget,
    SmoothScrollArea, StrongBodyLabel, SubtitleLabel, SwitchButton, TitleLabel,
    TransparentToolButton, FluentIcon as FIF,
)

from core.i18n import tr
from core.settings import EXPERIMENTAL, STABLE
from ui import tokens
from ui.cards import rows_card
from ui.rows import Columns, setting_row, shrink

# Как выглядит значок состояния: он показывает состояние, а не предлагаемое
# действие. Пауза, когда стоим; треугольник, когда работает.
BADGE = {
    "launch": (FIF.PAUSE_BOLD, "muted"),
    "starting": (FIF.SYNC, "warning"),
    "stop": (FIF.PLAY_SOLID, "success"),
    "stopping": (FIF.PAUSE_BOLD, "warning"),
}

SIDES_BOTH, SIDES_SERVER, SIDES_CLIENT = "both", "server", "client"


class StateBadge(QFrame):
    """Круглый значок состояния — цвет роли и значок того, что происходит."""

    SIZE = 40

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        self.icon = IconWidget(FIF.PAUSE_BOLD, self)
        self.icon.setFixedSize(18, 18)
        box.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignCenter)
        self.set_role("muted")

    def set_role(self, role: str) -> None:
        self.setStyleSheet(
            f"QFrame{{background:{tokens.tint(role, 0.18)};"
            f"border-radius:{self.SIZE // 2}px;}}")

    def apply(self, icon, role: str) -> None:
        self.icon.setIcon(icon)
        self.set_role(role)


class LaunchInterface(QWidget):
    """Страница «Запуск»: пресет, состояние, настройки запуска, журнал."""

    def __init__(self, win) -> None:
        super().__init__()
        self.setObjectName("launchInterface")
        self.win = win
        self._sides = SIDES_BOTH
        self._was_running = False
        self._pre_open: list[bool] = []
        self._syncing = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Прокрутка: раскрытые карточки не должны распирать окно так, что его
        # больше нельзя ужать. Без неё страница требовала высоты больше рабочей
        # области ноутбука.
        scroll = SmoothScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(SmoothScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}"
                             " QWidget#launchInner{background:transparent;}")
        inner = QWidget()
        inner.setObjectName("launchInner")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(tokens.SPACE_L, tokens.SPACE_L,
                                  tokens.SPACE_L, tokens.SPACE_L)
        layout.setSpacing(tokens.SPACE_S)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        layout.addWidget(TitleLabel(tr("main.tab_launch", "Запуск")))
        layout.addLayout(self._preset_row())
        layout.addWidget(self._hero())
        layout.addWidget(self._mods_card())
        layout.addWidget(self._pack_card())
        layout.addWidget(self._setup_card())
        layout.addLayout(self._journal_head())
        layout.addWidget(self._journal(), 1)

        # По умолчанию раскрыт только состав модов: его меняют чаще всего.
        # Раскрыть все три — значит увести журнал за нижний край экрана, а
        # журнал и есть то, куда смотрят сразу после нажатия кнопки.
        self.pack_card.set_open(False)
        self.setup_card.set_open(False)

    # ----------------------------------------------------------------- шапка

    def _preset_row(self) -> QHBoxLayout:
        top = QHBoxLayout()
        top.setSpacing(tokens.SPACE_XS)
        top.addWidget(BodyLabel(tr("main.preset", "Пресет:")))
        self.preset_combo = ComboBox()
        self.preset_combo.setMinimumWidth(200)
        self.preset_combo.setMaximumWidth(260)
        top.addWidget(self.preset_combo)
        self.b_new = TransparentToolButton(FIF.ADD)
        self.b_new.setToolTip(tr("main.preset_new", "Создать"))
        self.b_edit = TransparentToolButton(FIF.EDIT)
        self.b_edit.setToolTip(tr("main.preset_edit", "Изменить"))
        self.b_del = TransparentToolButton(FIF.DELETE)
        self.b_del.setToolTip(tr("main.preset_del", "Удалить"))
        for b in (self.b_new, self.b_edit, self.b_del):
            top.addWidget(b)
        top.addSpacing(tokens.SPACE_M)
        top.addWidget(BodyLabel(tr("main.branch", "Ветка:")))
        self.branch_combo = ComboBox()
        self.branch_combo.addItem("Stable", userData=STABLE)
        self.branch_combo.addItem("Experimental", userData=EXPERIMENTAL)
        top.addWidget(self.branch_combo)
        top.addStretch(1)
        # Обновление — здесь, а не в панели навигации. Там оно было честным, но
        # незаметным: пункт внизу списка, мимо которого человек ходит годами.
        # Обычная, а не первичная: первичная на экране одна, и это «Запустить».
        # Заметность даёт не вес кнопки, а то, что она появляется, только когда
        # есть что сказать.
        self.btn_update = PushButton(FIF.UPDATE,
                                     tr("main.update_btn", "Обновить приложение"))
        self.btn_update.setVisible(False)
        top.addWidget(self.btn_update)
        return top

    # -------------------------------------------------------------- карточка
    #                                                                состояния

    def _hero(self) -> QWidget:
        card = CardWidget()
        box = QVBoxLayout(card)
        box.setContentsMargins(tokens.SPACE_M, tokens.SPACE_M,
                               tokens.SPACE_M, tokens.SPACE_M)
        box.setSpacing(tokens.SPACE_S)

        line = QHBoxLayout()
        line.setSpacing(tokens.SPACE_S)
        self.badge = StateBadge()
        line.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.state_title = shrink(SubtitleLabel(""))
        self.state_sub = shrink(CaptionLabel(""))
        text.addWidget(self.state_title)
        text.addWidget(self.state_sub)
        line.addLayout(text, 1)
        # Прежняя подпись со сторонами: она уже умеет рисовать точку цвета
        # состояния и текст с PID, и переучивать её незачем.
        self.status_label = StrongBodyLabel("")
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        line.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignTop)
        box.addLayout(line)

        row = QHBoxLayout()
        row.setSpacing(tokens.SPACE_S)
        # Состав запуска: два варианта и их сумма — сумма последней, как читают.
        # Галки остаются живыми объектами и хранят состояние: к ним обращается
        # весь остальной код, и они же сохраняют выбор в пресет.
        self.chk_server = CheckBox(tr("common.server", "Сервер"))
        self.chk_client = CheckBox(tr("common.client", "Клиент"))
        self.sides = SegmentedWidget()
        for key, text_ in ((SIDES_SERVER, tr("common.server", "Сервер")),
                           (SIDES_CLIENT, tr("common.client", "Клиент")),
                           (SIDES_BOTH, tr("main.sides_both", "Сервер и клиент"))):
            self.sides.addItem(routeKey=key, text=text_,
                               onClick=lambda _checked=False, k=key: self._pick_sides(k))
        self.sides.setCurrentItem(SIDES_BOTH)
        row.addWidget(self.sides, 0)
        self.btn_launch = PrimaryPushButton(FIF.PLAY, tr("main.launch_btn", "Запустить"))
        self.btn_launch.setMinimumHeight(38)
        self.btn_launch.setMinimumWidth(1)      # ширину задаёт раскладка, не текст
        row.addWidget(self.btn_launch, 1)
        box.addLayout(row)
        return card

    def _pick_sides(self, key: str) -> None:
        """Сегмент переставляет галки — они и есть хранилище выбора."""
        if self._syncing:
            return
        self.chk_server.setChecked(key in (SIDES_SERVER, SIDES_BOTH))
        self.chk_client.setChecked(key in (SIDES_CLIENT, SIDES_BOTH))

    def sync_sides(self) -> None:
        """Ставит сегмент по галкам. Галки меняются и снаружи — из пресета."""
        srv, cli = self.chk_server.isChecked(), self.chk_client.isChecked()
        key = (SIDES_BOTH if srv and cli else
               SIDES_SERVER if srv else
               SIDES_CLIENT if cli else None)
        if key is None or key == self._sides:
            return
        self._sides = key
        self._syncing = True
        try:
            self.sides.setCurrentItem(key)
        finally:
            self._syncing = False

    # -------------------------------------------------------------- карточки

    def _mods_card(self):
        """Моды целиком: и состав запуска, и настройки самих модов.

        Панель одна и та же, что была отдельной вкладкой. Раньше работа над
        модом делилась между вкладкой и модальным окном: тип «серверный»
        задавался в одном месте, подключался мод в другом, и подсказка честно
        отправляла человека на другой экран. Теперь одна таблица.
        """
        self.mods_inline = self.win.mods_panel
        self.mods_card = rows_card(FIF.APPLICATION, tr("main.frame_mods", "Моды"), "",
                                   [self.mods_inline])
        return self.mods_card

    def _pack_card(self):
        self.pack_engine = ComboBox()
        self.pack_engine.addItem(tr("main.repack_off", "Не запаковывать"), userData="")
        self.pack_engine.addItem(tr("settings.engine_normal",
                                    "Обычная — переиспользует temp"), userData="normal")
        self.pack_engine.addItem(tr("settings.engine_full",
                                    "Полная (FullBuild) — чистит temp"), userData="full")
        self.pack_engine.setMinimumWidth(220)
        self.btn_pack_settings = PushButton(FIF.EDIT, tr("common.change", "Изменить"))
        self.btn_pack_settings.setToolTip(tr("main.pack_settings_tip",
                                             "Настройки pboProject — те же, что в «Настройках», "
                                             "но под рукой. Сохраняются сразу."))
        self.btn_sources = PushButton(FIF.SYNC, tr("main.mods_with_sources",
                                                   "Запаковать моды"))
        self.btn_packlogs = PushButton(FIF.ZIP_FOLDER, tr("main.show_packlogs",
                                                          "Логи запаковки"))
        self.btn_packlogs.setToolTip(tr("main.show_packlogs_tip",
                                        "Логи pboProject по последней запаковке: "
                                        "отдельно сборка pbo, отдельно бинаризация."))
        actions = QWidget()
        arow = QHBoxLayout(actions)
        arow.setContentsMargins(0, tokens.SPACE_XXS, 0, 0)
        arow.setSpacing(tokens.SPACE_XS)
        arow.addWidget(self.btn_sources)
        arow.addWidget(self.btn_packlogs)
        arow.addStretch(1)

        self.pack_card = rows_card(FIF.ZIP_FOLDER,
                                   tr("main.frame_pack2", "Запаковка модов"), "", [
            Columns([
            # Название говорит, что настройка включает, а не когда это
            # происходит; пояснение — про результат для человека.
            setting_row(tr("main.pack_row", "Запаковывать при запуске"),
                        tr("main.pack_row_desc",
                           "Мод, у которого сорсы новее его PBO, запакуется перед "
                           "стартом — правки попадут в игру."),
                        self.pack_engine),
            setting_row(tr("main.pack_flags_row", "Флаги pboProject"),
                        tr("main.pack_flags_desc",
                           "Те же, что в настройках, но под рукой."),
                        self.btn_pack_settings),
            ]),
            actions,
        ])
        return self.pack_card

    def _setup_card(self):
        """Всё, что описывает сервер: параметры запуска и его конфиг.

        Раньше и то и другое жило в отдельных окнах, и чтобы поменять одну
        строчку, приходилось открыть, поправить, закрыть. Теперь это одна
        плашка, свёрнутая по умолчанию: настраивают её редко, но когда
        настраивают — возятся долго, и место для этого нужно на странице.
        """
        from ui.cfg_editor import CfgCard
        from ui.params_panel import ParamsPanel

        # Тумблер, а не галка: это состояние системы, а не включение в набор.
        self.chk_hide_window = SwitchButton()
        self.chk_hide_window.setOnText("")
        self.chk_hide_window.setOffText("")
        self.params_panel = ParamsPanel()
        self.cfg_card = CfgCard()
        # Второй кнопки «Изменить пресет» здесь нет намеренно: она уже есть
        # карандашом в строке пресета, а два входа в одно действие расходятся
        # по поведению при первой же правке.
        self.setup_card = rows_card(
            FIF.SETTING, tr("main.frame_server", "Настройки сервера"),
            tr("main.frame_server_sum", "параметры запуска и serverDZ.cfg"), [
                setting_row(tr("main.hide_server_window", "Скрыть окно сервера"),
                            tr("main.hide_server_window_desc",
                               "Всё, что писало окно сервера, пойдёт в журнал ниже."),
                            self.chk_hide_window),
                self.params_panel,
                self.cfg_card,
            ])
        return self.setup_card

    # ---------------------------------------------------------------- журнал

    def _journal_head(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(tokens.SPACE_XS)
        row.addWidget(StrongBodyLabel(tr("main.journal", "Журнал запуска")))
        row.addStretch(1)
        self.btn_logs = PushButton(FIF.DOCUMENT, tr("main.show_logs",
                                                    "Логи клиента/сервера"))
        row.addWidget(self.btn_logs)
        return row

    def _journal(self) -> QWidget:
        # Журнал запуска и — когда окно сервера спрятано — его консоль под ним.
        # Двумя областями, а не одной лентой: это разные потоки. Наш журнал
        # редкий и осмысленный, консоль сервера частая и подробная; смешав их,
        # мы утопили бы первое во втором.
        self.launch_log = PlainTextEdit()
        self.launch_log.setReadOnly(True)
        self.launch_log.setFont(tokens.mono_font())
        self.launch_log.setMinimumHeight(140)
        # Пустое состояние: пустая чёрная область молчит о том, зачем она.
        self.launch_log.setPlaceholderText(tr(
            "main.journal_empty",
            "Здесь появится журнал запуска: запаковка модов, старт сервера, "
            "расход скриптовой памяти и ошибки."))
        tokens.apply_console(self.launch_log)

        self.console_box = QWidget()
        cbox = QVBoxLayout(self.console_box)
        cbox.setContentsMargins(0, 0, 0, 0)
        cbox.setSpacing(tokens.SPACE_XXS)
        cbox.addWidget(CaptionLabel(tr("main.server_console", "Консоль сервера")))
        self.console_log = PlainTextEdit()
        self.console_log.setReadOnly(True)
        self.console_log.setMaximumBlockCount(5000)
        self.console_log.setFont(tokens.mono_font())
        tokens.apply_console(self.console_log)
        cbox.addWidget(self.console_log, 1)
        self.console_box.setVisible(False)      # только у сервера без своего окна

        self.log_split = QSplitter(Qt.Orientation.Vertical)
        self.log_split.addWidget(self.launch_log)
        self.log_split.addWidget(self.console_box)
        self.log_split.setStretchFactor(0, 1)
        self.log_split.setStretchFactor(1, 1)
        return self.log_split

    # -------------------------------------------------------------- обновление

    def update_state(self) -> None:
        """Приводит шапку и карточки к текущему состоянию. Зовётся из окна.

        Считаем всё здесь, а не в главном окне: страница — представление, и
        знание о том, как выглядит состояние, должно жить рядом с виджетами.
        """
        win = self.win
        self.sync_sides()
        state = win.launch_state()
        icon, role = BADGE.get(state, BADGE["launch"])
        self.badge.apply(icon, role)
        self.state_title.setText(self._title(state))
        self.state_sub.setText(self._subtitle(state))
        self._summaries()
        self.set_running(win.server_running() or win.client_running()
                         or state == "starting")

    def _title(self, state: str) -> str:
        win = self.win
        srv, cli = win.server_running(), win.client_running()
        if state == "starting":
            return tr("main.hero_starting", "Запускается")
        if state == "stopping":
            return tr("main.hero_stopping", "Останавливается")
        if srv and cli:
            return tr("main.hero_running", "Сервер и клиент работают")
        if srv:
            return tr("main.hero_server", "Сервер работает")
        if cli:
            return tr("main.hero_client", "Клиент работает")
        return tr("main.hero_idle", "Ничего не запущено")

    def _subtitle(self, state: str) -> str:
        win = self.win
        errors = sum(win.launch_status.errors(s) for s in ("server", "client"))
        if errors:
            return tr("main.hero_errors", "Ошибок в скриптах: {n}", n=errors)
        if state == "starting":
            return tr("main.hero_prep", "Запаковка модов, затем старт сервера")
        if win.server_running() and not win.client_running() and self._sides == SIDES_BOTH:
            return tr("main.hero_no_client", "Клиент не запущен — сервер не тронут")
        if win.server_running() or win.client_running():
            return ""
        return tr("main.hero_ready", "Готов к запуску")

    def _summaries(self) -> None:
        """Итог в шапке каждой свёрнутой карточки — иначе сворачивание прячет
        состояние, и человек запускает, не зная, что запаковка выключена."""
        preset = getattr(self.win, "current", None)
        mods = len(preset.mods) + len(preset.server_mods) if preset else 0
        self.mods_card.set_summary(
            tr("main.sum_mods", "подключено модов: {n}", n=mods) if mods
            else tr("main.sum_no_mods", "моды не подключены"))

        engine = self.pack_engine.currentText()
        self.pack_card.set_summary(engine)
        branch = self.branch_combo.currentText()
        mode = preset.mode if preset else ""
        self.setup_card.set_summary(
            tr("main.sum_setup", "{b} · {m} · параметры и конфиг", b=branch, m=mode)
            if mode else branch)

    def set_running(self, running: bool) -> None:
        """Пока работа не идёт — нужны настройки; пока идёт — нужен журнал.

        Поэтому карточки сворачиваются сами на время запуска и возвращаются в
        то состояние, в котором были, когда всё остановится.
        """
        if running == self._was_running:
            return
        cards = [self.mods_card, self.pack_card, self.setup_card]
        if running:
            self._pre_open = [c.is_open() for c in cards]
            for c in cards:
                c.set_open(False)
        else:
            for c, was in zip(cards, self._pre_open or [True] * len(cards)):
                c.set_open(was)
        self._was_running = running
