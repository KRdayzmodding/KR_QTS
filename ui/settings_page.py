"""Страница общих настроек (Fluent)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFileDialog, QScrollArea,
)
from PySide6.QtCore import QTimer, QUrl, QRegularExpression
from PySide6.QtGui import QDesktopServices, QRegularExpressionValidator
from qfluentwidgets import (
    LineEdit, PasswordLineEdit, PlainTextEdit, ComboBox, CheckBox,
    PushButton, PrimaryPushButton, ToolButton, BodyLabel, CaptionLabel,
    SwitchButton, TransparentToolButton, TeachingTip,
    TeachingTipTailPosition, InfoBar, InfoBarPosition,
    FluentIcon as FIF, setTheme, Theme,
)

from pathlib import Path

from core import autodetect, filepatch, steam_urls
from core.i18n import tr, AVAILABLE
from core.settings import (
    Settings, find_pbo_project_exe, check_path, PATH_MISSING, PATH_NOT_INSTALLED,
)
from ui import tokens
from ui.cards import rows_card
from ui.pboproject_dialog import PboProjectDialog
from ui.steamid_list import SteamIdList

_VPP_PASS_MAXLEN = 32

# Компоненты не из Steam: ключ настроек -> (страница загрузки, название).
# Ставятся вручную, так что можем только открыть страницу в браузере.
EXTERNAL_DOWNLOADS: dict[str, tuple[str, str]] = {
    "mikero_tools": ("https://mikero.bytex.digital/Downloads",
                     "Mikero Tools (DePboTools)"),
}


class PathRow(QVBoxLayout):
    """Поле пути + обзор. Для устанавливаемых компонентов (settings_key задан)
    добавляется кнопка «взять недостающее» — видна, только пока путь не заполнен,
    и строка состояния под полем: пока Steam качает компонент, здесь виден
    прогресс, а по завершении путь подставляется сам."""

    def __init__(self, value: str, parent: QWidget, settings_key: str = ""):
        super().__init__()
        self.setSpacing(2)
        self.setContentsMargins(0, 0, 0, 0)
        self.settings_key = settings_key

        row = QHBoxLayout()
        self.edit = LineEdit()
        self.edit.setText(value)
        btn = ToolButton(FIF.FOLDER)

        def browse():
            p = QFileDialog.getExistingDirectory(parent, "", self.edit.text())
            if p:
                self.edit.setText(p)

        btn.clicked.connect(browse)
        row.addWidget(self.edit, 1)
        row.addWidget(btn)

        self.install_btn = make_install_button(parent, settings_key)
        if self.install_btn is not None:
            row.addWidget(self.install_btn)
        self.addLayout(row)

        # Родитель сразу: раскладка ещё не прикреплена к странице, и подпись
        # без родителя, которой скажут показаться, мигнёт отдельным окном.
        self.status = CaptionLabel("", parent)
        self.status.setWordWrap(True)
        self.status.hide()
        self.addWidget(self.status)

        self._dl_text = ""    # «Скачивание началось» от наблюдателя Steam
        self._problem = ""    # результат check_path
        self.edit.textChanged.connect(lambda _t: self.refresh_validity())
        self.refresh_validity()

    def refresh_validity(self) -> None:
        """Подсвечивает путь, если папки нет или программа из неё удалена.

        Сам путь не стираем: диск может быть временно недоступен, а терять
        из-за этого настройку нельзя.
        """
        self._problem = check_path(self.settings_key, self.edit.text().strip())
        self.edit.setError(bool(self._problem))
        if self.install_btn is not None:
            # кнопка установки нужна, пока компонента фактически нет
            self.install_btn.setVisible(not self.edit.text().strip()
                                        or self._problem == PATH_NOT_INSTALLED)
        self._render_status()

    def _render_status(self) -> None:
        if self._dl_text:
            text = self._dl_text          # идущая загрузка важнее старой ошибки
        elif self._problem == PATH_MISSING:
            text = tr("settings.path_missing", "Папки по этому пути нет.")
        elif self._problem == PATH_NOT_INSTALLED:
            # обычно живёт доли секунды: наблюдатель Steam в главном окне
            # увидит это и очистит путь сам. Видно, если приложение запущено
            # без главного окна (мастер) или программу удалили только что.
            text = tr("settings.path_not_installed",
                      "Программы по этому пути нет — осталась только папка.")
        else:
            text = ""
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def set_status(self, text: str) -> None:
        """Статус загрузки Steam — от наблюдателя в главном окне."""
        self._dl_text = text
        self._render_status()

    def text(self) -> str:
        return self.edit.text().strip()


def install_via_steam(parent, appid: str, title: str) -> None:
    """Диалог установки в Steam — только после явного подтверждения:
    steam://install сразу начинает качать, отменять придётся уже в Steam.

    Отдельно проговариваем, что путь подставится сам: иначе непонятно, зачем
    приложение отправило в Steam и что делать после того, как тот докачает.
    """
    from qfluentwidgets import MessageBox
    box = MessageBox(
        tr("steam.install_title", "Установка через Steam"),
        tr("steam.install_confirm",
           "Сейчас откроется Steam и начнётся скачивание «{n}» — он спросит, "
           "в какую библиотеку качать.\n\n"
           "Можно спокойно продолжать работу: приложение само отследит загрузку, "
           "подставит и сохранит путь, когда она завершится.\n\n"
           "Продолжить?", n=title),
        parent.window() if parent else None,
    )
    box.yesButton.setText(tr("common.yes", "Да"))
    box.cancelButton.setText(tr("common.no", "Нет"))
    if box.exec():
        QDesktopServices.openUrl(QUrl(steam_urls.install(appid)))


def make_install_button(parent, settings_key: str):
    """Кнопка «получить недостающее» для поля пути; None — компонент ставится
    вручную и подсказать нечем.

    Steam-компоненты ставятся прямо из приложения (с подтверждением — начнётся
    скачивание), сторонние — открытием страницы загрузки в браузере.
    """
    app = steam_urls.SETTINGS_APPS.get(settings_key)
    if app:
        appid, title = app
        btn = ToolButton(FIF.DOWNLOAD, parent)
        btn.setToolTip(tr("settings.install_via_steam",
                          "Установить «{n}» через Steam", n=title))
        btn.clicked.connect(lambda _=False, a=appid, t=title: install_via_steam(parent, a, t))
        return btn

    ext = EXTERNAL_DOWNLOADS.get(settings_key)
    if ext:
        url, title = ext
        btn = ToolButton(FIF.LINK, parent)
        btn.setToolTip(tr("settings.open_download_page",
                          "Открыть страницу загрузки «{n}»", n=title))
        btn.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
        return btn
    return None


def _qtsctl_command() -> str:
    """Чем звать внешнее управление на этой машине.

    В собранном виде это соседний exe, из исходников — интерпретатор со
    скриптом. Показываем ровно то, что сработает, а не общее «qtsctl»: команда
    отсюда копируется в задачу редактора, и она должна запускаться как есть.
    """
    import sys
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else Path(__file__).resolve().parents[1]
    exe = root / "qtsctl.exe"
    if exe.is_file():
        return f'"{exe}"'
    return f'"{sys.executable}" "{root / "qtsctl.py"}"'


def _cli_examples() -> str:
    """Примеры из той же справки, что показывает qtsctl -help.

    Один источник: расходиться подсказке в окне и справке в консоли нельзя.
    """
    from core import clihelp
    return "\n".join(cmd for _key, _caption, cmd in clihelp._EXAMPLES)


class SettingsPage(QScrollArea):
    def __init__(self, settings: Settings, on_saved=None, is_busy=None):
        super().__init__()
        self.settings = settings
        self.on_saved = on_saved
        self._save_timer = None
        # «занято ли» — спрашиваем у главного окна: расположение файлов нельзя
        # менять при живом сервере, он держит профиль открытым
        self.is_busy = is_busy
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setStyleSheet("QScrollArea{background:transparent;} QWidget#settingsInner{background:transparent;}")

        inner = QWidget()
        inner.setObjectName("settingsInner")
        self.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)

        self.sections: list = []

        def section(title: str, icon=FIF.SETTING, summary: str = "") -> QFormLayout:
            """Сворачиваемая карточка раздела; возвращает её форму для полей.

            Раньше разделы стояли развёрнутыми один под другим: семь штук,
            две с половиной тысячи пикселей, и нужную строку искали
            прокруткой. Теперь по умолчанию свёрнуты все — видно оглавление,
            и до любого раздела один щелчок. Итог в шапке говорит, что
            внутри, иначе сворачивание прячет информацию, а не экономит
            место.
            """
            holder = QWidget()
            f = QFormLayout(holder)
            f.setContentsMargins(0, 0, 0, 0)
            f.setSpacing(8)
            card = rows_card(icon, title, summary, [holder])
            card.set_open(False)
            layout.addWidget(card)
            self.sections.append(card)
            return f

        # ------------------------------------------------------------ Общее
        form_general = section(tr("settings.section_general", "Общее"), FIF.SETTING,
                               tr("settings.section_general_sum", "язык, тема, запуск и закрытие окна"))
        self.lang = ComboBox()
        for code, label in AVAILABLE.items():
            self.lang.addItem(label, userData=code)
        codes = list(AVAILABLE)
        self.lang.setCurrentIndex(codes.index(settings.language)
                                  if settings.language in codes else 0)
        form_general.addRow(BodyLabel(tr("settings.language", "Язык (нужен перезапуск)")), self.lang)

        self.project_prefix = LineEdit()
        self.project_prefix.setText(settings.project_prefix)
        self.project_prefix.setPlaceholderText(tr("settings.prefix_ph", "Например: KR"))
        self.project_prefix.setToolTip(tr("settings.prefix_tip",
                                          "Подставляется в hostname создаваемых серверов."))
        form_general.addRow(BodyLabel(tr("settings.prefix_label", "Префикс проекта")), self.project_prefix)

        self.theme = ComboBox()
        self.theme.addItem(tr("settings.theme_auto", "Как в системе"), userData="auto")
        self.theme.addItem(tr("settings.theme_light", "Светлая"), userData="light")
        self.theme.addItem(tr("settings.theme_dark", "Тёмная"), userData="dark")
        theme_codes = ["auto", "light", "dark"]
        self.theme.setCurrentIndex(theme_codes.index(settings.theme)
                                   if settings.theme in theme_codes else 0)
        self.theme.currentIndexChanged.connect(self._theme_changed)
        form_general.addRow(BodyLabel(tr("settings.theme_label", "Тема оформления")), self.theme)

        # Сетевой запрос при старте должен быть отключаемым: у части людей
        # рабочая машина без интернета, и молчаливый поход наружу их нервирует.
        upd_row = QHBoxLayout()
        # Тумблер, а не галка: это состояние программы, а не пункт в наборе.
        self.check_updates = SwitchButton()
        self.check_updates.setOnText(tr("settings.check_updates_on", "Проверять"))
        self.check_updates.setOffText(tr("settings.check_updates_off", "Не проверять"))
        self.check_updates.setChecked(settings.check_updates)
        b_check_now = PushButton(FIF.SYNC, tr("settings.check_now", "Проверить сейчас"))
        b_check_now.clicked.connect(self._check_updates_now)
        upd_row.addWidget(self.check_updates)
        upd_row.addStretch(1)
        upd_row.addWidget(b_check_now)
        form_general.addRow(BodyLabel(tr("settings.updates_label", "Обновления")), upd_row)

        # ------------------------------------------------- Клиент и сервер
        self.stop_method = ComboBox()
        self.stop_method.addItem(tr("settings.stop_soft", "Мягко"), userData="soft")
        self.stop_method.addItem(tr("settings.stop_hard", "Принудительно"), userData="hard")
        idx = self.stop_method.findData(settings.stop_method)
        self.stop_method.setCurrentIndex(max(idx, 0))
        self.stop_method.setToolTip(tr(
            "settings.stop_method_tip",
            "Мягкий способ даёт серверу завершиться своим порядком и сохранить "
            "данные; жёсткий обрывает его сразу."))
        form_general.addRow(BodyLabel(tr("settings.stop_method",
                                         "Остановка сервера и клиента")),
                            self.stop_method)

        # Автозапуск: правда о нём — в реестре, а не в настройках. Ключ могли
        # снять снаружи (чистилками автозагрузки, другой копией программы), и
        # галка, показывающая сохранённое желание вместо факта, врала бы.
        from core import autostart
        self.start_with_windows = CheckBox(tr("settings.start_with_windows",
                                              "Запускать вместе с Windows"))
        self.start_with_windows.setChecked(autostart.enabled())
        self.start_with_windows.setToolTip(tr(
            "settings.start_with_windows_tip",
            "Программа поднимется сама после входа в систему. Пресеты с галкой "
            "«Запускать сервер при старте программы» стартуют вместе с ней."))
        form_general.addRow(BodyLabel(""), self.start_with_windows)

        self.start_mode = ComboBox()
        self.start_mode.addItem(tr("settings.start_window", "Обычным окном"), userData="window")
        self.start_mode.addItem(tr("settings.start_tray", "Свернуть в трей"), userData="tray")
        self.start_mode.addItem(tr("settings.start_mini", "Мини-окном"), userData="mini")
        idx = self.start_mode.findData(getattr(settings, "start_mode", "window"))
        self.start_mode.setCurrentIndex(max(idx, 0))
        form_general.addRow(BodyLabel(tr("settings.start_mode", "Как показываться при запуске")),
                            self.start_mode)

        # Тумблер, а не галка, по той же причине, что у проверки обновлений:
        # это состояние программы. Подписи называют, что произойдёт, — иначе
        # «включено» пришлось бы расшифровывать в голове.
        self.close_quits = SwitchButton()
        self.close_quits.setOnText(tr("settings.close_quits_on", "Закрывает программу"))
        self.close_quits.setOffText(tr("settings.close_quits_off", "Сворачивает в мини-окно"))
        self.close_quits.setChecked(settings.close_quits)
        self.close_quits.setToolTip(tr(
            "settings.close_quits_tip",
            "Мини-окно удобно, пока правишь мод: программа под рукой, но не "
            "занимает экран. Если она нужна только на время запуска, пусть "
            "крестик закрывает её совсем. Выход из трея работает в любом случае."))
        form_general.addRow(BodyLabel(tr("settings.close_quits", "Крестик окна")),
                            self.close_quits)

        form_paths = section(tr("settings.section_paths", "Клиент и сервер"), FIF.FOLDER,
                               tr("settings.section_paths_sum", "где стоят игра, сервер и инструменты"))
        self.p_client = PathRow(settings.client_stable, self, "client_stable")
        self.p_client_exp = PathRow(settings.client_exp, self, "client_exp")
        self.p_server = PathRow(settings.server_stable, self, "server_stable")
        self.p_server_exp = PathRow(settings.server_exp, self, "server_exp")
        self.p_tools = PathRow(settings.dayz_tools, self, "dayz_tools")
        self.p_tools_exp = PathRow(settings.dayz_tools_exp, self, "dayz_tools_exp")
        form_paths.addRow(BodyLabel(tr("settings.client", "DayZ")), self.p_client)
        form_paths.addRow(BodyLabel(tr("settings.server", "DayZ Server")), self.p_server)
        form_paths.addRow(BodyLabel(tr("settings.client_exp", "DayZ Experimental")), self.p_client_exp)
        form_paths.addRow(BodyLabel(tr("settings.server_exp", "DayZ Server Experimental")),
                          self.p_server_exp)

        self.workshop = PlainTextEdit()
        self.workshop.setPlainText("\n".join(settings.workshop_dirs))
        self.workshop.setMaximumHeight(64)
        self.workshop.setToolTip(tr("settings.workshop_tip",
                                    "Папки steamapps/workshop/content/221100 — по одной на строку."))
        form_paths.addRow(BodyLabel(tr("settings.workshop", "Steam Workshop")), self.workshop)

        form_paths.addRow(BodyLabel(tr("settings.dayz_tools", "DayZ Tools")), self.p_tools)
        form_paths.addRow(BodyLabel(tr("settings.dayz_tools_exp", "DayZ Tools Experimental")),
                          self.p_tools_exp)

        self.p_downloads = PathRow(settings.downloads_dir, self)
        self.p_downloads.edit.setPlaceholderText(tr("settings.downloads_ph",
                                                    "<папка программы>\\downloads"))
        self.p_downloads.edit.setToolTip(tr("settings.downloads_tip",
                                            "Общее хранилище скачанных модов карт; во все корни "
                                            "они подключаются junction-ссылками."))
        form_paths.addRow(BodyLabel(tr("settings.downloads", "Папка для загрузок")), self.p_downloads)

        # Внизу блока: это не путь к установке, а раскладка внутри неё —
        # производное от путей выше, и стоять оно должно после них. Отдельным
        # окном, потому что смена тянет за собой переезд файлов.
        b_paths = PushButton(FIF.FOLDER, tr("settings.paths_btn",
                                            "Расположение проектных папок…"))
        b_paths.setToolTip(tr("settings.paths_tip",
                              "Куда приложение кладёт конфиги, профили, миссии "
                              "и ссылки на моды внутри корня игры."))
        b_paths.clicked.connect(self._open_paths)
        self.b_paths = b_paths
        form_paths.addRow("", b_paths)

        # ------------------------------------------------------------ Steam
        form_steam = section(tr("settings.section_steam", "Steam"), FIF.PEOPLE,
                               tr("settings.section_steam_sum", "админские SteamID, пароль VPPA, ключ API"))
        # ключ берём с живого поля: его могли вписать только что, не сохранив
        self.admin_ids = SteamIdList(list(settings.admin_steamids),
                                     lambda: self.steam_key.text().strip())
        self.admin_ids.setToolTip(tr("settings.admins_tip",
                                     "SteamID64 админов. Используется модами-админками."))
        form_steam.addRow(BodyLabel(tr("settings.admins", "Админские SteamID")), self.admin_ids)

        self.admin_pass = PasswordLineEdit()
        self.admin_pass.setMaxLength(_VPP_PASS_MAXLEN)
        # только печатные ASCII без пробела и кавычки: пароль уходит в кавычках
        # в serverDZ.cfg, а кириллицу VPPAdminTools не понимает
        self.admin_pass.setValidator(QRegularExpressionValidator(
            QRegularExpression(rf"[!#-~]{{0,{_VPP_PASS_MAXLEN}}}")))
        self.admin_pass.setText(settings.admin_password)
        self.admin_pass.setToolTip(tr("settings.admin_pass_tip",
                                      "До 32 символов, латиница/цифры/знаки — без кириллицы и "
                                      "пробелов. Пустое поле — вход в админку без пароля "
                                      "(vppDisablePassword = 1 в serverDZ.cfg)."))
        form_steam.addRow(BodyLabel(tr("settings.admin_pass", "Пароль VPPA (необязательно)")),
                          self.admin_pass)

        steam_row = QHBoxLayout()
        self.steam_key = PasswordLineEdit()
        self.steam_key.setText(settings.steam_api_key)
        btn_get_key = PushButton(FIF.LINK, tr("settings.steam_key_get", "Получить"))
        btn_get_key.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl("https://steamcommunity.com/dev/apikey")))
        steam_row.addWidget(self.steam_key, 1)
        steam_row.addWidget(btn_get_key)
        form_steam.addRow(BodyLabel(tr("settings.steam_key",
                                       "Steam API-ключ (необязательно)")), steam_row)
        steam_hint = CaptionLabel(tr(
            "settings.steam_key_hint",
            "Не обязателен: зависимости модов и SteamID по ссылке определяются и без него — "
            "чтением страниц Steam. Ключ делает это быстрее и надёжнее (страницы Valve может "
            "в любой момент переверстать, а контракт API стабилен). Как получить: нажмите "
            "«Получить», войдите в Steam, в поле «Domain Name» впишите что угодно "
            "(например, localhost), согласитесь с условиями и скопируйте ключ сюда."))
        steam_hint.setWordWrap(True)
        form_steam.addRow("", steam_hint)

        # ------------------------------------------------------------ Запаковка
        form_pack = section(tr("settings.section_pack", "Запаковка модов"), FIF.ZIP_FOLDER,
                               tr("settings.section_pack_sum", "чем паковать PBO, ключ подписи"))
        self._pack_flags = settings.pack_flags
        self._clean_meta = settings.clean_meta

        # Первым — чем паковать: от этого зависит всё остальное в разделе.
        # Настройки чужого упаковщика не должны висеть там, где он не
        # используется: человек читает их как «надо заполнить» и заполняет.
        self.pack_tool = ComboBox()
        self.pack_tool.addItem(tr("settings.tool_pboproject", "Mikero pboProject"),
                               userData="pboproject")
        self.pack_tool.addItem(tr("settings.tool_krbuild", "[KR] Project Builder"),
                               userData="krbuild")
        idx_tool = self.pack_tool.findData(getattr(settings, "pack_tool", "pboproject"))
        self.pack_tool.setCurrentIndex(max(idx_tool, 0))
        self.pack_tool.setToolTip(tr(
            "settings.tool_tip",
            "Чем собирать PBO. Движок выбирается один на проект: у обоих свой "
            "учёт изменений и общая папка temp, и чередование заставило бы "
            "каждый пересобирать за другим."))
        form_pack.addRow(BodyLabel(tr("settings.tool_label", "Чем паковать")),
                         self.pack_tool)

        # --- настройки pboProject: путь к Mikero, ключ подписи, окно флагов
        self.pbo_box = QWidget()
        pbo_form = QFormLayout(self.pbo_box)
        pbo_form.setContentsMargins(0, 0, 0, 0)
        pbo_form.setSpacing(8)
        self.p_mikero = PathRow(settings.mikero_tools, self, "mikero_tools")
        pbo_form.addRow(BodyLabel(tr("settings.mikero", "Mikero Tools (DePboTools)")),
                        self.p_mikero)
        mikero_hint = CaptionLabel(tr("settings.mikero_hint",
                                      "pboProject входит в состав Mikero Tools и требует "
                                      "установленных DayZ Tools — без них бинаризация не работает."))
        mikero_hint.setWordWrap(True)
        pbo_form.addRow("", mikero_hint)

        # Ключ подписи здесь, а не общей строкой: pboProject принимает его
        # флагом запуска, а Project Builder — только из своих настроек,
        # ключа командной строки у него нет. Общее поле обещало бы то, чего
        # для второго движка мы сделать не можем.
        key_row = QHBoxLayout()
        key_row.setSpacing(4)
        self.sign_key = LineEdit()
        self.sign_key.setText(getattr(settings, "sign_key", ""))
        self.sign_key.setPlaceholderText(tr("settings.sign_key_ph",
                                            "PBO не подписываются"))
        b_key_pick = ToolButton(FIF.FOLDER)
        b_key_pick.setToolTip(tr("settings.sign_key_pick", "Выбрать файл ключа"))
        b_key_pick.clicked.connect(self._pick_sign_key)
        self.b_key_new = PushButton(FIF.ADD, tr("settings.sign_key_new", "Создать…"))
        self.b_key_new.clicked.connect(self._create_sign_key)
        key_row.addWidget(self.sign_key, 1)
        key_row.addWidget(b_key_pick)
        key_row.addWidget(self.b_key_new)
        pbo_form.addRow(BodyLabel(tr("settings.sign_key", "Ключ подписи")), key_row)
        key_hint = CaptionLabel(tr(
            "settings.sign_key_hint",
            "Закрытый ключ (.biprivatekey), которым подписываются собранные "
            "PBO. Открытую половину (.bikey) нужно положить в папку keys "
            "сервера, иначе он подписанные моды не примет. Пусто — не "
            "подписывать."))
        key_hint.setWordWrap(True)
        pbo_form.addRow("", key_hint)

        self.b_pbo_settings = PushButton(FIF.SETTING,
                                         tr("settings.pbo_settings", "Настройки PboProject"))
        self.b_pbo_settings.clicked.connect(self._open_pbo_settings)
        pbo_form.addRow(BodyLabel(tr("settings.pbo_settings_label", "Запаковка PBO")),
                        self.b_pbo_settings)
        form_pack.addRow(self.pbo_box)

        # --- настройки Project Builder: путь и кнопка в его собственное окно
        self.krbuild_box = QWidget()
        kb_form = QFormLayout(self.krbuild_box)
        kb_form.setContentsMargins(0, 0, 0, 0)
        kb_form.setSpacing(8)
        self.p_krbuild = PathRow(getattr(settings, "krbuild_exe", ""), self)
        kb_form.addRow(BodyLabel(tr("settings.krbuild", "Папка Dev Toolkit")),
                       self.p_krbuild)
        krbuild_hint = CaptionLabel(tr(
            "settings.krbuild_hint",
            "Можно не заполнять: установленный [KR] Dev Toolkit программа "
            "находит сама. Папка нужна, только если держите его отдельной "
            "копией — запаковщик и окно настроек найдутся в ней по вложенным "
            "папкам. В поставку он не входит, это отдельная программа."))
        krbuild_hint.setWordWrap(True)
        kb_form.addRow("", krbuild_hint)

        # Что нашлось по указанной папке. Без этой строки поле молчит: папка
        # указана, а нашлась программа или нет — никак не узнать, пока не
        # дойдёшь до запаковки. Человек в такой тишине решает, что не видит.
        self.krbuild_found = CaptionLabel("")
        self.krbuild_found.setWordWrap(True)
        kb_form.addRow("", self.krbuild_found)

        # Следующий шаг там же, где отказ. Выбрать этот движок без тулкита
        # можно, а собрать им нельзя — и человек остаётся с «не установлен»
        # и без способа это исправить. Кнопка живёт только в этом состоянии.
        self.b_toolkit_get = PrimaryPushButton(
            FIF.DOWNLOAD, tr("settings.toolkit_get", "Скачать и установить"))
        self.b_toolkit_get.clicked.connect(self._install_toolkit)
        kb_form.addRow("", self.b_toolkit_get)
        self.b_toolkit_get.setVisible(False)
        self._krbuild_timer = QTimer(self)
        self._krbuild_timer.setSingleShot(True)
        self._krbuild_timer.setInterval(400)    # не искать на каждую букву
        self._krbuild_timer.timeout.connect(self._show_krbuild_found)
        self.p_krbuild.edit.textChanged.connect(self._krbuild_timer.start)
        # И сохраняем по ходу: путь сюда чаще вставляют, а не допечатывают,
        # и ждать ухода фокуса, чтобы настройка «вступила в силу», незачем.
        self.p_krbuild.edit.textChanged.connect(self._save_later)
        self.b_krbuild_settings = PushButton(FIF.SETTING,
                                             tr("settings.krbuild_settings",
                                                "Настройки Project Builder"))
        self.b_krbuild_settings.clicked.connect(self._open_krbuild_settings)
        kb_form.addRow(BodyLabel(tr("settings.krbuild_settings_label", "Сборка")),
                       self.b_krbuild_settings)
        kb_hint = CaptionLabel(tr(
            "settings.krbuild_own_hint",
            "Проверки, исправления, подпись и ключ у Project Builder свои — они "
            "задаются в его окне, а не здесь."))
        kb_hint.setWordWrap(True)
        kb_form.addRow("", kb_hint)
        form_pack.addRow(self.krbuild_box)

        self.pack_tool.currentIndexChanged.connect(self._tool_changed)

        self.pack_engine = ComboBox()
        self.pack_engine.addItem(tr("settings.engine_normal",
                                    "Обычная — переиспользует temp"), userData="normal")
        self.pack_engine.addItem(tr("settings.engine_full",
                                    "Полная (FullBuild) — чистит temp"), userData="full")
        self.pack_engine.setCurrentIndex(1 if settings.pack_engine == "full" else 0)
        self.pack_engine.setToolTip(tr("settings.engine_tip",
                                       "Обычная переиспользует содержимое temp и собирает за "
                                       "секунды; полная чистит temp и пересобирает всё."))
        form_pack.addRow(BodyLabel(tr("settings.engine_label", "Способ запаковки модов")), self.pack_engine)

        self._tool_changed()
        self._show_krbuild_found()

        # «полная» запаковка зависит и от pboProject, и от DayZ Tools
        self.p_mikero.edit.textChanged.connect(self._update_pbo_button_state)
        self.p_tools.edit.textChanged.connect(self._update_pbo_button_state)
        self._update_pbo_button_state()

        # ---------------------------------------------------- Filepatching
        # -------------------------------------------- Обновление модов
        form_upd = section(tr("settings.section_modupd", "Обновление модов"), FIF.UPDATE,
                               tr("settings.section_modupd_sum", "проверка и докачка модов мастерской"))

        upd_note = CaptionLabel(tr(
            "settings.modupd_note",
            "Сервер, поднятый со старым модом, ведёт себя необъяснимо: скрипты "
            "и конфиги не те, а в логах об этом ни слова. Мод, который Steam "
            "качает прямо сейчас, ещё хуже — в игру уезжает половина файлов. "
            "Состояние спрашивается у самого Steam, сеть для этого не нужна."))
        upd_note.setWordWrap(True)
        form_upd.addRow("", upd_note)

        # Тумблер, а не галка: это состояние системы, а не включение в набор.
        self.mod_update_before_launch = SwitchButton()
        self.mod_update_before_launch.setOnText("")
        self.mod_update_before_launch.setOffText("")
        self.mod_update_before_launch.setChecked(settings.mod_update_before_launch)
        form_upd.addRow(BodyLabel(tr("settings.modupd_on",
                                     "Проверять моды перед запуском")),
                        self.mod_update_before_launch)

        # «Включено ли» и «каким способом» — разные вопросы и разные контролы:
        # сведённые в один список, они опять слипнутся, как это было у запаковки.
        self.mod_update_method = ComboBox()
        self.mod_update_method.addItem(tr("settings.modupd_wait",
                                          "Ждать, пока Steam обновит сам"),
                                       userData="wait")
        self.mod_update_method.addItem(tr("settings.modupd_cmd",
                                          "Скачать через SteamCMD"),
                                       userData="steamcmd")
        idx = self.mod_update_method.findData(settings.mod_update_method)
        self.mod_update_method.setCurrentIndex(max(idx, 0))
        self.mod_update_method.currentIndexChanged.connect(self._modupd_method_changed)
        form_upd.addRow(BodyLabel(tr("settings.modupd_how", "Способ")),
                        self.mod_update_method)

        self.steamcmd_exe = LineEdit()
        self.steamcmd_exe.setText(settings.steamcmd_exe)
        self.steamcmd_exe.setPlaceholderText("steamcmd.exe")
        b_cmd = ToolButton(FIF.FOLDER)

        def pick_steamcmd():
            p, _ = QFileDialog.getOpenFileName(
                self, tr("settings.modupd_pick", "Где лежит steamcmd.exe"),
                self.steamcmd_exe.text(), "steamcmd.exe;;*.exe")
            if p:
                self.steamcmd_exe.setText(p)

        b_cmd.clicked.connect(pick_steamcmd)
        cmd_row = QHBoxLayout()
        cmd_row.addWidget(self.steamcmd_exe, 1)
        cmd_row.addWidget(b_cmd)
        self.row_steamcmd = BodyLabel(tr("settings.modupd_exe", "SteamCMD"))
        form_upd.addRow(self.row_steamcmd, cmd_row)

        self.steam_login = LineEdit()
        self.steam_login.setText(settings.steam_login)
        self.steam_login.setPlaceholderText(tr("settings.modupd_login_ph",
                                               "Имя учётной записи Steam"))
        self.row_login = BodyLabel(tr("settings.modupd_login", "Учётная запись"))
        form_upd.addRow(self.row_login, self.steam_login)

        self.login_note = CaptionLabel(tr(
            "settings.modupd_login_note",
            "Только имя. Пароль SteamCMD запоминает сам после первого ручного "
            "запуска — запустите его один раз и войдите. Анонимный вход к "
            "мастерской DayZ доступа не даёт: нужен аккаунт, владеющий игрой."))
        self.login_note.setWordWrap(True)
        form_upd.addRow("", self.login_note)

        self.mod_update_timeout_min = ComboBox()
        for minutes in (5, 10, 15, 30, 60):
            self.mod_update_timeout_min.addItem(
                tr("settings.modupd_min", "{n} мин", n=minutes), userData=minutes)
        idx = self.mod_update_timeout_min.findData(settings.mod_update_timeout_min)
        self.mod_update_timeout_min.setCurrentIndex(max(idx, 0))
        self.mod_update_timeout_min.setToolTip(tr(
            "settings.modupd_wait_tip",
            "Сколько ждать, прежде чем отменить запуск и сказать об этом."))
        form_upd.addRow(BodyLabel(tr("settings.modupd_wait_for", "Ждать не дольше")),
                        self.mod_update_timeout_min)
        self._modupd_method_changed()

        form_fp = section(tr("settings.section_filepatch", "Filepatching"), FIF.LINK,
                               tr("settings.section_filepatch_sum", "ссылки на папки скриптов для правок на лету"))
        fp_row = QHBoxLayout()
        self.b_fp_add = PushButton(FIF.LINK, tr("filepatch.add", "Создать симлинк"))
        self.b_fp_add.clicked.connect(self._filepatch_add)
        self.b_fp_help = TransparentToolButton(FIF.HELP)
        self.b_fp_help.setToolTip(tr("filepatch.help_tip", "Для чего это нужно"))
        self.b_fp_help.clicked.connect(self._show_filepatch_help)
        fp_row.addWidget(self.b_fp_add)
        fp_row.addWidget(self.b_fp_help)
        fp_row.addStretch(1)
        form_fp.addRow("", fp_row)

        fp_row2 = QHBoxLayout()
        self.b_fp_sync = PushButton(FIF.SYNC, tr("filepatch.sync", "Обновить ссылки"))
        self.b_fp_sync.setToolTip(tr("filepatch.sync_tip",
                                     "Досоздаёт недостающие ссылки во всех корнях и убирает те, "
                                     "чья папка на диске P: пропала."))
        self.b_fp_sync.clicked.connect(self._filepatch_sync)
        self.b_fp_clear = PushButton(FIF.DELETE, tr("filepatch.clear", "Удалить все Simlink"))
        self.b_fp_clear.setToolTip(tr("filepatch.clear_tip",
                                      "Снимает только ссылки, созданные этой кнопкой. "
                                      "Моды и прочее содержимое каталогов не трогает."))
        self.b_fp_clear.clicked.connect(self._filepatch_clear)
        fp_row2.addWidget(self.b_fp_sync)
        fp_row2.addWidget(self.b_fp_clear)
        fp_row2.addStretch(1)
        form_fp.addRow("", fp_row2)

        self.fp_status = CaptionLabel("")
        self.fp_status.setWordWrap(True)
        form_fp.addRow("", self.fp_status)
        self._update_filepatch_status()

        # ------------------------------------------- Внешнее управление
        form_cli = section(tr("settings.section_cli", "Внешнее управление"), FIF.COMMAND_PROMPT,
                               tr("settings.section_cli_sum", "команды снаружи: qtsctl и задачи редактора"))

        cli_note = CaptionLabel(tr(
            "settings.cli_note",
            "Сторонние инструменты и задачи редактора могут запускать сервер и "
            "клиент, паковать моды и получать отчёт — не открывая это окно. "
            "Канал персональный: другой пользователь машины до него не "
            "достучится."))
        cli_note.setWordWrap(True)
        form_cli.addRow("", cli_note)

        self.external_control = CheckBox(tr("settings.cli_enabled",
                                            "Отвечать на команды извне"))
        self.external_control.setChecked(settings.external_control)
        form_cli.addRow("", self.external_control)

        # Только чтение, а не выключенное поле: выключенное нельзя ни прочитать,
        # ни скопировать, а копировать это и нужно.
        self.cli_command = LineEdit()
        self.cli_command.setText(_qtsctl_command())
        self.cli_command.setReadOnly(True)
        cli_row = QHBoxLayout()
        cli_row.addWidget(self.cli_command, 1)
        b_copy_cmd = ToolButton(FIF.COPY)
        b_copy_cmd.setToolTip(tr("common.copy", "Скопировать"))
        b_copy_cmd.clicked.connect(lambda: self._copy(self.cli_command.text()))
        cli_row.addWidget(b_copy_cmd)
        form_cli.addRow(BodyLabel(tr("settings.cli_command", "Команда")), cli_row)

        self.cli_examples = PlainTextEdit()
        self.cli_examples.setPlainText(_cli_examples())
        self.cli_examples.setReadOnly(True)
        # Без переноса: команду переносить нельзя — она копируется целиком, а
        # разорванная пополам читается как две разные. Длинные уезжают вбок.
        self.cli_examples.setLineWrapMode(PlainTextEdit.LineWrapMode.NoWrap)
        self.cli_examples.setFixedHeight(132)
        form_cli.addRow(BodyLabel(tr("settings.cli_examples", "Примеры")),
                        self.cli_examples)

        cli_btns = QHBoxLayout()
        b_copy_ex = PushButton(FIF.COPY, tr("settings.cli_copy",
                                            "Скопировать примеры"))
        b_copy_ex.clicked.connect(lambda: self._copy(self.cli_examples.toPlainText()))
        cli_btns.addWidget(b_copy_ex)
        cli_btns.addStretch(1)
        form_cli.addRow("", cli_btns)

        cli_help = CaptionLabel(tr(
            "settings.cli_help_note",
            "Полная справка со всеми аргументами — «qtsctl -help», "
            "по разделам: -help mods, -help pack, -help params, -help exit."))
        cli_help.setWordWrap(True)
        form_cli.addRow("", cli_help)

        btns = QHBoxLayout()
        btn_detect = PushButton(FIF.SEARCH, tr("settings.autodetect",
                                               "Автопоиск незаполненных путей"))
        btn_detect.clicked.connect(self._autodetect)
        # Кнопки «Сохранить» нет: настройки записываются при изменении. Но
        # молчать об этом нельзя — привычка искать кнопку сильнее, чем вера в
        # то, что всё уже сохранено.
        self.unsaved = BodyLabel(tr("settings.autosaved",
                                    "Изменения сохраняются сразу"))
        btns.addWidget(btn_detect)
        btns.addStretch(1)
        btns.addWidget(self.unsaved)
        layout.addLayout(btns)

        self.note = CaptionLabel("")
        layout.addWidget(self.note)
        layout.addStretch(1)

        # Подписываемся на все поля разом: перечислять сигналы по одному —
        # верный способ забыть новое поле и получить молча неверный индикатор.
        for widget in (self.lang, self.pack_engine, self.theme, self.stop_method,
                       self.start_mode, self.mod_update_method,
                       self.mod_update_timeout_min, self.pack_tool):
            widget.currentIndexChanged.connect(lambda _i: self._save())
        # Тумблеры и галки шлют разные сигналы — подключаемся по тому, какой
        # у виджета есть, чтобы новое поле нельзя было забыть привязать.
        for widget in (self.check_updates, self.mod_update_before_launch,
                       self.external_control, self.start_with_windows,
                       self.close_quits):
            signal = (getattr(widget, "checkedChanged", None)
                      or getattr(widget, "toggled", None))
            signal.connect(lambda _v: self._save())
        # Печатают руками — пишем по окончании ввода, а не по букве.
        for widget in (self.project_prefix, self.admin_pass, self.steam_key,
                       self.steamcmd_exe, self.steam_login, self.sign_key):
            widget.editingFinished.connect(self._save)
        self.workshop.textChanged.connect(self._save_later)
        self.admin_ids.changed.connect(lambda: self._save())
        for row in (self.p_client, self.p_client_exp, self.p_server, self.p_server_exp,
                    self.p_mikero, self.p_krbuild, self.p_tools, self.p_tools_exp,
                    self.p_downloads):
            row.edit.editingFinished.connect(self._save)

        # Слежением за загрузками Steam владеет главное окно: качать можно
        # несколько компонентов сразу и уйти с этой страницы, а уведомление и
        # запись пути должны прийти всё равно. Здесь только отображение.
        self._path_rows = {
            "client_stable": self.p_client, "client_exp": self.p_client_exp,
            "server_stable": self.p_server, "server_exp": self.p_server_exp,
            "dayz_tools": self.p_tools, "dayz_tools_exp": self.p_tools_exp,
        }

    # ------------------------------------------------------- загрузки Steam

    def set_path_status(self, key: str, text: str) -> None:
        """Подпись под полем пути («Скачивание началось» либо пусто).

        Заодно перепроверяем сам путь: сигнал приходит и когда компонент
        удалили из Steam — тогда поле должно подсветиться, а кнопка установки
        вернуться.
        """
        row = self._path_rows.get(key)
        if row is not None:
            row.set_status(text)
            row.refresh_validity()

    def set_path_value(self, key: str, path: str, force: bool = False) -> None:
        """Подставляет путь, если поле пустое. Заполненное не трогаем — там мог
        быть ручной путь; force перезаписывает (компонент удалён — чистим поле).

        Нужно даже когда страница не открыта: иначе следующее нажатие
        «Сохранить» перезаписало бы значение тем, что осталось в виджете.
        """
        row = self._path_rows.get(key)
        if row is None or (not path and not force):
            return
        row.set_status("")
        if force or not row.text():
            row.edit.setText(path)

    def refresh_locks(self) -> None:
        """Пока что-то запущено, менять расположение файлов нельзя: сервер
        держит профиль открытым, а подхват после переезда его не узнает."""
        if getattr(self, "b_paths", None) is None:
            return
        busy = bool(self.is_busy and self.is_busy())
        self.b_paths.setEnabled(not busy)
        self.b_paths.setToolTip(
            tr("settings.paths_locked",
               "Недоступно, пока запущен сервер или клиент.") if busy
            else tr("settings.paths_tip",
                    "Куда приложение кладёт конфиги, профили, миссии "
                    "и ссылки на моды внутри корня игры."))

    def _open_paths(self) -> None:
        """Окно расположения файлов. Оно само переносит и само сохраняет —
        страница настроек в это не вмешивается."""
        from ui.paths_dialog import PathsDialog
        dlg = PathsDialog(self.settings, self)
        if dlg.exec() and dlg.changed and self.on_saved:
            self.on_saved()

    def _check_updates_now(self) -> None:
        """Проверка по кнопке — идёт через главное окно: там же живёт пункт
        в навигации, который надо обновить, и уже скачанное состояние."""
        win = self.window()
        if hasattr(win, "check_updates_now"):
            win.check_updates_now()

    def _theme_changed(self, _idx: int) -> None:
        code = self.theme.currentData()
        setTheme({"light": Theme.LIGHT, "dark": Theme.DARK, "auto": Theme.AUTO}
                .get(code, Theme.AUTO))
        self.settings.theme = code
        self.settings.save()

    def _autodetect(self) -> None:
        det = autodetect.detect_all()
        pairs = [
            (self.p_client, det["client_stable"]), (self.p_client_exp, det["client_exp"]),
            (self.p_server, det["server_stable"]), (self.p_server_exp, det["server_exp"]),
            (self.p_mikero, det["mikero_tools"]), (self.p_tools, det["dayz_tools"]),
            (self.p_tools_exp, det["dayz_tools_exp"]),
        ]
        filled = 0
        for row, val in pairs:
            if not row.text() and val:
                row.edit.setText(val)
                filled += 1
        if not self.workshop.toPlainText().strip() and det["workshop_dirs"]:
            self.workshop.setPlainText("\n".join(det["workshop_dirs"]))
            filled += 1
        self.note.setText(tr("settings.detected", "Заполнено полей: {n}", n=filled))

    def _update_pbo_button_state(self) -> None:
        """Доступность настроек pboProject и обоих режимов запаковки.

        Режимы оба идут через pboProject, а он зовёт бинаризатор и конвертеры из
        DayZ Tools — без них падает на бинаризации. Поэтому доступность у них
        общая, и подпись говорит, чего именно не хватает.
        """
        pbo_ok = Path(find_pbo_project_exe(self.p_mikero.text())).is_file()
        tools_ok = bool(self.p_tools.text()) and Path(self.p_tools.text()).is_dir()
        full_ok = pbo_ok and tools_ok

        self.b_pbo_settings.setEnabled(pbo_ok)
        self.b_pbo_settings.setToolTip(
            tr("settings.pbo_settings_tip",
              "Флаги командной строки pboProject: подпись, сжатие, "
              "обработка файлов и т.д. — с пояснениями по каждому.")
            if pbo_ok else
            tr("settings.pbo_settings_missing",
              "pboProject не найден по указанному пути Mikero Tools — "
              "укажите правильный путь, чтобы открыть эти настройки."))

        # Подписи режимов не трогаем: раньше здесь переписывался текст пункта 0,
        # из-за чего «Обычная» превращалась во вторую «Полную» — остаток от
        # времён, когда выбирали между своим пакером и pboProject.
        for i in range(self.pack_engine.count()):
            self.pack_engine.setItemEnabled(i, full_ok)
        if not pbo_ok:
            tip = tr("settings.engine_no_pbo",
                     "Запаковка недоступна: pboProject не найден по указанному пути.")
        elif not tools_ok:
            tip = tr("settings.engine_no_tools",
                     "Запаковка недоступна: не найдены DayZ Tools.")
        else:
            tip = tr("settings.engine_tip",
                     "Обычная переиспользует содержимое temp и собирает за "
                     "секунды; полная чистит temp и пересобирает всё.")
        self.pack_engine.setToolTip(tip)

    def _show_filepatch_help(self) -> None:
        TeachingTip.create(
            target=self.b_fp_help,
            icon=FIF.HELP,
            title=tr("settings.section_filepatch", "Filepatching"),
            content=tr("filepatch.help",
                       "Симлинк нужен для корректной работы filepatching. Filepatching "
                       "позволяет подтягивать скрипты без запаковки PBO — достаточно "
                       "перезапустить клиент и сервер.\n\n"
                       "Для подключения укажите папку скриптов вашего мода на диске P:. "
                       "Дальше ссылки создадутся автоматически везде, где это требуется — "
                       "в клиенте и сервере, stable и Experimental."),
            isClosable=True,
            tailPosition=TeachingTipTailPosition.BOTTOM,
            duration=-1,
            parent=self,
        )

    def _update_filepatch_status(self) -> None:
        lines = filepatch.status_lines(self.settings)
        self.fp_status.setText("\n".join(lines) if lines else
                               tr("filepatch.none", "Симлинки не подключены."))

    def _filepatch_report(self, rep, title: str) -> None:
        """Показывает итог операции. Ошибки важнее — их показываем отдельно."""
        parts = []
        if rep.created:
            parts.append(tr("filepatch.n_created", "создано: {n}", n=len(rep.created)))
        if rep.removed:
            parts.append(tr("filepatch.n_removed", "удалено: {n}", n=len(rep.removed)))
        if rep.kept:
            parts.append(tr("filepatch.n_kept", "уже было: {n}", n=len(rep.kept)))
        if rep.stale:
            parts.append(tr("filepatch.n_stale", "пропавших папок: {n}", n=len(rep.stale)))
        body = ", ".join(parts)

        if rep.failed:
            InfoBar.warning(title=title,
                            content=(body + "\n" if body else "") + "\n".join(rep.failed),
                            parent=self, duration=12000,
                            position=InfoBarPosition.TOP_RIGHT)
        else:
            InfoBar.success(title=title, content=body or tr("filepatch.nothing", "Изменений нет."),
                            parent=self, duration=6000, position=InfoBarPosition.TOP_RIGHT)
        self._update_filepatch_status()

    def _filepatch_add(self) -> None:
        # стартуем прямо с P: — оттуда всё равно только и можно выбирать
        start = "P:\\" if Path("P:\\").is_dir() else ""
        path = QFileDialog.getExistingDirectory(
            self, tr("filepatch.pick", "Папка скриптов мода на диске P:"), start)
        if not path:
            return
        rep, err = filepatch.add(self.settings, path)
        if err:
            InfoBar.error(title=tr("filepatch.add", "Создать симлинк"), content=err,
                          parent=self, duration=10000, position=InfoBarPosition.TOP_RIGHT)
            return
        self._filepatch_report(rep, tr("filepatch.added", "Симлинк подключён"))

    def _filepatch_sync(self) -> None:
        self._filepatch_report(filepatch.sync(self.settings),
                               tr("filepatch.synced", "Ссылки обновлены"))

    def _filepatch_clear(self) -> None:
        if not self.settings.filepatch_links:
            InfoBar.info(title=tr("filepatch.none", "Симлинки не подключены."), content="",
                         parent=self, duration=4000, position=InfoBarPosition.TOP_RIGHT)
            return
        from qfluentwidgets import MessageBox
        box = MessageBox(
            tr("filepatch.clear", "Удалить все Simlink"),
            tr("filepatch.clear_confirm",
               "Снять все ссылки filepatching во всех корнях?\n\n"
               "Сами папки со скриптами на диске P: останутся нетронутыми — "
               "удаляются только ссылки на них."),
            self.window())
        box.yesButton.setText(tr("common.yes", "Да"))
        box.cancelButton.setText(tr("common.no", "Нет"))
        if not box.exec():
            return
        self._filepatch_report(filepatch.remove_all(self.settings),
                               tr("filepatch.cleared", "Симлинки удалены"))

    def _tool_changed(self, *_a) -> None:
        """Показывает настройки только того движка, который выбран."""
        krbuild_chosen = self.pack_tool.currentData() == "krbuild"
        self.pbo_box.setVisible(not krbuild_chosen)
        self.krbuild_box.setVisible(krbuild_chosen)
        if krbuild_chosen:
            # Выбор движка — тот самый момент, когда человек узнаёт, что
            # тулкита нет. Показывать ему состояние, посчитанное при открытии
            # страницы, значит рисковать устаревшим отказом.
            self._show_krbuild_found()

    def _show_krbuild_found(self) -> None:
        """Пишет под полем, что нашлось в указанной папке."""
        from core import krbuild
        # Спрашиваем про то, что введено сейчас, а не про сохранённое:
        # строка должна отвечать на ввод, а не на прошлый сеанс.
        from dataclasses import replace
        typed = self.p_krbuild.text().strip()
        probe = replace(self.settings, krbuild_exe=typed)
        where = probe.krbuild_cli()
        if where:
            gui = krbuild.gui_exe(probe)
            version = krbuild.version_of(where)
            shown = f"{where} ({version})" if version else where
            # Пустое поле и найденная программа — не одно и то же сообщение:
            # человек должен видеть, что путь взялся из установки, а не из
            # его ввода, иначе «я ничего не указывал, а оно работает» читается
            # как ошибка.
            if typed:
                found = tr("settings.krbuild_found", "Нашлось: {p}", p=shown)
            else:
                found = tr("settings.krbuild_auto",
                           "Установленный Dev Toolkit: {p}", p=shown)
            if not gui:
                found += " " + tr("settings.krbuild_no_window",
                                  "Окна настроек рядом нет — кнопка выше не сработает.")
            self.krbuild_found.setText(found)
            role = "success" if gui else "warning"
        elif not typed:
            self.krbuild_found.setText(tr(
                "settings.krbuild_none",
                "Dev Toolkit не установлен. Поставьте его или укажите папку, "
                "если держите отдельной копией."))
            role = "text_dim"
        else:
            self.krbuild_found.setText(tr(
                "settings.krbuild_missing",
                "В этой папке нет запаковщика (ProjectBuilder.exe) — ни в "
                "ней самой, ни во вложенных."))
            role = "error"
        self.krbuild_found.setStyleSheet(f"color:{tokens.color(role)};")
        self.b_toolkit_get.setVisible(not where)

    def _open_krbuild_settings(self) -> None:
        """Открывает окно настроек Project Builder — его, а не наше.

        Проверки, исправления и подпись там свои; повторять их у себя значило
        бы завести второй источник правды для чужой программы.
        """
        import subprocess
        from dataclasses import replace

        from core import krbuild
        # По введённому прямо сейчас, а не по сохранённому: иначе сразу после
        # ввода пути кнопка отвечает «не найдено», пока строка под полем в том
        # же окне пишет «нашлось». Человек верит кнопке и решает, что сломано.
        probe = replace(self.settings, krbuild_exe=self.p_krbuild.text().strip())
        gui = krbuild.gui_exe(probe)
        if not gui:
            InfoBar.warning(
                title=tr("settings.krbuild_no_gui", "Окно Project Builder не найдено"),
                content=tr("settings.krbuild_no_gui_body",
                           "Укажите папку Dev Toolkit — рядом с запаковщиком "
                           "лежит ProjectBuilder_GUI.exe с окном настроек."),
                parent=self.window(), duration=6000,
                position=InfoBarPosition.TOP_RIGHT)
            return
        # Второй раз не запускаем: у чужой программы одно окно настроек, и
        # две копии писали бы в один и тот же build_kit.json — кто последний
        # закрыл, того и настройки.
        from ui.onewindow import raise_process_window
        running = getattr(self, "_krbuild_proc", None)
        if running is not None and running.poll() is None:
            if not raise_process_window(running.pid):
                InfoBar.info(
                    title=tr("settings.krbuild_already", "Окно настроек уже открыто"),
                    content="", parent=self.window(), duration=4000,
                    position=InfoBarPosition.TOP_RIGHT)
            return
        try:
            self._krbuild_proc = subprocess.Popen([gui, "--settings"])
        except OSError as e:
            InfoBar.error(title=tr("settings.krbuild_no_run", "Не удалось открыть"),
                          content=str(e), parent=self.window(), duration=6000,
                          position=InfoBarPosition.TOP_RIGHT)

    def _install_toolkit(self) -> None:
        """Скачивает установщик Dev Toolkit и отдаёт его человеку."""
        from ui.onewindow import show_once
        from ui.toolkit_setup_dialog import ToolkitSetupDialog

        def make():
            dialog = ToolkitSetupDialog(self.window())
            dialog.installed.connect(self._toolkit_installed)
            return dialog

        show_once(self, "toolkit_setup", make)

    def _toolkit_installed(self) -> None:
        """Тулкит поставился — поле с папкой больше не нужно.

        Если там был путь, по которому ничего не нашлось, он теперь мешает:
        указанная папка важнее установки, и человек остался бы с «не нашёлся»
        сразу после удачной установки.
        """
        from dataclasses import replace
        typed = self.p_krbuild.text().strip()
        if typed and not replace(self.settings, krbuild_exe=typed).krbuild_cli():
            self.p_krbuild.edit.setText("")
        self._show_krbuild_found()
        InfoBar.success(
            title=tr("settings.toolkit_ready", "Dev Toolkit установлен"),
            content=tr("settings.toolkit_ready_body",
                       "Запаковщик найден — можно собирать."),
            parent=self.window(), duration=5000,
            position=InfoBarPosition.TOP_RIGHT)

    def _pick_sign_key(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, tr("settings.sign_key_pick", "Выбрать файл ключа"),
            self.sign_key.text(),
            tr("settings.sign_key_filter", "Ключ подписи (*.biprivatekey)"))
        if path:
            self.sign_key.setText(path)
            self._save()

    def _create_sign_key(self) -> None:
        """Заводит пару ключей и сразу подставляет закрытый в поле."""
        from ui.signkey_dialog import SignKeyDialog
        dlg = SignKeyDialog(self.settings, self)
        if not dlg.exec() or not dlg.created:
            return
        self.sign_key.setText(dlg.created)
        self._save()
        from core import signkey
        public = signkey.public_of(dlg.created)
        InfoBar.success(
            title=tr("settings.sign_key_done", "Ключ создан"),
            content=tr("settings.sign_key_done_body",
                       "Открытую половину положите в keys сервера: {p}",
                       p=public or "—"),
            parent=self.window(), duration=8000,
            position=InfoBarPosition.TOP_RIGHT)

    def _open_pbo_settings(self) -> None:
        dlg = PboProjectDialog(self._pack_flags, self._clean_meta, self)
        if dlg.exec():
            self._pack_flags = dlg.result_flags() or Settings().pack_flags
            self._clean_meta = dlg.result_clean_meta()
            self._refresh_dirty()   # диалог сигналов полей не шлёт

    def _form_values(self) -> dict:
        """Что сейчас введено в форме — в терминах полей Settings.

        Один источник и для сохранения, и для проверки несохранённых изменений:
        иначе индикатор рано или поздно разойдётся с тем, что реально пишется.
        local_mods_dirs здесь нет намеренно — это поле редактируется на вкладке
        «Моды», страница настроек его не трогает.
        """
        return {
            "language": self.lang.currentData(),
            "check_updates": self.check_updates.isChecked(),
            "mod_update_before_launch": self.mod_update_before_launch.isChecked(),
            "mod_update_method": self.mod_update_method.currentData(),
            "mod_update_timeout_min": self.mod_update_timeout_min.currentData(),
            "steamcmd_exe": self.steamcmd_exe.text().strip(),
            "steam_login": self.steam_login.text().strip(),
            "external_control": self.external_control.isChecked(),
            "stop_method": self.stop_method.currentData(),
            "start_with_windows": self.start_with_windows.isChecked(),
            "start_mode": self.start_mode.currentData(),
            "close_quits": self.close_quits.isChecked(),
            "project_prefix": self.project_prefix.text().strip(),
            "client_stable": self.p_client.text(),
            "client_exp": self.p_client_exp.text(),
            "server_stable": self.p_server.text(),
            "server_exp": self.p_server_exp.text(),
            "mikero_tools": self.p_mikero.text(),
            "dayz_tools": self.p_tools.text(),
            "dayz_tools_exp": self.p_tools_exp.text(),
            "workshop_dirs": [x.strip() for x in self.workshop.toPlainText().splitlines() if x.strip()],
            "admin_steamids": self.admin_ids.values(),
            "admin_password": self.admin_pass.text(),
            "steam_api_key": self.steam_key.text().strip(),
            "downloads_dir": self.p_downloads.text(),
            "sign_key": self.sign_key.text().strip(),
            "pack_tool": self.pack_tool.currentData(),
            "krbuild_exe": self.p_krbuild.text(),
            "pack_flags": self._pack_flags,
            "clean_meta": self._clean_meta,
            "pack_engine": self.pack_engine.currentData(),
        }

    def reload_pack_flags(self) -> None:
        """Подхватывает флаги, изменённые снаружи (окно настроек запаковки с
        главной страницы). Без этого «Сохранить» здесь вернуло бы старое
        значение из своей копии."""
        self._pack_flags = self.settings.pack_flags
        self._clean_meta = self.settings.clean_meta
        self._refresh_dirty()

    def is_dirty(self) -> bool:
        return any(getattr(self.settings, k) != v for k, v in self._form_values().items())

    def _refresh_dirty(self) -> None:
        """Раньше показывала «есть несохранённые изменения». Теперь их не
        бывает: всё пишется сразу, — но метод зовут из нескольких мест, и
        пусть он останется точкой, где это решается."""
        self.unsaved.setVisible(True)

    def _modupd_method_changed(self, *_a) -> None:
        """Поля SteamCMD видны только когда он и выбран.

        Прячем, а не гасим: выключенное поле нельзя ни прочитать, ни
        скопировать, а объяснять, почему оно серое, было бы нечем.
        """
        cmd = self.mod_update_method.currentData() == "steamcmd"
        for w in (self.row_steamcmd, self.steamcmd_exe, self.row_login,
                  self.steam_login, self.login_note):
            w.setVisible(cmd)

    def _copy(self, text: str) -> None:
        """Кладёт текст в буфер и говорит об этом.

        Молчаливое копирование неотличимо от неработающей кнопки: человек жмёт
        второй раз и третий, не понимая, случилось ли что-нибудь.
        """
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        InfoBar.success(title=tr("settings.copied", "Скопировано"), content="",
                        parent=self.window(), duration=2000,
                        position=InfoBarPosition.TOP_RIGHT)

    def _save(self) -> None:
        """Пишет форму в настройки. Зовётся на каждое изменение."""
        s = self.settings
        values = self._form_values()
        autostart_changed = values.get("start_with_windows") != s.start_with_windows
        for key, value in values.items():
            setattr(s, key, value)
        s.save()
        # В реестр ходим, только когда тронули саму галку: при записи по
        # каждому изменению это был бы поход на любое движение в форме.
        if autostart_changed:
            self._apply_autostart()
        self._refresh_dirty()
        if self.on_saved:
            self.on_saved()

    def _save_later(self) -> None:
        """Сохранение с отсрочкой — для полей, которые правят построчно.

        Список папок мастерской — многострочное поле без «конца ввода»:
        писать на каждый символ незачем, а терять набранное нельзя.
        """
        if self._save_timer is None:
            self._save_timer = QTimer(self)
            self._save_timer.setSingleShot(True)
            self._save_timer.setInterval(700)
            self._save_timer.timeout.connect(self._save)
        self._save_timer.start()

    def _apply_autostart(self) -> None:
        """Правит запись в автозагрузке под галку.

        Делается при каждом сохранении, а не только при смене галки: программу
        могли переставить в другую папку, и запись вела бы в никуда — Windows
        на это молчит, а человек считал бы, что автозапуск работает.
        """
        from core import autostart
        want = self.start_with_windows.isChecked()
        if not want and not autostart.enabled():
            return
        ok, err = autostart.apply(want)
        if not ok:
            InfoBar.warning(
                title=tr("settings.autostart_failed", "Автозапуск не изменён"),
                content=err, parent=self.window(), duration=8000,
                position=InfoBarPosition.TOP_RIGHT)
            self.start_with_windows.setChecked(autostart.enabled())
