"""Работа с serverDZ.cfg: справочник ключей и точечная правка файла.

Файл правится минимально: меняются значения, добавляются недостающие ключи и
убираются отключённые. Комментарии, порядок и чужие строки не трогаются — в
конфиге люди держат свои пометки, и переписывать файл целиком нельзя.

Справочник — единственный источник знания о ключах: тип, группа, значение по
умолчанию и пояснение. По нему строится форма редактора, и он же отвечает на
вопрос «какие настройки вообще бывают» — раньше ответить было нечем: редактор
показывал только то, что уже написано в файле.
"""
from __future__ import annotations

import codecs
import re
from dataclasses import dataclass
from pathlib import Path

# Типы значений. Разделение bool и boolstr не педантизм: DayZ пишет одни
# булевы ключи цифрами (0/1), другие словами (false/true), и перепутать их
# значит получить конфиг, который сервер прочитает неверно.
BOOL = "bool"          # 0 / 1
BOOLSTR = "boolstr"    # false / true
INT = "int"
FLOAT = "float"
STR = "str"
CHOICE = "choice"

# Группы для формы: человек ищет «где тут про логи», а не перебирает 67 строк.
GROUPS = ("main", "access", "world", "game", "net", "log")
GROUP_NAMES = {
    "main": "Основное",
    "access": "Доступ и защита",
    "world": "Мир и время",
    "game": "Правила игры",
    "net": "Сеть и производительность",
    "log": "Логи",
}


@dataclass(frozen=True)
class VarSpec:
    """Один известный ключ конфига."""

    name: str
    kind: str
    group: str
    default: str = ""
    choices: tuple = ()          # для CHOICE: ((значение, подпись), ...)
    hint: str = ""

    def tooltip(self) -> str:
        from .i18n import tr
        return tr(f"cfgvar.{self.name}", self.hint)

    @property
    def quoted(self) -> bool:
        """Пишется ли значение в кавычках. Строки — да, числа и слова — нет."""
        return self.kind == STR


def _v(name, kind, group, default, choices_or_hint, hint=None):
    """Короткая запись строки справочника: у части ключей есть варианты."""
    if hint is None:
        return VarSpec(name, kind, group, default, (), choices_or_hint)
    return VarSpec(name, kind, group, default, tuple(choices_or_hint), hint)


