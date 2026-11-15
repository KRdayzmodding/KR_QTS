"""Offline animation conversion for qtsctl and the desktop dialog."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import filecmp
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from .i18n import tr
from .settings import Settings, toolkit_home


def arguments():
    parser = argparse.ArgumentParser(prog="qtsctl animation")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("convert", "Convert ANM to TXA or TXA to ANM"),
        ("model-import", "Open a DayZ XOB model as an editable Blender scene"),
        ("model-export", "Export the model from a Blender scene to DayZ XOB"),
        ("scene-import", "Apply an ANM clip to an XOB or Blender rig"),
        ("scene-export", "Export an ANM clip and optionally its XOB model"),
        ("library-import", "Open a DayZ model and its animation library in DayZ Model Studio"),
        ("library-export", "Export the model, all clips and their report from DayZ Model Studio"),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("source", type=Path)
        sub.add_argument("-o", "--output", type=Path, required=True)
        sub.add_argument("--toolkit", help="Path to the KR tools or portable kit")
        sub.add_argument("--overwrite", action="store_true", help="Replace existing outputs")
        if name != "convert":
            sub.add_argument("--blender", help="Path to blender.exe")
        if name in ("model-import", "scene-import", "library-import"):
            sub.add_argument("--assets-root", type=Path, action="append", metavar="DIR",
                             help="Model resource directory for XOB import (repeat for multiple directories)")
        if name in ("model-export", "scene-import", "scene-export"):
            sub.add_argument("--armature", help="Armature object name in Blender")
        if name == "scene-import":
            sub.add_argument("--rig", type=Path, required=True, help="Input XOB or .blend rig")
        if name == "scene-export":
            sub.add_argument("--model-out", type=Path, help="Also export this XOB model")
            sub.add_argument("--action", help="Blender action name")
        if name == "library-import":
            sub.add_argument("--model", metavar="XOB", help="Virtual XOB path inside a PBO archive")
            sub.add_argument("--animations", type=Path, metavar="DIR", help="Directory containing ANM clips")
            sub.add_argument("--visual", type=Path, metavar="MODEL.p3d", help="Visual P3D model for a skeleton XOB")
        if name == "library-export":
            sub.add_argument("--geometry", choices=("source", "visual"), help="Export original or visible model geometry")
            sub.add_argument("--primary-uv-only", action="store_true", help="Reduce a visual XOB6 export to its primary UV layer")
    return parser


def _toolkit_file(relative: str, args, settings) -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    explicit = args.toolkit or settings.animation_toolkit
    local = os.environ.get("LOCALAPPDATA")
    studio_install = Path(local) / "Programs/KR DayZ Model Studio" if local else None
    roots = [explicit] if explicit else [base, base.parent, studio_install, settings.krbuild_exe, toolkit_home()]
    for value in filter(None, roots):
        root = Path(value)
        if root.is_file():
            root = root.parent
        for folder in (root, root / "tools"):
            candidate = folder / relative
            if candidate.is_file():
                return candidate.resolve()
    raise ValueError(tr("animation.tool_missing", "Не найден {file}. Укажите папку комплекта KR.").format(file=relative))


def _blender(args, settings) -> Path:
    supplied = args.blender or settings.animation_blender or os.environ.get("KR_BLENDER")
    if supplied:
        paths = [Path(supplied)]
    else:
        found = shutil.which("blender")
        paths = [Path(found)] if found else []
        foundation = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Blender Foundation"
        paths += sorted(foundation.glob("Blender */blender.exe"),
                        key=lambda p: tuple(map(int, re.findall(r"\d+", p.parent.name))),
                        reverse=True)
        if os.environ.get("ProgramFiles(x86)"):
            paths.append(Path(os.environ["ProgramFiles(x86)"]) / "Steam/steamapps/common/Blender/blender.exe")
    for path in paths:
        if path.is_file():
            return path.resolve()
    raise ValueError(tr("animation.blender_missing", "Не найден Blender. Укажите путь к blender.exe."))


def _check_file(path, suffixes, *, input_file):
    path = path.expanduser().resolve()
    if path.suffix.lower() not in suffixes:
        raise ValueError(tr("animation.extension", "Ожидается {types}: {path}").format(
            types=" / ".join(suffixes), path=path))
    if input_file and not path.is_file():
        raise ValueError(tr("animation.input_missing", "Входной файл не найден: {path}").format(path=path))
    return path


def _blender_command(script, args, settings):
    bridge = _toolkit_file("blender/" + script, args, settings)
    return [_blender(args, settings), "--background", "--factory-startup", "--disable-autoexec",
            "--python-exit-code", "1", "--python", bridge, "--"]


def _asset_flags(args, settings):
    roots = args.assets_root
    if not roots and settings.animation_assets_root:
        roots = [Path(settings.animation_assets_root)]
    flags = []
    for root in roots or ():
        folder = root.expanduser().resolve()
        if not folder.is_dir():
            message = tr("animation.assets_missing", "Папка ресурсов модели не найдена: {path}")
            raise ValueError(message.format(path=folder))
        flags.extend(["--assets-root", folder])
    return flags


def _studio(args, settings):
    importing = args.command == "library-import"
    source = _check_file(args.source, (".xob", ".pbo") if importing else (".blend",), input_file=True)
    output = args.output.expanduser().resolve()
    command = _blender_command("model_studio.py", args, settings)
    command += ["import" if importing else "export", source, "-o", output]
    if importing:
        command += _asset_flags(args, settings)
        if args.animations:
            command += ["--animations", args.animations.expanduser().resolve()]
        if args.visual:
            command += ["--visual", args.visual.expanduser().resolve()]
        if args.model:
            command += ["--model", args.model]
    else:
        if args.geometry:
            command += ["--geometry", args.geometry]
        if args.primary_uv_only:
            command.append("--primary-uv-only")
    if args.overwrite:
        command.append("--overwrite")
    # Studio owns staging, batch validation and publishing for its complete library.
    return _invoke(command)


def _invoke(argv):
    run = subprocess.run(list(map(str, argv)), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log = run.stdout.strip()
    if run.returncode:
        raise ValueError(tr("animation.failed", "Инструмент завершился с кодом {code}.").format(
            code=run.returncode) + "\n" + log)
    return log


def _temporary_output(target, cleanup):
    # Same directory so relative Blender asset paths and the final rename remain valid.
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".kr-qts-", suffix=target.suffix, dir=target.parent)
    os.close(fd)
    stage = Path(name)
    stage.unlink()
    cleanup.callback(stage.unlink, missing_ok=True)
    return stage


def _publish(stages, outputs, overwrite):
    previous = {}
    installed = []
    try:
        for stage, output in zip(stages, outputs):
            if overwrite and output.exists():
                fd, name = tempfile.mkstemp(prefix=".kr-qts-backup-", dir=output.parent)
                os.close(fd)
                backup = Path(name)
                try:
                    os.replace(output, backup)
                except OSError:
                    backup.unlink()
                    raise
                previous[output] = backup
            # Reserve the name exclusively before replacing it with the complete file.
            with output.open("xb"):
                pass
            installed.append(output)
            os.replace(stage, output)
    except OSError:
        for output in reversed(installed):
            output.unlink(missing_ok=True)
        for output, backup in previous.items():
            os.replace(backup, output)
        raise
    for backup in previous.values():
        backup.unlink()


def run(args, settings=None):
    settings = settings or Settings.load()
    command = args.command
    if command in ("library-import", "library-export"):
        return _studio(args, settings)
    source_types = {"convert": (".anm", ".txa"), "model-import": (".xob",),
                    "model-export": (".blend",), "scene-import": (".anm",),
                    "scene-export": (".blend",)}
    source = _check_file(args.source, source_types[command], input_file=True)
    output_type = {"convert": ".txa" if source.suffix.lower() == ".anm" else ".anm",
                   "model-import": ".blend", "model-export": ".xob",
                   "scene-import": ".blend", "scene-export": ".anm"}[command]
    inputs = [source]
    outputs = [_check_file(args.output, (output_type,), input_file=False)]
    if command == "scene-import":
        inputs.append(_check_file(args.rig, (".xob", ".blend"), input_file=True))
    if getattr(args, "model_out", None):
        outputs.append(_check_file(args.model_out, (".xob",), input_file=False))
    for output in outputs:
        if output in inputs or (output.exists() and any(output.samefile(path) for path in inputs)):
            raise ValueError(tr("animation.input_protected", "Выход совпадает с исходным файлом: {path}").format(path=output))
        if output.exists() and (not output.is_file() or not args.overwrite):
            raise ValueError(tr("animation.exists", "Выход уже существует: {path}").format(path=output))

    logs = []
    with ExitStack() as cleanup:
        stages = [_temporary_output(output, cleanup) for output in outputs]
        if command == "convert":
            exe = _toolkit_file("AnmConverter.exe", args, settings)
            scratch = Path(cleanup.enter_context(tempfile.TemporaryDirectory()))
            local = scratch / source.name
            shutil.copyfile(source, local)
            logs.append(_invoke([exe, local]))
            converted = local.with_suffix(output_type)
            if converted.is_file():
                if output_type == ".txa":
                    verify = scratch / "verify"
                    verify.mkdir()
                    txa = verify / converted.name
                    shutil.copyfile(converted, txa)
                    problem = tr("animation.lossy", "TXA не удалось вернуть в побайтно исходный ANM. Для сохранения оригинала используйте scene-import.")
                    try:
                        _invoke([exe, txa])
                    except ValueError as exc:
                        raise ValueError(f"{problem}\n{exc}") from exc
                    restored = txa.with_suffix(".anm")
                    if not restored.is_file() or not filecmp.cmp(local, restored, shallow=False):
                        raise ValueError(problem)
                    logs.append(tr("animation.verified", "Проверено: обратная конвертация вернула исходный ANM байт в байт."))
                shutil.copyfile(converted, stages[0])
        else:
            base = _blender_command("xob_cli.py", args, settings)
            op = {"model-import": "import", "model-export": "export",
                  "scene-import": "import-anm", "scene-export": "export-anm"}[command]
            armature = ["--armature", args.armature] if getattr(args, "armature", None) else []
            flags = armature.copy()
            if command == "scene-import":
                flags.extend(["--rig", inputs[1]])
            if command == "model-import" or (command == "scene-import" and inputs[1].suffix.lower() == ".xob"):
                flags += _asset_flags(args, settings)
            elif getattr(args, "assets_root", None):
                logs.append(tr("animation.assets_blend",
                               "Для готовой сцены Blender используются сохранённые в ней материалы."))
            if getattr(args, "action", None):
                flags.extend(["--action", args.action])
            logs.append(_invoke([*base, op, source, "-o", stages[0], *flags]))
            if len(outputs) == 2:
                logs.append(_invoke([*base, "export", source, "-o", stages[1], *armature]))
        if not all(stage.is_file() and stage.stat().st_size for stage in stages):
            raise ValueError(tr("animation.no_result", "Инструмент не создал выходной файл.") + "\n" + "\n".join(logs))
        _publish(stages, outputs, args.overwrite)
    return "\n".join([*logs, *map(str, outputs)])
