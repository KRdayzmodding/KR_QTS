"""KR Server Manager — точка входа."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication
from qfluentwidgets import setTheme, setThemeColor, Theme

from core import i18n
from core.settings import Settings
from ui.main_window import MainWindow
from ui.theme import app_icon
from ui.wizard import FirstRunWizard

_THEMES = {"light": Theme.LIGHT, "dark": Theme.DARK, "auto": Theme.AUTO}


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("KR Server Manager")
    app.setOrganizationName("KRdayzmodding")
    # общая для всех окон: мастер, главное окно и окна логов берут её сами
    app.setWindowIcon(app_icon())

    settings = Settings.load()
    setTheme(_THEMES.get(settings.theme, Theme.AUTO))
    setThemeColor("#d0752b")  # оливково-оранжевый акцент под DayZ

    i18n.load(settings.language)

    if not settings.first_run_done:
        wizard = FirstRunWizard(settings)
        if not wizard.exec():
            return 0  # пользователь закрыл мастер — выходим без сохранения

    window = MainWindow(settings)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
