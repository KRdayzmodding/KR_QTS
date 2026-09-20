"""Проверка обновлений перед показом главного окна.

Квадратное окно на пару секунд: наверху надпись, в середине крутилка. Пришёл
ответ — крутилка превращается в галку или в предупреждение, под ней словами
итог. Нашлось обновление — окно подрастает, и снизу появляются две кнопки.

Почему отдельным окном, а не в фоне у главного: обновление стоит предлагать
до того, как человек начал работать. Начатую работу прерывать нельзя, и в
главном окне обновление поэтому живёт тихой пометкой в панели разделов — её
легко не заметить месяцами. Здесь же ещё ничего не начато, и вопрос уместен.

Пока окно висит, главное окно собирается за его спиной: проверка упирается в
сеть, сборка — в процессор, и делать их по очереди значит складывать секунды.
Собранное окно при этом ничем себя не выдаёт — ни значка в трее, ни тактов
состояния, пока ему не скажут «живи».

Запереть это окно не может ни при каких обстоятельствах: нет сети, GitHub
молчит, ответ пришёл битым — идём дальше. Неудобство от старой версии
несравнимо с программой, которая не запускается.
"""
from __future__ import annotations

from PySide6.QtCore import (
    Property, QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, FluentIcon as FIF, IndeterminateProgressRing,
    PrimaryPushButton, PushButton, StrongBodyLabel,
)

from core import updater
from core.i18n import tr
from core.updater import Release
from core.version import VERSION
from ui import tokens
from ui.theme import ThemedDialog

# Сколько ждём ответа GitHub. Пять секунд — это уже «не отвечает»: проверка
# версии не та задача, ради которой стоит держать человека перед пустым окном.
TIMEOUT_MS = 5000

# Сколько показываем «всё актуально» перед уходом. Меньше полусекунды —
# мелькание, которое не успеваешь прочитать.
OK_HOLD_MS = 900

# Движение — по шкале из docs/UX.md: знак дорисовывается заметно, окно растёт
# быстро.
MARK_MS = 250
GROW_MS = 180

SIDE = 360              # квадрат: надпись сверху, крутилка в середине
TALL = 440              # он же, когда снизу появились кнопки

# Проверка может пережить своё окно: ответ придёт, когда окна уже нет. Поток
# нельзя дать собрать сборщику мусора, пока он работает.
_detached: list[updater.CheckWorker] = []


def _slice(path: QPainterPath, part: float) -> QPainterPath:
    """Кусок пути от начала до доли part — линия, нарисованная не до конца."""
    if part >= 1.0:
        return path
    out = QPainterPath()
    out.moveTo(path.pointAtPercent(0.0))
    steps = 24
    for i in range(1, steps + 1):
        out.lineTo(path.pointAtPercent(part * i / steps))
    return out


