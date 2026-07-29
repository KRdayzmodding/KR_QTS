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
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QDialog, QWizard
from qfluentwidgets import FluentStyleSheet, isDarkTheme, setCustomStyleSheet

from core.settings import RES_DIR

_LIGHT_BG = "white"
_DARK_BG = "rgb(43, 43, 43)"

ICON_FILE = RES_DIR / "icon.tga"
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


def _inverted(src: QPixmap) -> QPixmap:
    """Негатив с сохранением прозрачности.

    Иконка монохромная (насыщенность нулевая по всей площади) и светлая: 84%
    пикселей — серый около 224. На тёмной шапке она читается, на светлой
    сливается с фоном. Инверсия переворачивает уровни серого, форму и
    прозрачность не трогает — для цветного логотипа так делать было бы нельзя,
    но здесь цвета нет.
    """
    img = src.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    img.invertPixels(QImage.InvertMode.InvertRgb)   # альфа не затрагивается
    return QPixmap.fromImage(img)


_icon_cache: dict[bool, QIcon] = {}


def app_icon(dark: bool | None = None) -> QIcon:
    """Иконка приложения под текущую тему; пустая, если файла нет.

    Кешируется по теме: её запрашивают окно, трей и мини-окно, а пересчёт —
    это девять уменьшений исходника половинками.
    """
    if dark is None:
        dark = isDarkTheme()
    if dark in _icon_cache:
        return _icon_cache[dark]
    icon = QIcon()
    src = QPixmap(str(ICON_FILE))
    if src.isNull():
        return icon
    if not dark:
        src = _inverted(src)
    for size in _ICON_SIZES:
        if size < src.width():
            icon.addPixmap(_downscale(src, size))
    icon.addPixmap(src)
    _icon_cache[dark] = icon
    return icon


# Серый для значков вне окна. Выбран по худшему случаю: на четырёх фонах,
# которые там встречаются, — белая шапка (255), светлая панель задач (243),
# тёмная шапка (43) и тёмная панель (32) — контраст выходит 3.9, 3.6, 3.6 и 4.1
# к одному при норме 3:1 для значков. Соседние варианты хуже: 120 проседает на
# тёмном фоне, 140 — на светлом.
_OUTSIDE_GREY = 128


def _tinted(src: QPixmap, value: int) -> QPixmap:
    """Ровная перекраска силуэта; форма и прозрачность не затрагиваются.

    Иконка — плоский силуэт: девять десятых непрозрачных пикселей имеют ровно
    один уровень, остальное приходится на сглаженные края. Терять при заливке
    нечего, полутона краёв сохраняет режим SourceIn через альфу.
    """
    img = src.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    p = QPainter(img)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(img.rect(), QColor(value, value, value))
    p.end()
    return QPixmap.fromImage(img)


def outside_source() -> QPixmap:
    """Исходник в том же сером, что и outside_icon.

    Нужен сборке: .ico внутри exe показывают проводник, «Пуск» и ярлыки — те же
    чужие фоны, и красить его иначе, чем значок работающей программы, значило бы
    получить два разных логотипа в соседних местах.
    """
    return _tinted(QPixmap(str(ICON_FILE)), _OUTSIDE_GREY)


_outside_cache: QIcon | None = None


def outside_icon() -> QIcon:
    """Значок вне окна: панель задач, «Пуск», Alt+Tab, проводник и трей.

    Один серый на все случаи, без подстройки под тему. Внутри окна фон известен
    точно — мы сами его рисуем, и там уместен максимальный контраст (app_icon).
    Снаружи фон нам не принадлежит: панель задач Windows 11 бывает прозрачной
    поверх обоев, есть режим высокой контрастности, есть удалённый рабочий
    стол. Угадывать там не по чему, а серый читается на любом из этих фонов.
    """
    global _outside_cache
    if _outside_cache is not None:
        return _outside_cache
    icon = QIcon()
    src = QPixmap(str(ICON_FILE))
    if src.isNull():
        return icon
    src = _tinted(src, _OUTSIDE_GREY)
    for size in _ICON_SIZES:
        if size < src.width():
            icon.addPixmap(_downscale(src, size))
    icon.addPixmap(src)
    _outside_cache = icon
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
