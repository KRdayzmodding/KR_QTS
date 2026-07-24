"""Фоновая загрузка миссии: zip ветки с GitHub -> распаковка подпапки -> установка."""
from __future__ import annotations

import shutil
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from . import missions
from .missions import CatalogEntry

_CHUNK = 256 * 1024


class MissionDownloadWorker(QThread):
    """Скачивает и устанавливает миссию из каталога.

    replace=True — обновление существующей папки; keep_storage управляет
    судьбой storage_* (персистентность) при обновлении.
    """
    progress = Signal(int, int, float, bool)  # байт скачано, всего, секунд, total оценочный?
    status = Signal(str)
    done = Signal(bool, str)             # ok, целевой путь или текст ошибки

    def __init__(self, entry: CatalogEntry, target_dir: Path, target_name: str,
                 replace: bool = False, keep_storage: bool = True, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.target_dir = target_dir
        self.target_name = target_name
        self.replace = replace
        self.keep_storage = keep_storage
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001 — всё в UI
            self.done.emit(False, str(e))

    def _run(self) -> None:
        from .i18n import tr
        entry = self.entry
        target = self.target_dir / self.target_name

        self.status.emit(tr("dl.resolving", "Определение версии…"))
        sub_path = missions.resolve_entry_path(entry)
        sha = missions.latest_sha(entry, sub_path)
        # GitHub отдаёт zip потоком без Content-Length; оцениваем объём по размеру репозитория
        estimated = 0
        try:
            info = missions._api_json(f"https://api.github.com/repos/{entry.repo}")
            estimated = int(info.get("size", 0)) * 1024
        except Exception:  # noqa: BLE001 — оценка не обязательна
            pass
        if self._cancel:
            self.done.emit(False, tr("dl.cancelled", "Отменено"))
            return

        url = missions.zip_url(entry)
        self.status.emit(tr("dl.downloading", "Скачивание {repo}…", repo=entry.repo))
        tmp_zip = Path(tempfile.mkstemp(suffix=".zip", prefix="krsm_")[1])
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "KR-ServerManager (github.com/KRdayzmodding/KR_ServerManager)"})
            t0 = time.monotonic()
            got = 0
            with urllib.request.urlopen(req, timeout=60) as resp, open(tmp_zip, "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                is_estimate = total <= 0
                if is_estimate:
                    total = estimated
                while True:
                    if self._cancel:
                        self.done.emit(False, tr("dl.cancelled", "Отменено"))
                        return
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    self.progress.emit(got, total, time.monotonic() - t0, is_estimate)

            self.status.emit(tr("dl.extracting", "Распаковка…"))
            with zipfile.ZipFile(tmp_zip) as zf:
                names = zf.namelist()
                if not names:
                    raise RuntimeError("Пустой архив")
                root = names[0].split("/", 1)[0]           # <repo>-<ветка>
                prefix = f"{root}/{sub_path}/"
                members = [n for n in names if n.startswith(prefix)]
                if not members:
                    raise RuntimeError(
                        tr("dl.no_path", "В архиве нет пути {p}", p=sub_path))
                extract_tmp = Path(tempfile.mkdtemp(prefix="krsm_mission_"))
                for n in members:
                    rel = n[len(prefix):]
                    if not rel:
                        continue
                    dest = extract_tmp / rel
                    if n.endswith("/"):
                        dest.mkdir(parents=True, exist_ok=True)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(n) as src, open(dest, "wb") as out:
                            shutil.copyfileobj(src, out)

            self.status.emit(tr("dl.installing", "Установка…"))
            self.target_dir.mkdir(parents=True, exist_ok=True)
            storage_backup: list[tuple[Path, Path]] = []
            if target.exists():
                if not self.replace:
                    raise RuntimeError(tr("dl.exists", "Папка уже существует: {p}", p=target))
                if self.keep_storage:
                    for st in target.glob("storage_*"):
                        bak = Path(tempfile.mkdtemp(prefix="krsm_storage_")) / st.name
                        shutil.move(str(st), str(bak))
                        storage_backup.append((bak, target / st.name))
                shutil.rmtree(target)
            shutil.move(str(extract_tmp), str(target))
            for bak, dest in storage_backup:
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.move(str(bak), str(dest))

            missions.write_meta(target, entry, sha, sub_path)
            self.done.emit(True, str(target))
        finally:
            tmp_zip.unlink(missing_ok=True)
