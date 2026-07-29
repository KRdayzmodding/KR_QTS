"""Сборка приложения в папку с exe.

    python tools/build.py            обычная сборка
    python tools/build.py --clean    с очисткой кешей PyInstaller

Готовит два файла, которые нужны спеке, и запускает PyInstaller:

    build/icon.ico          иконка exe — из того же icon.tga, что и в окне
    build/version_info.txt  ресурс версии Windows (свойства файла)

Результат — dist/KR_QTS/. Пользовательские данные там не лежат:
config и downloads приложение создаёт в %APPDATA%, см. core/settings.
"""
from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
sys.path.insert(0, str(ROOT))

from core.version import APP_NAME, PUBLISHER, VERSION, parse  # noqa: E402

# Размеры кадров в .ico. 16 — заголовок и трей, 32 — панель задач,
# 48/256 — проводник и Alt+Tab. Точное совпадение важно: не найдя нужный
# размер, Windows пересэмплирует ближайший, и картинка мылится.
ICON_SIZES = (256, 128, 64, 48, 32, 24, 16)


def make_icon(dst: Path) -> None:
    """Многоразмерный .ico из icon.tga тем же уменьшением, что и иконка окна."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QBuffer, QByteArray

    app = QApplication.instance() or QApplication([])   # noqa: F841 — нужен для QPixmap
    sys.path.insert(0, str(ROOT))
    from ui.theme import ICON_FILE, _downscale, outside_source

    # тот же серый, что у значка работающей программы: .ico показывают
    # проводник, «Пуск» и ярлыки — те же чужие фоны
    src = outside_source()
    if src.isNull():
        raise SystemExit(f"не читается иконка: {ICON_FILE}")

    frames = []
    for size in ICON_SIZES:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        _downscale(src, size).toImage().save(buf, "PNG")
        buf.close()
        frames.append(bytes(ba.data()))

    # Qt умеет писать только одноразмерный ico — контейнер собираем сами.
    # Кадры лежат PNG-ами: так делает сама Windows начиная с Vista.
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = b""
    blob = b""
    for size, data in zip(ICON_SIZES, frames):
        dim = 0 if size >= 256 else size      # 0 в поле размера означает 256
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blob += data
        offset += len(data)
    dst.write_bytes(header + entries + blob)


def make_version_info(dst: Path) -> None:
    """Ресурс версии для свойств exe — Windows показывает его в «Подробно»."""
    nums = (parse(VERSION) + (0, 0, 0, 0))[:4]
    dst.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={nums}, prodvers={nums},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', {PUBLISHER!r}),
      StringStruct('FileDescription', {APP_NAME!r}),
      StringStruct('FileVersion', {VERSION!r}),
      StringStruct('InternalName', 'KR_QTS'),
      StringStruct('LegalCopyright', 'GPLv3'),
      StringStruct('OriginalFilename', 'KR_QTS.exe'),
      StringStruct('ProductName', {APP_NAME!r}),
      StringStruct('ProductVersion', {VERSION!r}),
    ])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")


def make_zip(folder: Path) -> Path:
    """Архив сборки — то, что прикладывается к релизу на GitHub.

    Внутри архива папка с именем программы, а не голые файлы: распаковав такой
    архив куда попало, человек получит папку, а не вываленные в текущий каталог
    полторы тысячи файлов.

    Имя без версии в пути внутри — обновление распаковывается поверх установки,
    и версия в именах папок только мешала бы.
    """
    import zipfile
    dst = folder.parent / f"{folder.name}-{VERSION}.zip"
    dst.unlink(missing_ok=True)
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for i, f in enumerate(files, 1):
            z.write(f, folder.name + "/" + str(f.relative_to(folder)).replace("\\", "/"))
            if i % 200 == 0:
                print(f"    упаковано {i}/{len(files)}")
    return dst


def main() -> int:
    BUILD.mkdir(exist_ok=True)
    print(f"{APP_NAME} {VERSION}")
    make_icon(BUILD / "icon.ico")
    make_version_info(BUILD / "version_info.txt")
    print("  иконка и ресурс версии готовы")

    args = [sys.executable, "-m", "PyInstaller", "--noconfirm",
            str(ROOT / "KR_QTS.spec")]
    if "--clean" in sys.argv:
        args.insert(3, "--clean")
    print("  PyInstaller…")
    rc = subprocess.run(args, cwd=ROOT).returncode
    if rc:
        return rc
    out = ROOT / "dist" / "KR_QTS"
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"\nсобрано: {out}  ({size / 1024 / 1024:.0f} МБ)")

    if "--no-zip" not in sys.argv:
        print("  архив для релиза…")
        z = make_zip(out)
        print(f"\nготово: {z}  ({z.stat().st_size / 1024 / 1024:.0f} МБ)")
        print("  приложите этот файл к релизу на GitHub")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
