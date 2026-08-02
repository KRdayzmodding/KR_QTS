"""Ярлык быстрого запуска пресета на рабочем столе.

Ярлык несёт только имя пресета: «KR_QTS.exe --launch <пресет>». Всё остальное
делает приложение, и это принципиально — запуск у нас не «дёрнуть exe с
аргументами», а десяток шагов подготовки: перепаковка изменённых модов,
junction-ссылки, права админок, время входа в миссии. Ярлык с готовой
командной строкой пропустил бы всё это, и сервер поднялся бы сломанным.

Создаём через WScript.Shell, а не через pywin32: тот стоит в системе, но в
requirements его нет, и в собранную версию он может не попасть. PowerShell
есть на любой Windows.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Символы, которые нельзя ставить в имя файла Windows.
_BAD = '<>:"/\\|?*'


def desktop() -> Path:
    """Рабочий стол текущего пользователя."""
    import os
    profile = os.environ.get("USERPROFILE", "")
    return Path(profile) / "Desktop" if profile else Path.home() / "Desktop"


def app_target() -> tuple[str, str]:
    """Что запускать и с какой рабочей папкой.

    Из собранной версии — сам exe. Из исходников — интерпретатор с main.py:
    ярлык на разработческий запуск тоже иногда нужен.
    """
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return str(exe), str(exe.parent)
    root = Path(__file__).resolve().parent.parent
    return str(Path(sys.executable).resolve()), str(root)


def _powershell() -> str:
    """Полный путь к PowerShell.

    Не короткое имя: его ищут в PATH, а туда можно подложить свой powershell.exe
    и выполнить чужой код от нашего имени. Полный путь эту возможность убирает.
    """
    import os
    root = os.environ.get("SystemRoot", r"C:\Windows")
    full = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(full) if full.is_file() else "powershell.exe"


def _safe_name(name: str) -> str:
    out = "".join("_" if c in _BAD else c for c in name).strip(" .")
    return out or "preset"


def create(preset_stem: str, title: str, folder: Path | None = None) -> tuple[Path, str]:
    """Создаёт ярлык. Возвращает (путь, ошибка); ошибка пустая при успехе."""
    target, workdir = app_target()
    args = f'--launch "{preset_stem}"'
    if not getattr(sys, "frozen", False):
        # из исходников запускаем через main.py — он и разберёт аргумент
        args = f'"{Path(workdir) / "main.py"}" {args}'
    path = (folder or desktop()) / f"{_safe_name(title)}.lnk"

    # Кавычки внутри PowerShell-строки удваиваются; пути и имена приходят от
    # человека, и одинарная кавычка в имени пресета иначе разорвала бы команду.
    def q(s: str) -> str:
        return "'" + str(s).replace("'", "''") + "'"

    script = (
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({q(path)});"
        f"$s.TargetPath={q(target)};"
        f"$s.Arguments={q(args)};"
        f"$s.WorkingDirectory={q(workdir)};"
        f"$s.Description={q(title)};"
        f"$s.Save()"
    )
    try:
        res = subprocess.run([_powershell(), "-NoProfile", "-NonInteractive",
                              "-Command", script],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return path, str(e)
    if res.returncode != 0:
        return path, (res.stderr or res.stdout or "").strip()[:300]
    if not path.is_file():
        return path, "ярлык не создался"
    return path, ""
