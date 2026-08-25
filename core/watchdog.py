"""Сторож сервера: перезапуск по расписанию и подъём после падения.

Здесь только решения, без исполнения: на каждом такте класс говорит, что
сейчас надо сделать, а делает это окно — оно умеет останавливать и запускать
и знает про способ завершения, выбранный в настройках. Так логику можно
проверить целиком, не поднимая ни сервера, ни клиента.

Только сервер. Клиент под сторожа не попадает намеренно: он падает в отладке
десятками раз, и поднимать игру на весь экран без спроса — не помощь.

Зависший сервер отличается от работающего по RCon: процесс жив, а BattlEye
внутри него на запросы не отвечает. Логи для этого не годятся — сервер,
застрявший в бесконечном цикле скрипта, спокойно продолжает писать в них.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .i18n import tr

# Перезапуск назначается только расписанием — перечисленными временами суток.
# Отсчёт «через столько-то минут работы» убран: время суток при нём гуляет от
# запуска к запуску, а нужно было обратное. Шаг («каждые N часов начиная с
# HH:MM») убран тем же порядком: шаг, не делящий сутки нацело, обязательно
# даёт особый промежуток через полночь.
#
# Отсрочки «только что стартовали, пропустим ближайшее время» здесь нет: она
# сдвигала бы перезапуск на произвольный момент. Карусели не будет — после
# перезапуска ближайшее время считается заново, от нового момента.

# что сторож просит сделать
SAY, RESTART, REVIVE, KILL = "say", "restart", "revive", "kill"

# Столько подряд неудачных опросов RCon считаем зависанием. Три попытки с
# шагом опроса дают около полутора минут — меньше нельзя: сервер молчит и
# при обычной загрузке миссии, и во время сохранения базы.
HANG_STRIKES = 3


# Отметки, на которых предупреждаем. Ближе к сроку — чаще: за пять минут
# лишнее сообщение только раздражает, а за полминуты каждое на счету.
#   больше минуты — раз в минуту
#   последняя минута — каждые 10 секунд
#   последние полминуты — каждые 5 секунд
_FINE_MARKS = (60, 50, 40, 30, 25, 20, 15, 10, 5)


def minutes_of(text: str) -> int:
    """«01:30» -> 90 минут от полуночи. Мусор -> 0, без исключения.

    Значение приходит из файла пресета, а файл могли править руками. Уронить
    из-за этого весь запуск нельзя: полночь — понятное и безобидное падение
    назад, а перезапуск по сетке человек всё равно проверит глазами.

    Числа за пределами суток заворачиваются по кругу, а не упираются в
    границу: «25:00» — это час ночи, а не 23:59. Так же ведут себя часы.
    """
    parts = str(text or "").split(":")
    try:
        hh = int(parts[0])
        mm = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return 0
    return max(0, min(hh % 24 * 60 + mm % 60, 24 * 60 - 1))


def parse_times(text: str) -> list[int]:
    """«00:00, 04:00, 8, 12:30» -> [0, 240, 480, 750] минут от полуночи.

    Разделители любые из запятой, точки с запятой и пробела: человек пишет
    как удобно, а не как удобно разборщику. Мусор молча отбрасывается —
    вместо него окно редактора покажет, что именно понято.
    """
    out: set[int] = set()
    for chunk in re.split(r"[,;\s]+", str(text or "")):
        if not chunk:
            continue
        parts = chunk.replace(".", ":").split(":")
        try:
            hh = int(parts[0])
            mm = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            continue
        if 0 <= hh < 24 and 0 <= mm < 60:
            out.add(hh * 60 + mm)
    return sorted(out)


def format_times(times: list[int]) -> str:
    """Обратно в текст — тем же видом, каким показываем часы."""
    return ", ".join(f"{t // 60:02d}:{t % 60:02d}" for t in sorted(set(times)))


def next_node(wall: float, times: list[int]) -> float:
    """Момент ближайшего перезапуска из списка времён. 0 — список пуст.

    Времена заданы явно, поэтому день выглядит одинаково всегда: никаких
    шагов, никакого особого промежутка через полночь. Не осталось времён на
    сегодня — берём первое завтрашнее.

    Возвращается абсолютное время, а не остаток: по остатку момент не
    поймать — между тактами он перескакивает через ноль сразу к следующему
    времени, и «пора» не наступает никогда.
    """
    if not times:
        return 0.0
    lt = time.localtime(wall)
    midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    now_min = (wall - midnight) / 60
    later = [t for t in sorted(set(times)) if t > now_min]
    return midnight + (later[0] if later else 24 * 60 + min(times)) * 60


def marks_for(warn_min: int) -> list[int]:
    """Отметки в секундах до рестарта, по убыванию."""
    out = {m * 60 for m in range(1, max(0, warn_min) + 1)}
    out |= set(_FINE_MARKS)
    return sorted((m for m in out if m <= warn_min * 60), reverse=True)


def mark_label(mark: int) -> str:
    """Как назвать отметку: «5 мин.» или «30 сек.».

    Минуты только там, где отметка ровно на минуте и больше её самой:
    последняя минута идёт секундами, как и просили, — «60 сек.», а не
    «1 мин.». Врать округлением тут нечем: сообщение уходит ровно в тот
    момент, когда до срока остаётся столько, сколько написано.
    """
    if mark > 60 and mark % 60 == 0:
        return tr("watch.minutes", "{n} мин.", n=mark // 60)
    return tr("watch.seconds", "{n} сек.", n=mark)


@dataclass
class Action:
    kind: str
    text: str = ""          # для SAY — что сказать игрокам
    reason: str = ""        # для журнала


@dataclass
class ServerWatch:
    """Наблюдение за одним сервером. Такт — раз в секунду из окна."""

    times: list = field(default_factory=list)   # времена перезапуска, минут от полуночи
    warn_min: int = 15              # за сколько минут начинать предупреждать
    message: str = "Перезапуск сервера через %t"
    revive: bool = False            # поднимать упавший
    restart_on: bool = False        # включён ли перезапуск по расписанию

    started_at: float = 0.0         # когда сервер поднялся
    _node: float = 0.0              # для CLOCK: момент ближайшего узла сетки
    _said: set = field(default_factory=set)   # отметки, о которых уже сказали
    _strikes: int = 0               # подряд неотвеченных опросов RCon
    _armed: bool = False            # сторож следит (сервер наш и должен работать)
    _restarting: bool = False       # рестарт уже заказан, второй раз не просим
    _seen: bool = False             # сервер хоть раз был жив после запуска
    _pending: list[Action] = field(default_factory=list)

    # ------------------------------------------------------------- состояние

    def arm(self, now: float) -> None:
        """Сервер поднят нами — начинаем следить и отсчитывать до рестарта."""
        self.started_at = now
        self._said = set()
        self._node = 0.0
        self._strikes = 0
        self._armed = True
        self._restarting = False
        self._seen = False

    def disarm(self) -> None:
        """Сервер остановлен человеком — сторож молчит до следующего запуска."""
        self._armed = False
        self._restarting = False

    @property
    def armed(self) -> bool:
        return self._armed

    def left_sec(self, now: float, wall: float | None = None) -> float:
        """Сколько секунд до планового перезапуска (0 — не запланирован)."""
        if not self._armed or not self.restart_on or not self.times:
            return 0.0
        wall = time.time() if wall is None else wall
        if not self._node:
            self._node = next_node(wall, self.times)
        return self._node - wall

    # ------------------------------------------------------------------ такт

    def tick(self, now: float, alive: bool, rcon_alive: bool | None,
             wall: float | None = None) -> Action | None:
        """Что сделать прямо сейчас. None — ничего.

        alive — жив ли процесс сервера. rcon_alive — ответил ли RCon; None,
        если спросить нечем (RCon выключен или это не обычный сервер): тогда
        зависание не опознаём, а падения ловим по процессу.
        """
        if not self._armed:
            return None
        if alive:
            self._seen = True
            hang = self._note_rcon(rcon_alive)
            if hang:
                return hang
            return self._schedule(now, wall)
        # процесса нет
        if self._restarting:
            # это мы его и остановили ради рестарта — поднимаем обратно
            self._restarting = False
            self.started_at = now
            self._strikes = 0
            self._said = set()
            return Action(REVIVE, reason="restart")
        if self.revive and self._seen:
            self.started_at = now
            self._strikes = 0
            return Action(REVIVE, reason="crash")
        return None

    def _note_rcon(self, rcon_alive: bool | None) -> Action | None:
        """Считает молчание RCon. Три подряд — зависание."""
        if rcon_alive is None:
            return None
        if rcon_alive:
            self._strikes = 0
            return None
        if not self.revive:
            return None
        self._strikes += 1
        if self._strikes < HANG_STRIKES:
            return None
        self._strikes = 0
        self._restarting = True     # после убийства поднимем обратно
        return Action(KILL, reason="hang")

    def _schedule(self, now: float, wall: float | None = None) -> Action | None:
        """Плановый перезапуск: сначала предупреждения, потом остановка."""
        if not self.restart_on or self._restarting or not self.times:
            return None
        left = self.left_sec(now, wall)
        if left <= 0:
            self._restarting = True
            self._node = 0.0        # следующее время посчитаем после подъёма
            return Action(RESTART, reason="schedule")
        if left > self.warn_min * 60:
            return None
        # Отметки, которые уже пройдены, но ещё не названы. Говорим про самую
        # мелкую из них — она ближе всего к правде: если между тактами
        # проскочили несколько (окно было занято запуском), назвать крупную
        # значило бы обещать время, которого уже нет. Остальные помечаем
        # сказанными, чтобы не догонять ими следом.
        due = [m for m in marks_for(self.warn_min) if left <= m and m not in self._said]
        if not due:
            return None
        mark = due[-1]
        for m in due:
            self._said.add(m)
        return Action(SAY, text=self.message.replace("%t", mark_label(mark)),
                      reason="warn")
