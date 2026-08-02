"""Окно «Расположение файлов»: куда приложение кладёт своё внутри корня игры.

Четыре независимых пути — конфиги, профили, миссии, ссылки на моды. Отдельными
строками, потому что у людей разные привычки в именах: profile или profiles,
mpmissions или mpmission. Пустая строка означает сам корень.

Смена пути — это переезд, а не просто запись значения: файлы остались бы на
старом месте, а приложение искало бы их на новом. Поэтому здесь же показывается
план, ход работы и вопрос про удаление старого. Настройка записывается только
после успешного переезда — см. core/relocate.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QFormLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, LineEdit, MessageBox, PrimaryPushButton,
    ProgressBar, PushButton,
)

from core import relocate
from core.i18n import tr
from core.layout import CONFIG, MISSIONS, MODS, PATH_FIELDS, PROFILE
from core.settings import Settings
from ui.theme import ThemedDialog

_ROWS = (
    (CONFIG, "Конфиги сервера", "paths.row_config"),
    (PROFILE, "Профили", "paths.row_profile"),
    (MISSIONS, "Миссии", "paths.row_missions"),
    (MODS, "Ссылки на моды", "paths.row_mods"),
)


class _Worker(QThread):
    """Переезд в фоне: копирование сотен файлов не должно морозить окно."""
    step = Signal(int, int, str)
    finished_with = Signal(list)      # список ошибок

    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.plan = plan
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        errors = relocate.apply(
            self.plan,
            on_step=lambda d, t, n: self.step.emit(d, t, n),
            cancelled=lambda: self._cancel)
        self.finished_with.emit(errors)


class PathsDialog(ThemedDialog):
    """Показ и смена расположения файлов."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.changed = False
        self._plan: relocate.Plan | None = None
        self._worker: _Worker | None = None
        self.setWindowTitle(tr("paths.title", "Расположение проектных папок"))
        self.resize(560, 420)

        layout = QVBoxLayout(self)
        note = BodyLabel(tr(
            "paths.note",
            "Пути задаются относительно корня клиента и сервера и применяются "
            "ко всем установкам сразу. Пустая строка означает сам корень."))
        note.setWordWrap(True)
        layout.addWidget(note)

        form = QFormLayout()
        self.edits: dict[str, LineEdit] = {}
        self.errors: dict[str, CaptionLabel] = {}
        for kind, default_label, key in _ROWS:
            box = QWidget()
            col = QVBoxLayout(box)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(2)
            edit = LineEdit()
            edit.setText(getattr(settings, PATH_FIELDS[kind], "") or "")
            edit.textChanged.connect(lambda _t: self._recheck())
            err = CaptionLabel("")
            err.setWordWrap(True)
            err.setVisible(False)
            col.addWidget(edit)
            col.addWidget(err)
            self.edits[kind] = edit
            self.errors[kind] = err
            form.addRow(BodyLabel(tr(key, default_label)), box)
        layout.addLayout(form)

        self.summary = CaptionLabel("")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        layout.addStretch(1)

        self.bar = ProgressBar()
        self.bar.setVisible(False)
        layout.addWidget(self.bar)
        self.step_label = CaptionLabel("")
        layout.addWidget(self.step_label)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.b_close = PushButton(tr("common.close", "Закрыть"))
        self.b_close.clicked.connect(self.reject)
        self.b_apply = PrimaryPushButton(tr("paths.apply", "Применить"))
        self.b_apply.clicked.connect(self._apply)
        btns.addWidget(self.b_close)
        btns.addWidget(self.b_apply)
        layout.addLayout(btns)

        self._recheck()

    # ------------------------------------------------------------- проверка

    def _values(self) -> dict[str, str]:
        return {k: e.text().strip() for k, e in self.edits.items()}

    def _recheck(self) -> None:
        """Разбирает ввод и говорит, что будет сделано. Ошибку — под полем."""
        bad = False
        for kind, edit in self.edits.items():
            problem = relocate.validate(edit.text())
            self.errors[kind].setText(problem)
            self.errors[kind].setVisible(bool(problem))
            edit.setError(bool(problem))
            bad = bad or bool(problem)
        if bad:
            self.summary.setText("")
            self.b_apply.setEnabled(False)
            return
        values = self._values()
        current = {k: (getattr(self.settings, f, "") or "").strip()
                   for k, f in PATH_FIELDS.items()}
        if values == current:
            self.summary.setText(tr("paths.no_change", "Пути не изменились."))
            self.b_apply.setEnabled(False)
            return
        plan = relocate.build(self.settings, values)
        self._plan = plan
        self.summary.setText(self._describe(plan))
        self.b_apply.setEnabled(True)

    def _describe(self, plan) -> str:
        """План словами, по каждому корню отдельно.

        Общее число ничего не объясняет: установок бывает четыре, и важно
        видеть, где переезд состоится, а где переносить нечего.
        """
        if plan.empty:
            return tr("paths.nothing_to_move",
                      "Переносить нечего — файлов на старом месте нет.")
        lines = [tr("paths.will_move_head", "Будет перенесено:")]
        for label, (files, links) in sorted(plan.by_root().items()):
            lines.append(tr("paths.will_move_root",
                            "  {r}: файлов и папок {n}, ссылок {l}",
                            r=label, n=files, l=links))
        for note in plan.skipped[:6]:
            lines.append(tr("paths.skipped_one", "  пропущено — {t}", t=note))
        return "\n".join(lines)

    # -------------------------------------------------------------- переезд

    def _apply(self) -> None:
        plan = self._plan
        if plan is None:
            return
        self.b_apply.setEnabled(False)
        self.b_close.setEnabled(False)
        for e in self.edits.values():
            e.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setValue(0)
        self._worker = _Worker(plan, self)
        self._worker.step.connect(self._on_step)
        self._worker.finished_with.connect(self._on_done)
        self._worker.start()

    def _on_step(self, done: int, total: int, name: str) -> None:
        self.bar.setValue(int(done * 100 / total) if total else 100)
        self.step_label.setText(name)

    def _on_done(self, errors: list) -> None:
        self.bar.setVisible(False)
        self.step_label.setText("")
        for e in self.edits.values():
            e.setEnabled(True)
        self.b_close.setEnabled(True)
        plan = self._plan

        if errors:
            # Настройку не трогаем: старые файлы на месте, приложение работает
            # по-прежнему. Иначе получили бы настройку, указывающую в никуда.
            self._say(tr("paths.failed_title", "Переезд не завершён"),
                      tr("paths.failed_body",
                         "Настройка оставлена прежней, файлы не тронуты.\n\n{e}",
                         e="\n".join(errors[:10])))
            self._recheck()
            return

        for kind, value in self._values().items():
            setattr(self.settings, PATH_FIELDS[kind], value)
        self.settings.save()
        self.changed = True

        if plan is not None and not plan.empty:
            box = MessageBox(
                tr("paths.cleanup_title", "Файлы перенесены"),
                tr("paths.cleanup_body",
                   "Старые файлы остались на прежнем месте. Удалить их?\n\n"
                   "Если сейчас откажетесь, сможете удалить их вручную позже."),
                self)
            box.yesButton.setText(tr("paths.cleanup_yes", "Удалить"))
            box.cancelButton.setText(tr("paths.cleanup_no", "Оставить"))
            if box.exec():
                _removed, errs = relocate.cleanup(plan)
                if errs:
                    self._say(tr("paths.cleanup_partial", "Удалено не всё"),
                              "\n".join(errs[:10]))
            self._say(tr("paths.report_title", "Переезд завершён"),
                      self._report(plan))
        self.accept()

    def _report(self, plan) -> str:
        """Что именно произошло — перечнем по корням, а не словом «готово».

        У человека бывает четыре установки, и «готово» не отвечает на вопрос,
        где переезд состоялся, а где переносить было нечего.
        """
        lines = []
        for label, (files, links) in sorted(plan.by_root().items()):
            lines.append(tr("paths.report_root",
                            "{r}: перенесено {n}, ссылок пересоздано {l}",
                            r=label, n=files, l=links))
        if plan.skipped:
            lines.append("")
            lines.append(tr("paths.report_skipped", "Пропущено:"))
            lines += [f"  {t}" for t in plan.skipped[:10]]
        return "\n".join(lines)

    def _say(self, title: str, body: str) -> None:
        box = MessageBox(title, body, self)
        box.yesButton.setText(tr("common.ok", "Понятно"))
        box.cancelButton.hide()
        box.exec()

    def reject(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return          # посреди переезда закрывать нельзя
        super().reject()
