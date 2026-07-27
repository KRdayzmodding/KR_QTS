"""Общая тёмная/светлая тема для самописных диалогов.

qfluentwidgets красит под текущую Theme только свои собственные окна
(MessageBox/MessageBoxBase вызывают FluentStyleSheet.DIALOG.apply() у себя
в __init__) — обычный QDialog остаётся с системным (светлым) фоном даже при
включённой тёмной теме, а дочерние BodyLabel/CaptionLabel всё равно красятся
в светлый текст глобальной таблицей стилей — получается светлый текст на
светлом фоне, нечитаемо. Все свои диалоги в приложении наследуются от
ThemedDialog вместо голого QDialog, чтобы получать тот же фон/цвет текста,
что и у MessageBox.
"""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QWizard
from qfluentwidgets import FluentStyleSheet, setCustomStyleSheet

_LIGHT_BG = "white"
_DARK_BG = "rgb(43, 43, 43)"


def _page_qss(bg: str) -> str:
    """Фон страниц мастера и их дочерних контейнеров.

    Правило QDialog из DIALOG.qss до QWizardPage не достаёт, а нативный стиль
    Windows (windowsvista + ModernStyle) рисует область страницы белой поверх
    тёмного фона самого окна.
    """
    return (f"QWizardPage{{background-color:{bg};}}"
            f"QWizardPage QGroupBox{{background-color:transparent;}}")


class ThemedDialog(QDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        FluentStyleSheet.DIALOG.apply(self)


class ThemedWizard(QWizard):
    """QWizard — тоже QDialog в Qt, поэтому тот же DIALOG.qss (селектор QDialog
    в стилевом листе матчит и подклассы) красит фон самого окна; страницы
    приходится красить отдельно (см. _page_qss)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # ClassicStyle — иначе windowsvista подмешивает свой светлый заголовок
        # и рамку страницы, которые не подчиняются таблице стилей
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        FluentStyleSheet.DIALOG.apply(self)
        setCustomStyleSheet(self, _page_qss(_LIGHT_BG), _page_qss(_DARK_BG))
