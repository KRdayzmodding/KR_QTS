"""Проверка и загрузка обновлений с GitHub Releases.

Версия берётся из тега релиза, описание изменений — из его текста, файл — из
приложенных ассетов. Ничего дополнительно публиковать не нужно: контрольную
сумму GitHub считает сам и отдаёт в поле digest, по нему и сверяем скачанное.

Устанавливать обновление на ходу нельзя: Windows не даёт переписать файлы
работающей программы. Поэтому скачанное складывается рядом с настройками и
ждёт перезапуска — см. pending() и core/updater_apply.
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict

from PySide6.QtCore import QObject, QThread, Signal

from .settings import APP_DIR
from .version import VERSION, is_newer

REPO = "KRdayzmodding/KR_QTS"
_API = f"https://api.github.com/repos/{REPO}/releases/latest"
_UA = {"User-Agent": f"KR-QTS/{VERSION} (github.com/{REPO})",
       "Accept": "application/vnd.github+json"}

UPDATE_DIR = APP_DIR / "update"
_PENDING = UPDATE_DIR / "pending.json"
_CHUNK = 256 * 1024


@dataclass
class Release:
    """Релиз с GitHub — ровно то, что нужно показать и скачать."""
    version: str        # 0.2.0, без «v»
    name: str           # заголовок релиза
    changelog: str      # его текст
    page: str           # страница релиза на GitHub
    asset_name: str = ""
    asset_url: str = ""
    asset_size: int = 0
    digest: str = ""    # «sha256:...», считает GitHub

    @property
    def downloadable(self) -> bool:
        return bool(self.asset_url)


def _pick_asset(assets: list[dict]) -> dict | None:
    """Архив со сборкой. Берём первый zip: остальное в релизе — исходники,
    которые GitHub прикладывает сам."""
    for a in assets:
        if str(a.get("name", "")).lower().endswith(".zip"):
            return a
    return None


def fetch_latest(timeout: int = 15) -> Release | None:
    """Последний релиз либо None, если релизов нет, сеть недоступна или
    репозиторий закрыт. Отсутствие ответа — не ошибка: проверка обновлений не
    должна мешать работать.
    """
    try:
        req = urllib.request.Request(_API, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None
    tag = str(data.get("tag_name") or "")
    if not tag:
        return None
    rel = Release(
        version=tag.lstrip("vV"),
        name=str(data.get("name") or tag),
        changelog=str(data.get("body") or ""),
        page=str(data.get("html_url") or ""),
    )
    asset = _pick_asset(data.get("assets") or [])
    if asset:
        rel.asset_name = str(asset.get("name") or "")
        rel.asset_url = str(asset.get("browser_download_url") or "")
        rel.asset_size = int(asset.get("size") or 0)
        rel.digest = str(asset.get("digest") or "")
    return rel


def is_update(rel: Release | None) -> bool:
    """Именно новее, а не «отличается»: сборка из исходников идёт впереди
    релиза, и предлагать откатиться на неё назад незачем."""
    return rel is not None and is_newer(rel.version)


# ------------------------------------------------------------ скачанное ждёт

def pending() -> Release | None:
    """Обновление, уже скачанное и ждущее перезапуска."""
    try:
        data = json.loads(_PENDING.read_text(encoding="utf-8"))
        rel = Release(**data)
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    # файл могли удалить руками — тогда ждать нечего
    if not (UPDATE_DIR / rel.asset_name).is_file():
        return None
    return rel


def set_pending(rel: Release) -> None:
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    _PENDING.write_text(json.dumps(asdict(rel), ensure_ascii=False, indent=2),
                        encoding="utf-8")


def clear_pending() -> None:
    """Убирает и отметку, и сам архив: держать 150 МБ после установки незачем."""
    rel = pending()
    try:
        _PENDING.unlink(missing_ok=True)
        if rel:
            (UPDATE_DIR / rel.asset_name).unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------- воркеры

class CheckWorker(QThread):
    """Проверка версии в фоне: сеть при старте не должна задерживать окно."""
    done = Signal(object)        # Release либо None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    def run(self) -> None:
        self.done.emit(fetch_latest())


class DownloadWorker(QThread):
    """Загрузка архива обновления со сверкой контрольной суммы."""
    progress = Signal(int, int)  # получено, всего
    done = Signal(str)           # путь к файлу
    failed = Signal(str)

    def __init__(self, rel: Release, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.rel = rel
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        rel = self.rel
        UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        # качаем во временное имя: оборванная загрузка не должна выглядеть
        # как готовый к установке файл
        tmp = UPDATE_DIR / (rel.asset_name + ".part")
        dst = UPDATE_DIR / rel.asset_name
        sha = hashlib.sha256()
        got = 0
        try:
            req = urllib.request.Request(rel.asset_url, headers=_UA)
            with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
                total = int(resp.headers.get("Content-Length") or rel.asset_size or 0)
                while True:
                    if self._cancel:
                        raise InterruptedError
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    sha.update(chunk)
                    got += len(chunk)
                    self.progress.emit(got, total)
        except InterruptedError:
            tmp.unlink(missing_ok=True)
            return
        except (urllib.error.URLError, OSError) as e:
            tmp.unlink(missing_ok=True)
            self.failed.emit(str(e))
            return

        expected = rel.digest.split(":", 1)[-1].lower() if rel.digest else ""
        if expected and sha.hexdigest() != expected:
            # скачали не то: битая загрузка или подмена по пути
            tmp.unlink(missing_ok=True)
            self.failed.emit("контрольная сумма не совпала")
            return
        try:
            dst.unlink(missing_ok=True)
            tmp.rename(dst)
        except OSError as e:
            self.failed.emit(str(e))
            return
        set_pending(rel)
        self.done.emit(str(dst))
