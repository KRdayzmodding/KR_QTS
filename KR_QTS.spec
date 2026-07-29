# -*- mode: python ; coding: utf-8 -*-
"""Сборка PyInstaller. Запускать через tools/build.py — он готовит иконку и
ресурс версии, без которых спека соберётся, но exe выйдет безымянным.

Режим — папка, а не один файл: раздаём мы инсталлятор, и распаковывать себя
во временный каталог при каждом запуске (5-15 секунд на PySide6) незачем.
"""
from PyInstaller.utils.hooks import collect_all

# qfluentwidgets держит свои qss, шрифты и картинки внутри пакета и грузит их
# по путям в рантайме — без collect_all окно поднимется без стилей
qfw_datas, qfw_binaries, qfw_hidden = collect_all("qfluentwidgets")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=qfw_binaries,
    datas=[
        ("data", "data"),      # шаблон serverDZ.cfg, каталог карт, шаблон LBmaster
        ("lang", "lang"),      # ru/en/de
        ("icon.tga", "."),     # иконка окна и трея
        ("LICENSE", "."),      # GPLv3 — обязана ехать вместе с бинарником
    ] + qfw_datas,
    hiddenimports=qfw_hidden,
    hookspath=[],
    runtime_hooks=[],
    # tkinter тянет ~10 МБ и не используется; Qt-модули ниже — тоже
    excludes=[
        "tkinter", "unittest", "pydoc_data",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
        "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtCharts",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KR_QTS",
    debug=False,
    strip=False,
    upx=False,              # UPX ускоряет ложные срабатывания антивирусов
    console=False,          # GUI: консольное окно за спиной не нужно
    icon="build/icon.ico",
    version="build/version_info.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="KR_QTS",
)
