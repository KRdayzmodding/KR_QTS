"""Проверка обновлений перед показом главного окна.

Маленькое окно на несколько секунд: крутилка и «Поиск обновлений». Дальше одно
из трёх — актуальная версия, найдено обновление, GitHub не ответил.

Почему отдельным окном, а не в фоне у главного: обновление стоит предлагать
до того, как человек начал работать. Начатую работу прерывать нельзя, и в
главном окне обновление поэтому живёт тихой пометкой в панели разделов — её
легко не заметить месяцами. Здесь же ещё ничего не начато, и вопрос уместен.

Запереть это окно не может ни при каких обстоятельствах: нет сети, GitHub
молчит, ответ пришёл битым — идём дальше. Неудобство от старой версии
несравнимо с программой, которая не запускается.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, FluentIcon as FIF, IconWidget, IndeterminateProgressRing,
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

# Сколько показываем «всё актуально». Меньше секунды — мелькание, которое
# не успеваешь прочитать; больше — задержка на ровном месте.
OK_HOLD_MS = 1000

# Проверка может пережить своё окно: ответ придёт, когда окна уже нет. Поток
# нельзя дать собрать сборщику мусора, пока он работает.
_detached: list[updater.CheckWorker] = []


class UpdateGate(ThemedDialog):
    """Окно проверки. После exec() смотреть на .release и .accepted_update."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.release: Release | None = None
        self.accepted_update = False
        self._answered = False

        self.setWindowTitle(tr("gate.title", "Обновление"))
        # Ширина одна на все состояния и все языки, высота — по содержимому:
        # пока это строка с крутилкой, окно маленькое; появятся пояснение и
        # кнопки — подрастёт один раз. Держать заранее высокое окно ради
        # состояния, до которого обычно не доходит, значит показывать секунду
        # наполовину пустую коробку.
        self.setFixedSize(420, 112)
        # Без кнопки помощи в заголовке: она ничего не делает.
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        box = QVBoxLayout(self)
        box.setContentsMargins(tokens.SPACE_L, tokens.SPACE_L,
                               tokens.SPACE_L, tokens.SPACE_L)
        box.setSpacing(tokens.SPACE_M)

        head = QHBoxLayout()
        head.setSpacing(tokens.SPACE_S)
        self.ring = IndeterminateProgressRing(self)
        self.ring.setFixedSize(24, 24)
        self.ring.setStrokeWidth(3)
        head.addWidget(self.ring)
        # Значок вместо крутилки — когда ждать больше нечего.
        self.icon = IconWidget(FIF.ACCEPT, self)
        self.icon.setFixedSize(24, 24)
        self.icon.setVisible(False)
        head.addWidget(self.icon)
        self.title = StrongBodyLabel(tr("gate.searching", "Поиск обновлений"))
        head.addWidget(self.title, 1)
        box.addLayout(head)

        self.note = BodyLabel("")
        self.note.setWordWrap(True)
        self.note.setVisible(False)
        box.addWidget(self.note)
        box.addStretch(1)

        row = QHBoxLayout()
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
        box.addLayout(row)

        # Ответ ждём ровно столько, сколько обещали. Сам запрос оборвётся сам
        # по своему таймауту; окно его не дожидается.
        QTimer.singleShot(TIMEOUT_MS, self._timed_out)

    # ------------------------------------------------------------ состояния

    def _grow(self) -> None:
        """Место под пояснение и кнопки — по самому длинному из трёх языков."""
        self.setFixedSize(420, 168)

    def _settle(self, icon, color: str, title: str) -> None:
        """Общее для всех трёх исходов: крутилка уступает место значку."""
        self._answered = True
        self.ring.setVisible(False)
        self.icon.setIcon(icon.colored(color, color))
        self.icon.setVisible(True)
        self.title.setText(title)

    def show_current(self) -> None:
        self._settle(FIF.ACCEPT, tokens.color("success"),
                     tr("gate.current", "Установлена актуальная версия"))
        QTimer.singleShot(OK_HOLD_MS, self.reject)

    def show_found(self, rel: Release) -> None:
        self.release = rel
        self._settle(FIF.UPDATE, tokens.ACCENT,
                     tr("gate.found", "Найдена новая версия!"))
        self.note.setText(tr("gate.found_body", "{n} → {v}", n=VERSION, v=rel.version))
        self.note.setVisible(True)
        self._grow()
        self.b_skip.setVisible(True)
        self.b_update.setVisible(True)
        self.b_update.setFocus()

    def show_offline(self) -> None:
        self._settle(FIF.INFO, tokens.color("warning"),
                     tr("gate.offline", "Не удалось подключиться к GitHub"))
        self.note.setText(tr("gate.offline_body",
                             "Проверить обновления можно позже — в настройках."))
        self.note.setVisible(True)
        self._grow()
        self.b_ok.setVisible(True)
        self.b_ok.setFocus()

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


def run(settings, parent: QWidget | None = None) -> bool:
    """Показывает окно проверки. True — идти дальше, False — мы закрываемся.

    False означает, что человек согласился обновиться и помощник пошёл
    работать: приложение обязано уйти, иначе он будет ждать нас до упора.
    """
    if not getattr(settings, "check_updates", True):
        return True
    if updater.pending() is not None:
        # Обновление уже скачано и ждёт перезапуска — спрашивать GitHub
        # незачем, об этом скажет само главное окно.
        return True

    gate = UpdateGate(parent)
    worker = updater.CheckWorker(timeout=int(TIMEOUT_MS / 1000))
    _detached.append(worker)

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
    gate.exec()

    if not gate.accepted_update or gate.release is None:
        return True
    return _install(gate.release, parent)


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
