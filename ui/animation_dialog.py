"""Local file conversion via the same qtsctl entry point used by scripts."""
from pathlib import Path
import sys

from PySide6.QtCore import QProcess, QStandardPaths
from PySide6.QtWidgets import QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CheckBox, FluentIcon as FIF, LineEdit,
                            PlainTextEdit, PrimaryPushButton, ToolButton)

from core.i18n import tr
from ui import tokens
from ui.theme import ThemedDialog


class AnimationDialog(ThemedDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.suggested_output = ""
        self.setWindowTitle(tr("animation.title", "Модели и анимации"))
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setSpacing(tokens.SPACE_S)
        self.form = QFormLayout()
        layout.addLayout(self.form)
        self.operation = QComboBox()
        self.operation.setAccessibleName(tr("animation.operation", "Операция"))
        for name, key, fallback in (
            ("model-import", "model_import", "XOB → Blender"),
            ("model-export", "model_export", "Blender → XOB"),
            ("convert", "convert", "ANM ⇄ TXA"),
            ("scene-import", "scene_import", "Применить ANM к ригу"),
            ("scene-export", "scene_export", "Экспорт анимации из Blender"),
            ("library-import", "library_import", "Модель и все анимации → Blender"),
            ("library-export", "library_export", "Экспорт модели и всех анимаций"),
        ):
            self.operation.addItem(tr(f"animation.{key}", fallback), userData=name)
        self.form.addRow(BodyLabel(tr("animation.operation", "Операция")), self.operation)
        self.fields = {}
        self.rows = {}
        for key, label in (("source", "Исходный файл"), ("rig", "Риг XOB / Blender"),
                           ("model", "Путь XOB в архиве PBO"), ("animations", "Папка анимаций"),
                           ("visual", "Видимая модель P3D"),
                           ("assets_root", "Ресурсы модели"),
                           ("output", "Сохранить в"), ("model_out", "Дополнительно сохранить XOB"),
                           ("armature", "Имя арматуры"), ("action", "Имя действия"),
                           ("toolkit", "Папка комплекта KR"), ("blender", "Программа Blender")):
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            field = LineEdit()
            self.fields[key] = field
            self.rows[key] = row
            line.addWidget(field)
            if key not in ("armature", "action", "model"):
                pick = ToolButton(FIF.FOLDER)
                pick.clicked.connect(lambda checked=False, item=key: self._browse(item))
                line.addWidget(pick)
            self.form.addRow(BodyLabel(tr(f"animation.{key}", label)), row)
        self.fields["toolkit"].setText(settings.animation_toolkit)
        self.fields["blender"].setText(settings.animation_blender)
        self.fields["assets_root"].setText(settings.animation_assets_root)
        for key in ("toolkit", "blender", "assets_root", "animations", "visual"):
            self.fields[key].setPlaceholderText(tr("animation.automatic", "Автопоиск"))
        for key in ("armature", "action", "model_out"):
            self.fields[key].setPlaceholderText(tr("animation.optional", "Необязательно"))
        self.advanced = CheckBox(tr("animation.advanced", "Дополнительные параметры"))
        self.advanced.toggled.connect(self._rows)
        layout.addWidget(self.advanced)
        self.replace = CheckBox(tr("animation.overwrite", "Заменить существующие выходные файлы"))
        layout.addWidget(self.replace)
        self.go = PrimaryPushButton(tr("animation.run", "Выполнить"))
        self.go.clicked.connect(self._run)
        layout.addWidget(self.go)
        self.result = PlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setMaximumHeight(110)
        layout.addWidget(self.result)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.operation.currentIndexChanged.connect(self._changed)
        self.fields["rig"].textChanged.connect(self._rows)
        self.fields["source"].editingFinished.connect(self._suggest_output)
        self.fields["source"].textChanged.connect(self._rows)
        self._rows()

    def _rows(self, *_):
        mode = self.operation.currentData()
        extra = self.advanced.isChecked()
        visible = {"source", "output"}
        if mode == "scene-import":
            visible.add("rig")
        if mode == "library-import":
            visible.add("animations")
            if Path(self.fields["source"].text()).suffix.lower() == ".pbo":
                visible.add("model")
        xob_rig = mode == "scene-import" and Path(self.fields["rig"].text()).suffix.lower() != ".blend"
        if mode in ("model-import", "library-import") or xob_rig:
            visible.add("assets_root")
        if mode == "scene-export":
            visible.add("model_out")
        if extra:
            visible.add("toolkit")
            if mode != "convert":
                visible.add("blender")
            if mode in ("model-export", "scene-import", "scene-export"):
                visible.add("armature")
            if mode == "scene-export":
                visible.add("action")
            if mode == "library-import":
                visible.add("visual")
        for key, row in self.rows.items():
            self.form.setRowVisible(row, key in visible)
        self.fields["output"].setPlaceholderText(
            tr("animation.library_output", "Новая или пустая папка для файлов с игровыми путями")
            if mode == "library-export" else "")

    def _changed(self, *_):
        for key in ("source", "rig", "output", "model", "model_out", "armature", "action", "animations", "visual"):
            self.fields[key].clear()
        self._rows()

    def _suffix(self, key):
        mode = self.operation.currentData()
        if key == "source":
            return {"convert": "*.anm *.txa", "model-import": "*.xob", "model-export": "*.blend",
                    "library-import": "*.xob *.pbo", "library-export": "*.blend",
                    "scene-import": "*.anm", "scene-export": "*.blend"}[mode]
        if key == "output":
            suffix = Path(self.fields["source"].text()).suffix.lower()
            return {"convert": "*.anm" if suffix == ".txa" else "*.txa", "model-import": "*.blend",
                    "model-export": "*.xob", "scene-import": "*.blend", "scene-export": "*.anm",
                    "library-import": "*.blend"}[mode]
        return {"rig": "*.xob *.blend", "model_out": "*.xob", "blender": "*.exe", "visual": "*.p3d"}[key]

    def _suggest_output(self):
        source = self.fields["source"].text().strip()
        current = self.fields["output"].text()
        if Path(source).name and (not current or current == self.suggested_output):
            path = Path(source)
            if self.operation.currentData() == "library-export":
                target = path.with_name(path.stem + "_export")
            elif self.operation.currentData() == "library-import":
                folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
                target = Path(folder) / "KR DayZ Model Studio" / (path.stem + ".blend")
            else:
                target = path.with_suffix(self._suffix("output")[1:])
            self.suggested_output = str(target)
            self.fields["output"].setText(self.suggested_output)

    def _browse(self, key):
        start = self.fields[key].text() or self.fields["source"].text()
        output_folder = key == "output" and self.operation.currentData() == "library-export"
        if key in ("toolkit", "assets_root", "animations") or output_folder:
            choice = QFileDialog.getExistingDirectory(self, self.windowTitle(), start)
        else:
            select = QFileDialog.getSaveFileName if key in ("output", "model_out") else QFileDialog.getOpenFileName
            choice, _ = select(self, self.windowTitle(), start, f"DayZ / Blender ({self._suffix(key)})")
        if choice:
            self.fields[key].setText(choice)
            if key == "source":
                self._suggest_output()

    def _run(self):
        mode = self.operation.currentData()
        values = {key: edit.text().strip() for key, edit in self.fields.items()}
        if not values["source"] or not values["output"] or (mode == "scene-import" and not values["rig"]):
            self.result.setPlainText(tr("animation.choose", "Укажите исходный файл, результат и нужный для операции риг."))
            return
        argv = ["animation", mode, values["source"], "-o", values["output"]]
        option_keys = {
            "convert": (),
            "model-import": ("assets_root",),
            "model-export": ("armature",),
            "scene-import": ("rig", "armature"),
            "scene-export": ("model_out", "armature", "action"),
            "library-import": ("animations", "visual", "assets_root"),
            "library-export": (),
        }[mode]
        if mode == "scene-import" and Path(values["rig"]).suffix.lower() == ".xob":
            option_keys += ("assets_root",)
        if mode == "library-import" and Path(values["source"]).suffix.lower() == ".pbo":
            option_keys += ("model",)
        if mode != "convert":
            option_keys += ("blender",)
        for key in (*option_keys, "toolkit"):
            if values[key]:
                argv.extend(["--" + key.replace("_", "-"), values[key]])
        if self.replace.isChecked():
            argv.append("--overwrite")
        path_settings = {f"animation_{key}": values[key] for key in ("toolkit", "blender", "assets_root")}
        if any(getattr(self.settings, key) != value for key, value in path_settings.items()):
            for key, value in path_settings.items():
                setattr(self.settings, key, value)
            self.settings.save()
        if getattr(sys, "frozen", False):
            exe = str(Path(sys.executable).with_name("qtsctl.exe"))
        else:
            exe = sys.executable
            argv.insert(0, str(Path(__file__).resolve().parents[1] / "qtsctl.py"))
        self.go.setEnabled(False)
        self.result.setPlainText(tr("animation.running", "Идёт конвертация…"))
        self.process.start(exe, argv)

    def _finished(self, code, status):
        log = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace").strip()
        ok = code == 0 and status == QProcess.ExitStatus.NormalExit
        message = tr("animation.done", "Готово") if ok else tr("animation.error", "Ошибка конвертации")
        self.result.setPlainText(message + "\n" + log)
        self.go.setEnabled(True)

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.result.setPlainText(self.process.errorString())
            self.go.setEnabled(True)

    def reject(self):
        if self.process.state() == QProcess.ProcessState.NotRunning:
            super().reject()
