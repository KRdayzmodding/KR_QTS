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

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QDialog, QWizard
from qfluentwidgets import FluentStyleSheet, setCustomStyleSheet

from core.settings import APP_DIR

_LIGHT_BG = "white"
_DARK_BG = "rgb(43, 43, 43)"

ICON_FILE = APP_DIR / "icon.tga"
# Размеры, которые реально запрашиваются: 16 — системный заголовок и трей,
# 18 — заголовок FluentWindow (см. FluentTitleBar.setIcon), 32 — панель задач,
# 48/256 — проводник и Alt+Tab. Точное совпадение важно: не найдя нужный
# размер, QIcon берёт ближайший и пересэмплирует его ещё раз — картинка мылится.
_ICON_SIZES = (16, 18, 20, 24, 32, 48, 64, 128, 256)


def _downscale(src: QPixmap, size: int) -> QPixmap:
    """Уменьшение половинками до нужного размера.

    Плавное масштабирование Qt билинейное: при уменьшении сразу в 14 раз
    (256 -> 18) оно читает лишь малую часть пикселей исходника, и результат
    выходит мылом. Пошаговое деление пополам усредняет всю картинку.
    """
    pm = src
    mode = Qt.TransformationMode.SmoothTransformation
    ratio = Qt.AspectRatioMode.KeepAspectRatio
    while pm.width() // 2 > size:
        pm = pm.scaled(pm.width() // 2, pm.height() // 2, ratio, mode)
    return pm.scaled(size, size, ratio, mode)


def app_icon() -> QIcon:
    """Иконка приложения; пустая, если файла нет — падать из-за этого незачем."""
    icon = QIcon()
    src = QPixmap(str(ICON_FILE))
    if src.isNull():
        return icon
    for size in _ICON_SIZES:
        if size < src.width():
            icon.addPixmap(_downscale(src, size))
    icon.addPixmap(src)
    return icon


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
