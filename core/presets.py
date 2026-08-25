"""Пресеты сервера и пресеты модов."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .settings import PRESETS_DIR, MOD_PRESETS_DIR, STABLE

MODE_DEDICATED = "dedicated"
MODE_DIAG = "diag"


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_")
    return s or "preset"


# Единицы, которые раньше писали в самом шаблоне сообщения. Теперь их
# подставляет %t вместе с числом (иначе на последней минуте выходило «через
# 45 мин.»), и оставшийся в тексте хвост дал бы «через 45 сек. мин.».
_UNIT_TAIL = (" мин.", " мин", " min.", " min", " Min.", " Min")


def _times_from_old(preset: ServerPreset, data: dict) -> str:
    """Перенос старых пресетов: «начиная с HH:MM каждые N минут» -> список.

    Раскрываем прежнюю сетку в явные времена, чтобы расписание после
    обновления осталось тем же, каким его задавали.
    """
    if data.get("restart_times") or "restart_at" not in data:
        return preset.restart_times
    from .watchdog import format_times, minutes_of
    start = minutes_of(data.get("restart_at", "04:00"))
    step = int(data.get("restart_every_min", 0) or 0)
    if step <= 0:
        return format_times([start])
    return format_times([t for t in range(start, 24 * 60, step)])


def _drop_unit(message: str) -> str:
    """Убирает единицу, дописанную сразу после %t в старых пресетах."""
    for tail in _UNIT_TAIL:
        message = message.replace("%t" + tail, "%t")
    return message


@dataclass
class ServerPreset:
    name: str = "Новый пресет"
    mode: str = MODE_DIAG                  # dedicated | diag
    branch: str = STABLE                   # ветка по умолчанию
    client_use_diag: bool = False          # в dedicated-режиме клиент = DayZDiag

    # Пути (относительно корня клиента или абсолютные)
    server_config: str = ""
    mission: str = ""
    profiles: str = ""
    port: int = 2302
    time_login: int = -1   # TimeLogin в db/globals.xml миссии; -1 — не трогать

    # Параметры запуска: имя -> значение (только явно выставленные)
    params_server: dict = field(default_factory=dict)
    params_client: dict = field(default_factory=dict)
    extra_server: str = ""                 # доп. аргументы свободным текстом
    extra_client: str = ""

    # Моды: имена из реестра модов; порядок = порядок загрузки
    mods: list[str] = field(default_factory=list)          # -mod (клиент + сервер)
    server_mods: list[str] = field(default_factory=list)   # -serverMod

    # Состояние галок запуска
    launch_server: bool = True
    launch_client: bool = True

    # Поднимать сервер этого пресета при старте программы (в том числе когда
    # она стартует вместе с Windows). Только сервер: автозапуск клиента
    # означал бы, что игра лезет на экран без спроса.
    autostart: bool = False
    # Перезапускать сервер по расписанию и поднимать его, если он упал.
    # Значения — в core/watchdog; здесь только хранение.
    auto_restart: bool = False
    # Времена перезапусков через запятую: «01:00, 05:00, 15:00». Только
    # список — прежние «через N минут работы» и «каждые N часов начиная с
    # HH:MM» убраны: при них время суток гуляло, а нужно было обратное.
    restart_times: str = "04:00"
    restart_warn_min: int = 15          # за сколько минут начинать предупреждать
    restart_message: str = "Перезапуск сервера через %t"
    auto_revive: bool = False           # поднимать упавший сервер

    @property
    def world(self) -> str:
        return self.mission.rsplit(".", 1)[1] if "." in self.mission else ""

    def file_stem(self) -> str:
        """Имя файла пресета: <имя>_<карта> — одно имя допустимо на разных картах."""
        return _slug(f"{self.name}_{self.world}" if self.world else self.name)

    def path(self) -> Path:
        return PRESETS_DIR / f"{self.file_stem()}.json"

    def save(self) -> None:
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        new_path = self.path()
        new_path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # имя или карта изменились — файл переехал, старый убираем
        src = getattr(self, "_src", None)
        if src and Path(src) != new_path:
            try:
                Path(src).unlink(missing_ok=True)
            except OSError:
                pass
        self._src = new_path

    def delete(self) -> None:
        try:
            Path(getattr(self, "_src", self.path())).unlink(missing_ok=True)
        except OSError:
            pass

    @classmethod
    def from_dict(cls, data: dict) -> ServerPreset:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        p = cls(**{k: v for k, v in data.items() if k in known})
        p.restart_message = _drop_unit(p.restart_message)
        p.restart_times = _times_from_old(p, data)
        return p

    @classmethod
    def load_all(cls) -> list[ServerPreset]:
        out = []
        if PRESETS_DIR.is_dir():
            for f in sorted(PRESETS_DIR.glob("*.json")):
                try:
                    p = cls.from_dict(json.loads(f.read_text(encoding="utf-8")))
                    p._src = f  # откуда загружен — для переезда файла при переименовании
                    out.append(p)
                except (OSError, json.JSONDecodeError, TypeError):
                    continue
        return out


@dataclass
class ModPreset:
    """Именованный набор модов — шаблон для быстрого применения к пресету сервера."""
    name: str = "Набор модов"
    mods: list[str] = field(default_factory=list)
    server_mods: list[str] = field(default_factory=list)

    def save(self) -> None:
        MOD_PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        (MOD_PRESETS_DIR / f"{_slug(self.name)}.json").write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load_all(cls) -> list[ModPreset]:
        out = []
        if MOD_PRESETS_DIR.is_dir():
            for f in sorted(MOD_PRESETS_DIR.glob("*.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    out.append(cls(name=data.get("name", f.stem),
                                   mods=data.get("mods", []),
                                   server_mods=data.get("server_mods", [])))
                except (OSError, json.JSONDecodeError):
                    continue
        return out


def _same_mod(a: str, b: str) -> bool:
    """Один ли это мод. Сравниваем как реестр: с «@» впереди и без регистра —
    в пресетах имя могло быть записано и так и так."""
    def norm(s: str) -> str:
        s = s.strip()
        return (s if s.startswith("@") else "@" + s).lower()
    return norm(a) == norm(b)


def apply_server_flag(mod_name: str, is_server: bool) -> list[str]:
    """Раскладывает мод по строкам запуска во всех пресетах. Возвращает имена
    тех, где что-то изменилось.

    Признак «серверный» — свойство самого мода, а не пресета, но подключён мод
    в пресете списком: -mod или -serverMod. Раньше метку меняли, а подключённые
    экземпляры оставались где были — мод продолжал уходить не в ту строку
    запуска, и человек видел ту же ошибку, ради которой метку и ставил.

    Затрагиваются только пресеты, где мод уже подключён: молча добавлять его
    туда, где его не было, нельзя.
    """
    changed: list[str] = []
    for p in ServerPreset.load_all():
        src, dst = (p.mods, p.server_mods) if is_server else (p.server_mods, p.mods)
        moved = [n for n in src if _same_mod(n, mod_name)]
        if not moved:
            continue
        src[:] = [n for n in src if not _same_mod(n, mod_name)]
        for n in moved:
            if not any(_same_mod(x, n) for x in dst):
                dst.append(n)
        p.save()
        changed.append(p.name)
    return changed