class Mark(QWidget):
    """Знак на месте крутилки: галка или восклицательный знак.

    Рисуем сами, а не берём готовый значок, ради одного: линия проявляется на
    глазах. Статичная картинка, возникшая вместо крутилки, читается как
    «подвисло», а дорисовавшаяся за четверть секунды — как «готово».
    """

    OK, WARN = "ok", "warn"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.kind = self.OK
        self.color = QColor(tokens.color("success"))
        self._grow = 0.0
        self.setFixedSize(72, 72)
        self._ani = QPropertyAnimation(self, b"grow", self)
        self._ani.setDuration(MARK_MS)
        self._ani.setEasingCurve(QEasingCurve.Type.OutQuad)

    def start(self, kind: str, color: str) -> None:
        self.kind = kind
        self.color = QColor(color)
        self.show()
        self._ani.stop()
        self._ani.setStartValue(0.0)
        self._ani.setEndValue(1.0)
        self._ani.start()

    def _get_grow(self) -> float:
        return self._grow

    def _set_grow(self, v: float) -> None:
        self._grow = v
        self.update()

    grow = Property(float, _get_grow, _set_grow)

    def paintEvent(self, e):        # имя метода задаёт Qt
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        p.setPen(QPen(self.color, 5.0, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        # Кольцо дорисовывается вместе со знаком: оно занимает место крутилки,
        # и без него знак повисает в пустоте там, где только что было кольцо.
        p.drawArc(QRectF(3, 3, w - 6, w - 6), 90 * 16, -int(360 * 16 * self._grow))
        if self.kind == self.OK:
            path = QPainterPath()
            path.moveTo(w * 0.30, w * 0.52)
            path.lineTo(w * 0.44, w * 0.66)
            path.lineTo(w * 0.71, w * 0.36)
            p.drawPath(_slice(path, self._grow))
        else:
            # Восклицательный знак: палочка растёт сверху вниз, точка
            # появляется в конце — раньше она мелькала бы прежде смысла.
            top, bottom = w * 0.28, w * 0.56
            p.drawLine(int(w / 2), int(top),
                       int(w / 2), int(top + (bottom - top) * self._grow))
            if self._grow > 0.85:
                p.setBrush(self.color)
                r = 3.0
                p.drawEllipse(QRectF(w / 2 - r, w * 0.68 - r, r * 2, r * 2))


class UpdateGate(ThemedDialog):
    """Окно проверки. После exec() смотреть на .release и .accepted_update."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.release: Release | None = None
        self.accepted_update = False
        self._answered = False
        # «Всё актуально» уходит не по таймеру, а когда сойдётся двое: время
        # показа вышло И главное окно собрано. Иначе бывает так: ответ пришёл
        # за треть секунды, окно проверки закрылось — а главное ещё строится,
        # и человек полсекунды смотрит на пустой белый прямоугольник.
        self._ready = False
        self._held = False

        self.setWindowTitle(tr("gate.title", "Обновление"))
        self.setFixedSize(SIDE, SIDE)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        box = QVBoxLayout(self)
        box.setContentsMargins(tokens.SPACE_L, tokens.SPACE_L,
                               tokens.SPACE_L, tokens.SPACE_L)
        box.setSpacing(tokens.SPACE_M)

        # Надпись сверху — прописными и с разрядкой: так она читается как имя
        # происходящего, а не как фраза, которую надо дочитывать.
        self.caption = CaptionLabel(tr("gate.searching", "Поиск обновлений").upper())
        font = QFont(self.caption.font())
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 112)
        self.caption.setFont(font)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.caption)

        box.addStretch(1)
        middle = QHBoxLayout()
        middle.addStretch(1)
        self.ring = IndeterminateProgressRing(self)
        self.ring.setFixedSize(72, 72)
        self.ring.setStrokeWidth(5)
        middle.addWidget(self.ring)
        self.mark = Mark(self)
        self.mark.hide()
        middle.addWidget(self.mark)
        middle.addStretch(1)
        box.addLayout(middle)

        self.result = StrongBodyLabel("")
        self.result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result.setWordWrap(True)
        self.result.setVisible(False)
        box.addWidget(self.result)

        self.note = BodyLabel("")
        self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.note.setWordWrap(True)
        self.note.setVisible(False)
        box.addWidget(self.note)
        box.addStretch(1)

        # Кнопки по центру и своей ширины: одна кнопка враспор на всё окно
        # выглядит как полоса, а не как кнопка.
        row = QHBoxLayout()
        row.setSpacing(tokens.SPACE_S)
        row.addStretch(1)
        self.b_skip = PushButton(tr("gate.skip", "Пропустить"))
        self.b_skip.clicked.connect(self.reject)
        self.b_skip.setVisible(False)
        row.addWidget(self.b_skip)
        self.b_update = PrimaryPushButton(FIF.UPDATE, tr("gate.update", "Обновить"))
        self.b_update.clicked.connect(self._take_update)
        self.b_update.setVisible(False)
        row.addWidget(self.b_update)
        self.b_ok = PushButton(tr("common.ok", "ОК"))
        self.b_ok.clicked.connect(self.reject)
        self.b_ok.setVisible(False)
        row.addWidget(self.b_ok)
        row.addStretch(1)
        for b in (self.b_skip, self.b_update, self.b_ok):
            b.setMinimumWidth(128)
        box.addLayout(row)

        self._grow_ani = QPropertyAnimation(self, b"maximumHeight", self)
        self._grow_ani.setDuration(GROW_MS)
        self._grow_ani.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._grow_ani.finished.connect(lambda: self.setFixedHeight(TALL))

        QTimer.singleShot(TIMEOUT_MS, self._timed_out)

    # ------------------------------------------------------------ состояния

    def _grow(self) -> None:
        """Растём под кнопки. Меняем только высоту: прыжок в обе стороны
        читается как «окно перестраивается», а не «раскрылось»."""
        self.setMinimumHeight(0)        # иначе фиксированный размер держит
        self._grow_ani.stop()
        self._grow_ani.setStartValue(self.height())
        self._grow_ani.setEndValue(TALL)
        self._grow_ani.start()

    def _settle(self, kind: str, color: str, text: str) -> None:
        """Общее для всех исходов: крутилка уступает место знаку."""
        self._answered = True
        self.ring.hide()
        self.mark.start(kind, color)
        self.result.setText(text)
        self.result.setVisible(True)

    def show_current(self) -> None:
        self._settle(Mark.OK, tokens.color("success"),
                     tr("gate.current", "Установлена актуальная версия"))
        QTimer.singleShot(OK_HOLD_MS, self._hold_over)

    def _hold_over(self) -> None:
        """Минимальное время показа вышло."""
        self._held = True
        self._close_when_ready()

    def build_finished(self) -> None:
        """Главное окно собрано — можно уступать ему место."""
        self._ready = True
        self._close_when_ready()

    def _close_when_ready(self) -> None:
        if self._held and self._ready:
            self.reject()

    def show_found(self, rel: Release) -> None:
        self.release = rel
        self._settle(Mark.WARN, tokens.ACCENT,
                     tr("gate.found", "Найдена новая версия!"))
        self.note.setText(tr("gate.found_body", "{n} → {v}", n=VERSION, v=rel.version))
        self.note.setVisible(True)
        self.b_skip.setVisible(True)
        self.b_update.setVisible(True)
        self.b_update.setFocus()
        self._grow()

    def show_offline(self) -> None:
        self._settle(Mark.WARN, tokens.color("warning"),
                     tr("gate.offline", "Не удалось подключиться к GitHub"))
        self.note.setText(tr("gate.offline_body",
                             "Проверить обновления можно позже — в настройках."))
        self.note.setVisible(True)
        self.b_ok.setVisible(True)
        self.b_ok.setFocus()
        self._grow()

    # -------------------------------------------------------------- события

    def _timed_out(self) -> None:
        if not self._answered:
            self.show_offline()

    def _take_update(self) -> None:
        self.accepted_update = True
        self.accept()

    def answer(self, rel: Release | None, offline: bool) -> None:
        """Ответ проверки. Опоздавший — после таймаута — не трогаем: человек
        уже читает «не удалось подключиться», и подменять текст под рукой,
        когда он тянется к кнопке, нельзя."""
        if self._answered:
            return
        if offline:
            self.show_offline()
        elif updater.is_update(rel) and rel is not None:
            self.show_found(rel)
        else:
            self.show_current()


def run(settings, build=None, parent: QWidget | None = None):
    """Показывает окно проверки. Отдаёт (идти дальше, собранное главное окно).

    build — как собрать главное окно. Собираем его, пока ждём GitHub: это
    единственное место в запуске, где сеть и процессор можно занять
    одновременно. Показывать собранное окно здесь нельзя ничем — им
    распоряжается тот, кто нас позвал.

    «Идти дальше» = False означает, что человек согласился обновиться и
    помощник пошёл работать: приложение обязано уйти.
    """
    if not getattr(settings, "check_updates", True) or updater.pending() is not None:
        # Проверка выключена или обновление уже скачано и ждёт перезапуска —
        # окна нет, но собрать главное всё равно надо.
        return True, (build() if build else None)

    gate = UpdateGate(parent)
    worker = updater.CheckWorker(timeout=int(TIMEOUT_MS / 1000))
    _detached.append(worker)
    made: dict[str, object] = {"win": None, "err": None}

    def got(rel: Release | None) -> None:
        offline = getattr(worker, "offline", False)
        try:
            gate.answer(rel, offline)
        except RuntimeError:
            pass                    # окна уже нет — ответ опоздал

    worker.done.connect(got)
    worker.finished.connect(lambda: _detached.remove(worker)
                            if worker in _detached else None)
    worker.start()

    def do_build() -> None:
        if made["win"] is not None:
            return                  # уже собрали (окно закрыли раньше срока)
        try:
            made["win"] = build()
        except Exception as e:      # noqa: BLE001 — доложим после закрытия окна
            made["err"] = e
        gate.build_finished()       # даже если не вышло: держать окно нечем

    if build is not None:
        # Через очередь событий, а не сразу: сборка держит поток секунду с
        # лишним, и начатая раньше показа она задержала бы саму крутилку.
        QTimer.singleShot(0, do_build)
    else:
        gate.build_finished()
    gate.exec()

    if made.get("err") is not None:
        raise made["err"]           # пусть разбирается сторож падений

    window = made["win"]
    if window is None and build is not None:
        # Окно закрыли раньше, чем очередь событий дошла до сборки. Собираем
        # здесь и кладём в тот же словарь: отложенный вызов увидит готовое и
        # второго окна не построит.
        window = made["win"] = build()
    if not gate.accepted_update or gate.release is None:
        return True, window
    return _install(gate.release, parent), window


def _install(rel: Release, parent: QWidget | None) -> bool:
    """Качает и ставит. True — идти дальше (не вышло), False — мы закрываемся."""
    from ui.update_dialog import UpdateDialog

    # downloading=True: «Обновить» уже нажали, и окно сразу показывает ход
    # загрузки, а не кнопку «Скачать». Второй раз спрашивать о том же — лишний
    # клик, а кнопка, которая ничего не начинает, потому что уже качается, —
    # прямая ложь.
    dlg = UpdateDialog(rel, downloading=True, parent=parent)
    worker = updater.DownloadWorker(rel, dlg)
    worker.progress.connect(dlg.set_progress)
    worker.failed.connect(dlg.set_failed)
    worker.done.connect(lambda _p: dlg.set_ready())
    go = {"v": False}
    dlg.restart_requested.connect(lambda: go.__setitem__("v", True))
    QTimer.singleShot(0, worker.start)
    dlg.exec()
    if worker.isRunning():          # окно закрыли посреди загрузки
        worker.cancel()
        worker.wait()
    if not go["v"]:
        return True                 # передумал — просто идём дальше
    from ui import update_install
    err = update_install.install(rel, parent)
    if not err:
        return False                # помощник пошёл работать, мы уходим
    # Не встало — не запираем: говорим причину и идём дальше на текущей версии.
    from qfluentwidgets import MessageBox
    box = MessageBox(tr("gate.failed_title", "Обновление не установлено"),
                     tr("gate.failed_body",
                        "{m}\n\nПродолжаем на текущей версии.", m=err), parent)
    box.cancelButton.hide()
    box.exec()
    return True
