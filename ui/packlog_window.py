"""Окна логов pboProject: отдельно сборка pbo, отдельно бинаризация.

Логи пишет сам pboProject в temp рабочего диска, и они огромны: у крупного мода
это тысячи строк, среди которых пара предупреждений. Поэтому по умолчанию
показываются только строки с Warning/Error, а полный текст — по галке.

Перед каждым логом идёт итог: сколько предупреждений и ошибок. Он же красит
заголовок — зелёный, если чисто.
"""
from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit
from qfluentwidgets import CheckBox, CaptionLabel, isDarkTheme, qconfig

from core import packlog
from core.i18n import tr

_WARN_COLOR = "#e5c07b"
_ERR_COLOR = "#ff6b6b"
_OK_COLOR = "#4caf50"
_TEXT_COLOR = "#d4d4d4"
_CONSOLE_QSS = ("QPlainTextEdit{background:#1e1e1e;color:#d4d4d4;"
                "border:1px solid #333;border-radius:6px;padding:4px;}")

_TITLES = {
    packlog.PACKING: ("Логи запаковки", "#2e7d32"),
    packlog.BINARIZE: ("Логи бинаризации", "#6a4c93"),
}


class PackLogWindow(QWidget):
    """Логи одного типа по всем PBO последней запаковки."""

    def __init__(self, kind: str):
        super().__init__(None, Qt.WindowType.Window)
        self.kind = kind
        self._reports: list[packlog.LogReport] = []
        title, accent = _TITLES[kind]
        self.setWindowTitle(tr(f"packlog.title_{kind}", title))
        self.resize(900, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        banner = CaptionLabel(tr(f"packlog.banner_{kind}", title).upper())
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner.setStyleSheet(
            f"QLabel{{background:{accent};color:#ffffff;font-weight:600;"
            f"font-size:14pt;padding:6px 10px;border-radius:6px;}}")
        layout.addWidget(banner)

        row = QHBoxLayout()
        self.chk_full = CheckBox(tr("packlog.show_full", "Показать полностью"))
        self.chk_full.setToolTip(tr("packlog.show_full_tip",
                                    "Весь текст логов. Без галки показываются только "
                                    "строки с предупреждениями и ошибками."))
        self.chk_full.toggled.connect(lambda _v: self._render())
        row.addWidget(self.chk_full)
        row.addStretch(1)
        layout.addLayout(row)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("Consolas", 9))
        self.view.setStyleSheet(_CONSOLE_QSS)
        layout.addWidget(self.view, 1)

        self._apply_bg()
        qconfig.themeChanged.connect(self._apply_bg)

    def _apply_bg(self) -> None:
        """Обычный QWidget под тему сам не красится (как и окна логов сервера)."""
        bg = "rgb(43, 43, 43)" if isDarkTheme() else "white"
        self.setStyleSheet(f"QWidget{{background-color:{bg};}}" + _CONSOLE_QSS)

    # ----------------------------------------------------------------- данные

    def set_names(self, names: list[str]) -> None:
        """Показывает логи только что собранных PBO — а не всё, что лежит в temp
        от прошлых сессий."""
        self._reports = packlog.read_all(names, self.kind)
        self._render()

    def _summary(self, rep: packlog.LogReport) -> str:
        head = tr("packlog.summary", "[Результаты запаковки {n}]", n=f"{rep.name}.pbo")
        color = _OK_COLOR if rep.clean else _TEXT_COLOR
        parts = [f'<span style="color:{color};font-weight:600;">{html.escape(head)}</span>']
        if rep.clean:
            parts.append(f'<span style="color:{_OK_COLOR};">'
                         + html.escape(tr("packlog.no_issues", "без замечаний")) + "</span>")
        else:
            parts.append(f'<span style="color:{_WARN_COLOR};">Warnings: {rep.warnings}</span>')
            parts.append(f'<span style="color:{_ERR_COLOR};">Errors: {rep.errors}</span>')
        return " ".join(parts)

    def _line_html(self, line: str) -> str:
        """Красим только метку в начале строки, а не строку целиком —
        так текст остаётся читаемым."""
        n = packlog.mark_len(line)
        if not n:
            return f'<span style="color:{_TEXT_COLOR};">{html.escape(line)}</span>'
        color = _WARN_COLOR if packlog.mark_of(line) == packlog.WARNING else _ERR_COLOR
        return (f'<span style="color:{color};font-weight:600;">{html.escape(line[:n])}</span>'
                f'<span style="color:{_TEXT_COLOR};">{html.escape(line[n:])}</span>')

    def _render(self) -> None:
        self.view.clear()
        if not self._reports:
            self.view.appendHtml(f'<span style="color:{_TEXT_COLOR};">'
                                 + html.escape(tr("packlog.empty",
                                                  "Пока ничего не паковалось."))
                                 + "</span>")
            return
        full = self.chk_full.isChecked()
        blocks = []
        for rep in self._reports:
            if not rep.exists:
                continue
            block = [self._summary(rep)]
            lines = rep.lines if full else rep.marked_lines()
            block += [self._line_html(ln) for ln in lines]
            if rep.truncated and full:
                # молча обрезать нельзя: конец лога — как раз то место, где
                # обычно и лежит причина падения сборки
                block.append(self._line_html(
                    tr("packlog.truncated",
                       "=== лог слишком велик: показаны первые {n} строк ===",
                       n=packlog.MAX_LINES)))
            blocks.append("<br>".join(block))
        self.view.appendHtml("<br><br>".join(blocks) if blocks else
                             f'<span style="color:{_TEXT_COLOR};">'
                             + html.escape(tr("packlog.no_logs",
                                              "Логи не найдены."))
                             + "</span>")
        self.view.moveCursor(self.view.textCursor().MoveOperation.Start)
