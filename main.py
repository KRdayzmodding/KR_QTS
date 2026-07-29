"""KR Quick Test Server — точка входа."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication
from qfluentwidgets import setTheme, setThemeColor, Theme

from core import console, crashguard, i18n, updater_apply
from core.settings import APP_DIR, Settings
from core.version import APP_NAME, VERSION
from ui.first_run_update import ensure_current
from ui.main_window import MainWindow
from ui.theme import outside_icon
from ui.wizard import FirstRunWizard

_THEMES = {"light": Theme.LIGHT, "dark": Theme.DARK, "auto": Theme.AUTO}


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
    window.show()
    # проверка версии — после показа окна: сеть не должна задерживать запуск
    window.start_update_check()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
