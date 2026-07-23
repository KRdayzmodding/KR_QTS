"""KR Server Manager — точка входа."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from core import i18n
from core.settings import Settings
from ui.main_window import MainWindow
from ui.wizard import FirstRunWizard


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("KR Server Manager")
    app.setOrganizationName("KRdayzmodding")

    settings = Settings.load()
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
