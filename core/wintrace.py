"""Кто показывается окном — в файл, по просьбе.

Виджет без родителя, которому сказали показаться, — окно верхнего уровня: оно
мигает на экране и пропадает. Вспышка живёт доли секунды, на снимок не
попадает, и человек может сказать только «что-то мелькнуло».

Включается переменной окружения KR_QTS_TRACE_WINDOWS=1 и пишет в
logs/windows.log: что за виджет, какого размера и из какого места кода его
показали. В обычной работе не делает ничего — фильтр даже не ставится.
"""
from __future__ import annotations

import os
import traceback
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QWidget

ENV = "KR_QTS_TRACE_WINDOWS"


class _Catcher(QObject):
    def __init__(self, path: Path):
        super().__init__()
        self.path = path

    def eventFilter(self, obj, event):      # имя метода задаёт Qt
        if (event.type() == QEvent.Type.Show and isinstance(obj, QWidget)
                and obj.isWindow()):
            where = [f"{os.path.basename(f.filename)}:{f.lineno} {f.name}"
                     for f in traceback.extract_stack()[:-1]
                     if "wintrace" not in f.filename]
            line = (f"{type(obj).__name__} «{obj.windowTitle()}» "
                    f"{obj.width()}x{obj.height()}\n    "
                    + "\n    ".join(where[-6:]) + "\n")
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line)
            except OSError:
                pass
        return False


def install(app, log_dir: Path) -> bool:
    """Ставит ловушку, если просили. True — поставили."""
    if os.environ.get(ENV) != "1":
        return False
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "windows.log"
        path.write_text("", encoding="utf-8")
    except OSError:
        return False
    app._window_trace = _Catcher(path)      # держим ссылку: иначе соберётся
    app.installEventFilter(app._window_trace)
    return True
