"""Установка [KR] Dev Toolkit: скачать установщик и отдать его человеку.

Тулкит — чужая программа, в поставку QTS она не входит. Пока её нет, движок
«Project Builder» выбрать можно, а собрать им нельзя — и человек остаётся с
сообщением «не установлен» и без следующего шага. Поэтому установщик мы
скачиваем сами: адрес постоянный, его публикуют те же люди, что и тулкит.

Ставить за человека не беремся: установщик показывает своё окно, спрашивает
папку и работает без прав администратора. Наше дело — принести файл, запустить
его и после выхода проверить, нашёлся ли тулкит.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from .settings import APP_DIR
from .version import VERSION

REPO = "KRdayzmodding/KR_Toolkit"
SETUP_TAG = "installer"
SETUP_NAME = "KR_DevToolkit_Setup.exe"
# Прямая ссылка на тот же файл: она работает и тогда, когда API GitHub
# отвечает отказом (а он отвечает — без ключа там 60 запросов в час на адрес).
SETUP_URL = f"https://github.com/{REPO}/releases/download/{SETUP_TAG}/{SETUP_NAME}"
_API = f"https://api.github.com/repos/{REPO}/releases/tags/{SETUP_TAG}"
_UA = {"User-Agent": f"KR-QTS/{VERSION} (github.com/KRdayzmodding/KR_QTS)",
       "Accept": "application/vnd.github+json"}

SETUP_DIR = APP_DIR / "toolkit"
_CHUNK = 256 * 1024


@dataclass
class Setup:
    """Установщик: откуда брать, сколько весить и чем проверить."""
    url: str = SETUP_URL
    size: int = 0
    digest: str = ""        # «sha256:...», считает сам GitHub

    @property
    def expected(self) -> str:
        return self.digest.split(":", 1)[-1].lower() if self.digest else ""


def fetch_setup(timeout: int = 15) -> Setup:
    """Описание установщика с GitHub; при отказе — одна прямая ссылка.

    Размер и контрольную сумму спрашиваем у API: без размера не из чего
    считать проценты, а без суммы нечем проверить скачанное. Но жить без них
    можно, а без установщика нельзя — поэтому отказ API не останавливает
    загрузку, он только лишает нас полоски и сверки.
    """
    try:
        req = urllib.request.Request(_API, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return Setup()
    for asset in (data.get("assets") or []):
        if str(asset.get("name", "")).lower() == SETUP_NAME.lower():
            return Setup(url=str(asset.get("browser_download_url") or SETUP_URL),
                         size=int(asset.get("size") or 0),
                         digest=str(asset.get("digest") or ""))
    return Setup()


def local_setup() -> Path:
    """Куда кладём скачанный установщик."""
    return SETUP_DIR / SETUP_NAME


def ready(setup: Setup) -> str:
    """Уже скачанный и сошедшийся файл; пусто — качать заново.

    Проверяем суммой, а не наличием: оборванная в прошлый раз загрузка и
    подменённый файл выглядят на диске одинаково.
    """
    path = local_setup()
    if not path.is_file():
        return ""
    if setup.size and path.stat().st_size != setup.size:
        return ""
    if setup.expected and _sha256(path) != setup.expected:
        return ""
    # Без суммы и размера сказать «сошлось» не о чем: такой файл качаем заново.
    return str(path) if (setup.expected or setup.size) else ""


def _sha256(path: Path) -> str:
    sha = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(_CHUNK)
                if not chunk:
                    break
                sha.update(chunk)
    except OSError:
        return ""
    return sha.hexdigest()


def launch(path: str) -> subprocess.Popen | None:
    """Запускает установщик; None — не удалось.

    Без ключей тишины: папку и ярлыки выбирает человек, а молчаливая
    установка чужой программы — это решение за него.
    """
    try:
        return subprocess.Popen([path])
    except OSError:
        return None


def forget(path: str) -> None:
    """Убирает скачанный установщик: 137 МБ в папке настроек ни к чему.

    Зовётся только после удачной установки — когда тулкит уже нашёлся.
    Понадобится снова — скачаем снова, адрес постоянный.
    """
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


class SetupWorker(QThread):
    """Загрузка установщика со сверкой контрольной суммы."""
    progress = Signal(int, int)     # получено, всего
    done = Signal(str)              # путь к файлу
    failed = Signal(str)

    def __init__(self, setup: Setup | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        # None — спросить GitHub в своём потоке. Делать это в главном значило
        # бы подвесить окно на время сетевого запроса, и как раз в тот миг,
        # когда человек только нажал кнопку и ждёт отклика.
        self.setup = setup
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        if self.setup is None:
            self.setup = fetch_setup()
            if self._cancel:
                return
        have = ready(self.setup)
        if have:
            # Файл уже лежит и сходится: качать 137 МБ второй раз незачем.
            self.done.emit(have)
            return
        SETUP_DIR.mkdir(parents=True, exist_ok=True)
        # Качаем во временное имя: оборванная загрузка не должна выглядеть
        # готовым установщиком — его потом запустят.
        tmp = SETUP_DIR / (SETUP_NAME + ".part")
        dst = local_setup()
        sha = hashlib.sha256()
        got = 0
        try:
            req = urllib.request.Request(self.setup.url, headers=_UA)
            with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
                total = int(resp.headers.get("Content-Length") or self.setup.size or 0)
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

        if self.setup.expected and sha.hexdigest() != self.setup.expected:
            # Скачали не то: битая загрузка или подмена по пути. Запускать
            # такое нельзя — это exe, а не картинка.
            tmp.unlink(missing_ok=True)
            self.failed.emit("контрольная сумма не совпала")
            return
        try:
            dst.unlink(missing_ok=True)
            tmp.rename(dst)
        except OSError as e:
            self.failed.emit(str(e))
            return
        self.done.emit(str(dst))
