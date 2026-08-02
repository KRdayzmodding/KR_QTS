"""KR Quick Test Server — точка входа."""
from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication
from qfluentwidgets import setTheme, setThemeColor, Theme

from core import console, crashguard, i18n, updater_apply
from core.settings import APP_DIR, Settings
from core.version import APP_NAME, VERSION
from ui.first_run_update import ensure_current
from ui.main_window import MainWindow
from ui import single_instance
from ui.theme import outside_icon
from ui.wizard import FirstRunWizard

_THEMES = {"light": Theme.LIGHT, "dark": Theme.DARK, "auto": Theme.AUTO}


def _preset_arg(argv: list[str]) -> str:
    """Имя пресета из «--launch <пресет>». Пусто — обычный запуск."""
    for i, a in enumerate(argv):
        if a == "--launch" and i + 1 < len(argv):
            return argv[i + 1].strip()
        if a.startswith("--launch="):
            return a.split("=", 1)[1].strip()
    return ""


def _greet(channel, window) -> None:
    """Пришло сообщение от второй копии.

    «show» — человек запустил программу второй раз и хочет её видеть.
    «launch:<пресет>» — нажат ярлык быстрого запуска: окно не поднимаем,
    свёрнутая в трей программа должна там и остаться.
    """
    conn = channel.nextPendingConnection()
    text = ""
    if conn is not None:
        # Сначала смотрим, что уже пришло: вторая копия успевает написать и
        # отключиться раньше, чем мы дойдём сюда, а на закрытом сокете
        # waitForReadyRead возвращает ложь, хотя данные лежат в буфере.
        if not conn.bytesAvailable():
            conn.waitForReadyRead(300)
        text = bytes(conn.readAll().data()).decode("utf-8", "replace").strip()
        single_instance.confirm(conn)
        conn.disconnectFromServer()
    if text.startswith(single_instance.LAUNCH + ":"):
        window.launch_preset_by_stem(text.split(":", 1)[1])
        return
    window.restore_from_tray()


def main() -> int:
    # До всего остального: консольные помощники pboProject наследуют консоль
    # от нас, а в собранном виде её нет — и каждый заводит себе окно.
    console.hide()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("KRdayzmodding")
    # Сразу после создания QApplication и до всего остального: если упадёт
    # чтение настроек или сборка окна, пользователь увидит причину, а не
    # исчезнувшее окно. У собранной версии stderr некуда выводить.
    crashguard.install(f"{APP_NAME} {VERSION}", APP_DIR / "logs")
    # общая для всех окон: мастер, главное окно и окна логов берут её сами
    app.setWindowIcon(outside_icon())

    # До чтения настроек: вторая копия не должна успеть ничего ни прочитать,
    # ни записать — иначе два менеджера начнут спорить за одни файлы.
    user = os.environ.get("USERNAME", "")
    wanted = _preset_arg(sys.argv)
    msg = (f"{single_instance.LAUNCH}:{wanted}" if wanted
           else single_instance.SHOW)
    if single_instance.already_running(user, msg):
        return 0            # работающая копия всё сделает сама
    channel = single_instance.listen(app, user)

    settings = Settings.load()
    setTheme(_THEMES.get(settings.theme, Theme.AUTO))
    setThemeColor("#d0752b")  # оливково-оранжевый акцент под DayZ

    i18n.load(settings.language)

    # Если помощник отработал, мы уже запущены из новых файлов — снимаем
    # отметку и убираем архив, иначе он так и лежал бы сотней мегабайт.
    updater_apply.settled()

    if not settings.first_run_done:
        # До мастера, а не после: настраивать всё на устаревшей версии, чтобы
        # потом обновиться, — верный способ получить конфиг, которого новая
        # версия не ждёт. Запереть эта проверка не может, см. модуль.
        if not ensure_current():
            return 0
        wizard = FirstRunWizard(settings)
        if not wizard.exec():
            return 0  # пользователь закрыл мастер — выходим без сохранения

    window = MainWindow(settings)
    # вторая копия стучится в канал вместо запуска — показываем эту
    channel.newConnection.connect(lambda: _greet(channel, window))
    if wanted:
        # запуск по ярлыку: окна не показываем вовсе, значок в трее уже есть
        window.launch_preset_by_stem(wanted)
    else:
        window.show()
    # после показа: подхват уже работающих клиента и сервера прошлого запуска
    window.adopt_running()
    # проверка версии — после показа окна: сеть не должна задерживать запуск
    window.start_update_check()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
