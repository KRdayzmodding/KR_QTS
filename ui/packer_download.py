"""Скачивание [KR] PBO Packer с GitHub.

Пакер поставляется отдельно от приложения (исходники к нему не открываются),
поэтому в сборку не входит и качается по требованию в packer/.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from qfluentwidgets import MessageBox, InfoBar, InfoBarPosition

from core.i18n import tr
from core.settings import Settings

# Пакер лежит в том же репозитории, но отдельной папкой packer/ — исходников
# у него нет, так что в сборку приложения он не входит и качается по требованию.
_REPO = "KRdayzmodding/KR_ServerManager"
PACKER_URL = f"https://raw.githubusercontent.com/{_REPO}/main/packer/pbo_packer.exe"
PACKER_PAGE = f"https://github.com/{_REPO}/tree/main/packer"

_UA = {"User-Agent": "KR-ServerManager (github.com/KRdayzmodding/KR_ServerManager)"}


class _DownloadWorker(QThread):
    done = Signal(bool, str)   # успех, путь либо текст ошибки

    def __init__(self, url: str, target: Path, parent=None):
        super().__init__(parent)
        self.url = url
        self.target = target

    def run(self) -> None:
        tmp = self.target.with_suffix(".part")
        try:
            self.target.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(self.url, headers=_UA)
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                while chunk := r.read(256 * 1024):
                    f.write(chunk)
            # скачали целиком — только теперь подменяем рабочий файл
            tmp.replace(self.target)
            self.done.emit(True, str(self.target))
        except Exception as e:  # noqa: BLE001 — сеть/права: показываем как есть
            tmp.unlink(missing_ok=True)
            self.done.emit(False, str(e))


def download_kr_packer(parent, settings: Settings) -> bool:
    """Спрашивает подтверждение и качает пакер. True — запущено скачивание.

    Результат приходит асинхронно (InfoBar), поэтому статус в настройках
    обновляется по завершении, а не сразу.
    """
    target = Path(settings.pbo_packer_exe())
    box = MessageBox(
        tr("packer.dl_title", "[KR] PBO Packer"),
        tr("packer.dl_confirm",
           "Скачать [KR] PBO Packer с GitHub в «{p}»?\n\n"
           "Это быстрый запаковщик без проверок ошибок — для локальной отладки. "
           "Он поставляется отдельно от приложения.", p=target.parent),
        parent.window() if parent else None,
    )
    box.yesButton.setText(tr("common.yes", "Да"))
    box.cancelButton.setText(tr("common.no", "Нет"))
    if not box.exec():
        return False

    InfoBar.info(title=tr("packer.dl_started", "Скачиваю [KR] PBO Packer…"),
                 content="", parent=parent, duration=3000,
                 position=InfoBarPosition.TOP_RIGHT)

    def finished(ok: bool, msg: str) -> None:
        if ok:
            InfoBar.success(title=tr("packer.dl_ok", "[KR] PBO Packer установлен"),
                            content=msg, parent=parent, duration=5000,
                            position=InfoBarPosition.TOP_RIGHT)
        else:
            InfoBar.error(title=tr("packer.dl_failed", "Не удалось скачать [KR] PBO Packer"),
                          content=tr("packer.dl_failed_body",
                                     "{err}\n\nМожно скачать вручную: {url}",
                                     err=msg, url=PACKER_PAGE),
                          parent=parent, duration=10000,
                          position=InfoBarPosition.TOP_RIGHT)
        if hasattr(parent, "_update_packer_status"):
            parent._update_packer_status()

    # ссылку на воркер держим на parent, иначе поток соберёт GC до завершения
    parent._packer_worker = _DownloadWorker(PACKER_URL, target, parent)
    parent._packer_worker.done.connect(finished)
    parent._packer_worker.start()
    return True
