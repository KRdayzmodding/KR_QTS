"""Параметры запуска сервера и клиента — строками, а не таблицей в окне.

Флаги названы так же, как в командной строке игры: для мододела это точнее
любого перевода — совпадает с документацией и гуглится. Смысл каждого написан
рядом, а не прячется во всплывающей подсказке.

Значения кладутся в пресет сразу, как их поменяли: кнопка «Сохранить» здесь
означала бы, что настройку можно выставить и потерять, а человек уже нажал
«Запустить».
"""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import LineEdit, SegmentedWidget, SwitchButton

from core.i18n import tr
from core.params import CLIENT, FLAG, INT, SERVER, SWITCH, specs_for
from core.presets import MODE_DIAG, ServerPreset
from ui import tokens
from ui.rows import Columns, setting_row, subheading

# Значения трёхпозиционного параметра. «Не задан» — не то же самое, что
# «выключен»: первый не попадает в командную строку вовсе, второй уезжает
# туда как «=0», и для игры это разные вещи.
UNSET, ON, OFF = "unset", "on", "off"


class ParamsPanel(QWidget):
    """Параметры запуска выбранной стороны."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.preset: ServerPreset | None = None
        self._loading = False
        self._widgets: dict[tuple[str, str], QWidget] = {}
        self._rows: dict[str, list[QWidget]] = {SERVER: [], CLIENT: []}

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(tokens.SPACE_XS)

        self.side = SegmentedWidget()
        for key, text in ((SERVER, tr("params.side_server", "Сервера")),
                          (CLIENT, tr("params.side_client", "Клиента"))):
            self.side.addItem(routeKey=key, text=text,
                              onClick=lambda _c=False, k=key: self._show_side(k))
        self.side.setCurrentItem(SERVER)
        box.addWidget(subheading(tr("params.title", "Параметры запуска")))
        box.addWidget(setting_row(
            tr("params.whose", "Чьи параметры"),
            tr("params.whose_desc",
               "Флаги названы так же, как в командной строке игры."), self.side))

        self.columns = Columns([])
        box.addWidget(self.columns)

        self.extra = LineEdit()
        self.extra.setPlaceholderText(tr("params.extra_ph", "Например: -cpuCount=4"))
        self.extra.setFixedWidth(260)
        self.extra.editingFinished.connect(self._extra_changed)
        box.addWidget(setting_row(
            tr("params.extra", "Дополнительно"),
            tr("params.extra_desc", "Аргументы, которых нет в списке выше."),
            self.extra))

    # ------------------------------------------------------------------ данные

    def set_preset(self, preset: ServerPreset | None) -> None:
        self.preset = preset
        self.setEnabled(preset is not None)
        self._build()

    def _diag(self) -> bool:
        return bool(self.preset and self.preset.mode == MODE_DIAG)

    def _build(self) -> None:
        """Пересобирает строки: набор параметров зависит от режима пресета."""
        self._loading = True
        try:
            for row in list(self._widgets.values()):
                pass
            for rows in self._rows.values():
                for row in rows:
                    row.setParent(None)
            self._widgets.clear()
            self._rows = {SERVER: [], CLIENT: []}
            if self.preset is None:
                self.columns.rows = []
                self.columns.set_active([])
                return

            all_rows = []
            for target, values in ((SERVER, self.preset.params_server),
                                   (CLIENT, self.preset.params_client)):
                for spec in specs_for(target, self._diag()):
                    control = self._control(spec, values.get(spec.name, None), target)
                    row = setting_row(f"-{spec.name}", spec.tooltip(), control)
                    self._rows[target].append(row)
                    all_rows.append(row)
            self.columns.rows = all_rows
            self._show_side(self.side.currentRouteKey() or SERVER)
        finally:
            self._loading = False

    def _control(self, spec, value, target: str) -> QWidget:
        key = (target, spec.name)
        if spec.ptype in (FLAG, SWITCH):
            if spec.ptype == FLAG:
                w = SwitchButton()
                w.setOnText("")
                w.setOffText("")
                w.setChecked(bool(value))
                w.checkedChanged.connect(lambda _v, k=key: self._changed(k))
            else:
                # Три состояния: не задан, включён, выключен. Сегмент, а не
                # список: вариантов три, они короткие и взаимоисключающие.
                w = SegmentedWidget()
                for route, text in ((UNSET, tr("params.unset", "—")),
                                    (ON, tr("params.on", "Вкл")),
                                    (OFF, tr("params.off", "Выкл"))):
                    w.addItem(routeKey=route, text=text,
                              onClick=lambda _c=False, k=key: self._changed(k))
                w.setCurrentItem(UNSET if value is None else (ON if value else OFF))
        else:
            w = LineEdit()
            w.setFixedWidth(150)
            w.setText("" if value is None else str(value))
            if spec.ptype == INT:
                w.setPlaceholderText(tr("params.int_ph", "число"))
            w.editingFinished.connect(lambda k=key: self._changed(k))
        self._widgets[key] = w
        return w

    def _show_side(self, key: str) -> None:
        self.columns.set_active(self._rows.get(key, []))
        if self.preset is not None:
            self.extra.setText(self.preset.extra_server if key == SERVER
                               else self.preset.extra_client)

    # ------------------------------------------------------------------ запись

    def _changed(self, key: tuple[str, str]) -> None:
        if self._loading or self.preset is None:
            return
        target, name = key
        values = (self.preset.params_server if target == SERVER
                  else self.preset.params_client)
        spec = next((s for s in specs_for(target, self._diag()) if s.name == name), None)
        w = self._widgets.get(key)
        if spec is None or w is None:
            return
        if spec.ptype == FLAG:
            if w.isChecked():
                values[name] = True
            else:
                values.pop(name, None)
        elif spec.ptype == SWITCH:
            route = w.currentRouteKey()
            if route == UNSET:
                values.pop(name, None)
            else:
                values[name] = route == ON
        else:
            text = w.text().strip()
            if not text:
                values.pop(name, None)
            elif spec.ptype == INT:
                try:
                    values[name] = int(text)
                except ValueError:
                    return
            else:
                values[name] = text
        self._save()

    def _extra_changed(self) -> None:
        if self._loading or self.preset is None:
            return
        text = self.extra.text().strip()
        if self.side.currentRouteKey() == CLIENT:
            self.preset.extra_client = text
        else:
            self.preset.extra_server = text
        self._save()

    def _save(self) -> None:
        try:
            self.preset.save()
        except OSError:
            pass        # о том, что пресет не пишется, скажет запуск