SPECS: tuple[VarSpec, ...] = (
    _v("hostname", "str", "main", "",
       "Название сервера в браузере серверов."),
    _v("description", "str", "main", "",
       "Описание сервера в браузере серверов (до 255 символов)."),
    _v("password", "str", "main", "",
       "Пароль для входа на сервер (пусто — без пароля)."),
    _v("passwordAdmin", "str", "main", "",
       "Пароль администратора (команды #login)."),
    _v("maxPlayers", "int", "main", "10",
       "Максимум игроков."),
    _v("template", "str", "main", "",
       "Миссия сервера в формате <Миссия>.<Террейн> (class Missions)."),
    _v("verifySignatures", "choice", "access", "0", [("0", "Выключена"), ("2", "Включена")],
       "Проверка подписей PBO: 2 — включена (нужны .bikey в keys), 0 — выключена (для разработки)."),
    _v("forceSameBuild", "bool", "access", "0",
       "Пускать только клиентов с той же сборкой игры."),
    _v("allowFilePatching", "bool", "access", "1",
       "Пускать клиентов с -filePatching (обязательно для отладки сорсов)."),
    _v("enableWhitelist", "bool", "access", "0",
       "Включить вайтлист (0-1)."),
    _v("disableBanlist", "boolstr", "access", "false",
       "Не использовать ban.txt (по умолчанию false)."),
    _v("disablePrioritylist", "boolstr", "access", "false",
       "Не использовать priority.txt (по умолчанию false)."),
    _v("disableMultiAccountMitigation", "boolstr", "access", "false",
       "Отключить защиту от мультиаккаунтов (консоли)."),
    _v("shotValidation", "bool", "access", "1",
       "Валидация выстрелов: 1 — включена, 0 — выключена."),
    _v("speedhackDetection", "int", "access", "1",
       "Детект спидхака: 1 — строгий … 10 — мягкий."),
    _v("pingWarning", "int", "access", "350",
       "Пинг (мс), при котором показывается жёлтое предупреждение."),
    _v("pingCritical", "int", "access", "500",
       "Пинг (мс), при котором показывается красное предупреждение."),
    _v("MaxPing", "int", "access", "500",
       "Пинг (мс), при котором игрока кикает с сервера."),
    _v("serverTime", "str", "world", "2012/07/15/11/00",
       "Стартовое время сервера: SystemTime или \"YYYY/MM/DD/HH/MM\"."),
    _v("serverTimeAcceleration", "float", "world", "1",
       "Ускорение игрового времени (множитель)."),
    _v("serverNightTimeAcceleration", "float", "world", "1",
       "Дополнительное ускорение ночи."),
    _v("serverTimePersistent", "bool", "world", "0",
       "Сохранять игровое время между рестартами."),
    _v("lightingConfig", "choice", "world", "0", [("0", "Яркая ночь"), ("1", "Тёмная ночь"), ("2", "Как на Сахале")],
       "Освещение ночи: 0 — яркая, 1 — тёмная, 2 — вариант Сахала."),
    _v("disablePersonalLight", "bool", "world", "1",
       "Отключить персональную подсветку у всех клиентов."),
    _v("respawnTime", "int", "world", "5",
       "Задержка (сек) перед созданием нового персонажа после смерти."),
    _v("disableRespawnDialog", "bool", "world", "0",
       "Скрыть диалог выбора точки респауна."),
    _v("instanceId", "int", "world", "1",
       "Идентификатор инстанса (папка storage_<id> в миссии)."),
    _v("storageAutoFix", "bool", "world", "1",
       "Автопочинка битого persistence-файла."),
    _v("disable3rdPerson", "bool", "game", "0",
       "Запретить вид от третьего лица."),
    _v("disableCrosshair", "bool", "game", "0",
       "Убрать прицел."),
    _v("disableVoN", "bool", "game", "0",
       "Отключить голосовой чат."),
    _v("vonCodecQuality", "int", "game", "20",
       "Качество кодека голоса (0–30)."),
    _v("enableDebugMonitor", "bool", "game", "0",
       "Показать отладочный монитор игрокам."),
    _v("disableBaseDamage", "bool", "game", "0",
       "Отключить урон по базам (заборы, вышки)."),
    _v("disableContainerDamage", "bool", "game", "0",
       "Отключить урон по контейнерам (палатки, бочки, ящики)."),
    _v("motdInterval", "int", "game", "1",
       "Интервал (сек) между сообщениями motd."),
    _v("steamQueryPort", "int", "net", "2305",
       "Порт Steam Query (обычно порт+2)."),
    _v("clientPort", "int", "net", "2304",
       "Принудительный порт для подключения клиентов."),
    _v("guaranteedUpdates", "bool", "net", "1",
       "Протокол связи с сервером (только 1)."),
    _v("loginQueueConcurrentPlayers", "int", "net", "5",
       "Сколько игроков одновременно обрабатывается при входе."),
    _v("loginQueueMaxPlayers", "int", "net", "500",
       "Максимум игроков в очереди на вход."),
    _v("simulatedPlayersBatch", "int", "net", "20",
       "Лимит игроков, симулируемых за один кадр сервера."),
    _v("multithreadedReplication", "bool", "net", "1",
       "Многопоточная репликация (число потоков — из dayzsettings.xml)."),
    _v("networkRangeClose", "int", "net", "20",
       "Сетевой пузырь (м): ближние объекты с предметами внутри (рюкзаки). По умолчанию 20."),
    _v("networkRangeNear", "int", "net", "150",
       "Сетевой пузырь (м): ближние предметы инвентаря. По умолчанию 150."),
    _v("networkRangeFar", "int", "net", "1000",
       "Сетевой пузырь (м): дальние объекты. По умолчанию 1000."),
    _v("networkRangeDistantEffect", "int", "net", "4000",
       "Сетевой пузырь (м): эффекты (звуки). По умолчанию 4000."),
    _v("defaultVisibility", "int", "net", "1375",
       "Максимальная дальность отрисовки террейна на сервере."),
    _v("defaultObjectViewDistance", "int", "net", "1375",
       "Максимальная дальность отрисовки объектов на сервере."),
    _v("networkObjectBatchLogSlow", "float", "net", "5",
       "Порог (сек): если обработка сетевого «пузыря» занимает дольше — пишется в лог."),
    _v("networkObjectBatchEnforceBandwidthLimits", "bool", "net", "1",
       "Ограничивать создание объектов по статистике использования канала."),
    _v("networkObjectBatchUseEstimatedBandwidth", "bool", "net", "0",
       "0 — реально отправленные данные за прошлый кадр, 1 — грубая оценка."),
    _v("networkObjectBatchUseDynamicMaximumBandwidth", "bool", "net", "1",
       "Лимит канала — доля от текущего максимума, а не жёсткое число."),
    _v("networkObjectBatchBandwidthLimit", "float", "net", "0.8",
       "Сам лимит канала: доля [0,1] или число [1,∞) — смотря что выше."),
    _v("networkObjectBatchCompute", "int", "net", "1000",
       "Сколько объектов на создание/удаление проверяется за один кадр сервера."),
    _v("networkObjectBatchSendCreate", "int", "net", "10",
       "Максимум объектов, отправляемых на создание за кадр."),
    _v("networkObjectBatchSendDelete", "int", "net", "10",
       "Максимум объектов, отправляемых на удаление за кадр."),
    _v("timeStampFormat", "choice", "log", "Short", [("Full", "Full"), ("Short", "Short")],
       "Формат таймштампов в RPT: Full или Short."),
    _v("logAverageFps", "int", "log", "5",
       "Писать средний FPS сервера каждые N секунд (нужен -doLogs)."),
    _v("logMemory", "int", "log", "6",
       "Писать потребление памяти каждые N секунд (нужен -doLogs)."),
    _v("logPlayers", "int", "log", "7",
       "Писать число игроков каждые N секунд (нужен -doLogs)."),
    _v("logFile", "str", "log", "server_console.log",
       "Файл консольного лога сервера в папке профиля."),
    _v("adminLogPlayerHitsOnly", "bool", "log", "0",
       "1 — только попадания по игрокам, 0 — все попадания."),
    _v("adminLogPlacement", "bool", "log", "0",
       "Логировать установку ловушек и палаток."),
    _v("adminLogBuildActions", "bool", "log", "0",
       "Логировать действия базостроения."),
    _v("adminLogPlayerList", "bool", "log", "0",
       "Периодический список игроков с позициями (раз в 5 минут)."),
    _v("serverFpsWarning", "int", "log", "15",
       "FPS сервера, ниже которого показывается предупреждение (минимум 11)."),
)

