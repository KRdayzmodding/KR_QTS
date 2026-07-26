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
from qfluentwidgets import FluentStyleSheet


class ThemedDialog(QDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        FluentStyleSheet.DIALOG.apply(self)


class ThemedWizard(QWizard):
    """QWizard — тоже QDialog в Qt, поэтому тот же DIALOG.qss (селектор QDialog
    в стилевом листе матчит и подклассы) красит фон под текущую тему."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        FluentStyleSheet.DIALOG.apply(self)