BY_NAME: dict[str, VarSpec] = {s.name: s for s in SPECS}

# Оставлено ради совместимости: раньше здесь лежал словарь «имя -> тип».
KNOWN_VARS: dict[str, str] = {s.name: s.kind for s in SPECS}


def specs_of_group(group: str) -> list[VarSpec]:
    return [s for s in SPECS if s.group == group]


_VAR_RE = re.compile(r'^(\s*)([A-Za-z_]\w*)\s*=\s*(".*?"|[^;/]*?)\s*;', re.MULTILINE)
_LINE_RE = re.compile(r'^[ \t]*([A-Za-z_]\w*)[ \t]*=[^\n]*?;[^\n]*\n?', re.MULTILINE)


@dataclass
class CfgVar:
    name: str
    value: str        # без кавычек
    quoted: bool
    span: tuple[int, int]  # позиция значения в тексте
    known: bool


def read_text_any(path: Path) -> tuple[str, str]:
    """Читает cfg, возвращает (текст, исходная кодировка)."""
    raw = path.read_bytes()
    if raw.startswith(codecs.BOM_UTF8):
        return raw[len(codecs.BOM_UTF8):].decode("utf-8", errors="replace"), "utf-8-bom"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp1251", errors="replace"), "cp1251"


def write_utf8_no_bom(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def needs_reencode(path: Path) -> bool:
    try:
        _, enc = read_text_any(path)
        return enc != "utf-8"
    except OSError:
        return False


class ServerCfg:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.text, self.encoding = read_text_any(path)

    def variables(self) -> list[CfgVar]:
        """Ключи, которые в файле есть. Вложенные в class-блоки тоже.

        Внутри class Missions лежит template — он настоящий ключ конфига, и
        прятать его от человека только потому, что он в блоке, незачем.
        """
        out = []
        for m in _VAR_RE.finditer(self.text):
            name, raw = m.group(2), m.group(3).strip()
            quoted = raw.startswith('"') and raw.endswith('"')
            value = raw[1:-1] if quoted else raw
            out.append(CfgVar(
                name=name, value=value, quoted=quoted,
                span=(m.start(3), m.end(3)), known=name in BY_NAME,
            ))
        return out

    def values(self) -> dict[str, str]:
        return {v.name: v.value for v in self.variables()}

    def set_values(self, new_values: dict[str, str]) -> None:
        """Меняет значения существующих переменных точечно, справа налево."""
        cfg_vars = [v for v in self.variables() if v.name in new_values]
        for v in sorted(cfg_vars, key=lambda x: x.span[0], reverse=True):
            nv = new_values[v.name]
            raw = f'"{nv}"' if v.quoted else nv
            self.text = self.text[: v.span[0]] + raw + self.text[v.span[1]:]

    def remove(self, names) -> int:
        """Убирает строки с этими ключами целиком, вместе с их комментарием."""
        names = set(names)
        gone = 0

        def drop(m):
            nonlocal gone
            if m.group(1) in names:
                gone += 1
                return ""
            return m.group(0)

        self.text = _LINE_RE.sub(drop, self.text)
        return gone

    def _insert_at(self) -> int:
        """Куда дописывать новый ключ: после последней строки верхнего уровня.

        Не в конец файла: там может стоять закрытая скобка class-блока или
        чужой хвост, и ключ, приписанный после неё, читается хуже. Глубину
        считаем по скобкам — вложенные блоки пропускаем.
        """
        depth = 0
        pos = len(self.text)
        offset = 0
        for line in self.text.splitlines(keepends=True):
            stripped = line.strip()
            if depth == 0 and _LINE_RE.match(line):
                pos = offset + len(line)
            depth += stripped.count("{") - stripped.count("}")
            offset += len(line)
        return pos

    def add(self, name: str, value: str) -> None:
        """Дописывает ключ, которого в файле нет."""
        spec = BY_NAME.get(name)
        raw = f'"{value}"' if (spec.quoted if spec else False) else value
        line = f"{name} = {raw};\n"
        at = self._insert_at()
        if at < len(self.text) and not self.text[:at].endswith("\n"):
            line = "\n" + line
        self.text = self.text[:at] + line + self.text[at:]

    def apply(self, wanted: dict[str, str | None]) -> None:
        """Приводит файл к заданному состоянию за один проход.

        None означает «этого ключа в файле быть не должно». Порядок важен:
        сначала убираем, потом правим существующие, потом дописываем новые —
        иначе позиции значений, посчитанные до удаления, укажут не туда.
        """
        drop = [n for n, v in wanted.items() if v is None]
        if drop:
            self.remove(drop)
        have = self.values()
        change = {n: v for n, v in wanted.items()
                  if v is not None and n in have and have[n] != v}
        if change:
            self.set_values(change)
        for name, value in wanted.items():
            if value is not None and name not in have:
                self.add(name, value)

    def save(self) -> None:
        """Сохраняет всегда в UTF-8 без BOM (перекодирует при необходимости)."""
        write_utf8_no_bom(self.path, self.text)
        self.encoding = "utf-8"
