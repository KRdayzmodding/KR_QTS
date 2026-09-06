"""Разбор аргументов внешнего управления.

Правило одно на всю грамматику, и если оно понято, остальное выводится:

    «-» — ровно это: задать значение, заменить список, выключить флаг.
    «+» — сверх того, что есть: добавить к списку, включить флаг.

Пресет остаётся базой, аргументы — накладка на один запуск: ничего из
разобранного здесь в пресет не пишется. Исключение одно и намеренное —
привязки модов и сорсов (см. Overlay.mods), они по своей природе постоянные.

Список аргументов сторон не написан руками, а собран из справочника
core/params.py: каждый ParamSpec уже знает свою сторону, тип и описание на трёх
языках. Поэтому новый параметр появляется в командной строке, в справке и в
форме настроек одновременно, и разойтись они не могут.

Модуль намеренно не знает ни про Qt, ни про приложение: его гоняют тесты, и он
же работает внутри qtsctl, где ничего кроме стандартной библиотеки нет.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from .params import BOTH, CLIENT, FLAG, INT, SERVER, SWITCH, PARAMS, ParamSpec

# Команды. Пустая строка запроса означает запуск: «qtsctl -preset dev +server»
# читается лучше, чем «qtsctl launch -preset dev +server», а launch оставлен для
# тех, кто предпочитает писать глагол явно.
LAUNCH = "launch"
STOP = "stop"
RESTART = "restart"
STATUS = "status"
SHOW = "show"
QUIT = "quit"
HELP = "help"
COMMANDS = (LAUNCH, RESTART, STOP, STATUS, SHOW, QUIT, HELP)

# Группы — только для справки: плоский список из полусотни строк не читается.
G_BASIC = "basic"
G_MODS = "mods"
G_PACK = "pack"
G_PARAMS = "params"
G_OUTPUT = "output"

# Значения -pack. Пустая строка — «не паковать»; DEFAULT — «как настроено в
# приложении». Третьего состояния «не задано» в самих значениях нет: его
# выражает None в Overlay, иначе пришлось бы гадать, что значит пустая строка.
PACK_DEFAULT = "default"
PACK_MODES = ("normal", "full")

WAIT_DEFAULT = 300      # секунд, если у -wait не задано своё число

SIDE_BOTH = "both"
SIDE_SERVER = "server"


class CliError(Exception):
    """Ошибка разбора. text — готовое сообщение человеку, с подсказкой."""

    def __init__(self, text: str, hint: str = "") -> None:
        super().__init__(text)
        self.text = text
        self.hint = hint

    def full(self) -> str:
        return f"{self.text}\n{self.hint}" if self.hint else self.text


@dataclass(frozen=True)
class ArgSpec:
    """Один аргумент командной строки — он же строка справки, он же ответ
    capabilities. Один источник, три применения: расходиться нечему."""

    name: str                 # каноническое имя без знака
    group: str
    value: str = ""           # "" | "int" | "str" | "list" | "enum" | "path"
    plus: bool = True         # есть ли форма со знаком «+»
    minus: bool = True        # есть ли форма со знаком «-»
    values: tuple = ()        # допустимые значения для enum
    side: str = ""            # client | server | "" — к кому относится
    optional: bool = False    # значение можно не писать: у -wait есть своё
    hint: str = ""            # как назвать значение в справке, если не по типу
    minus_value: bool = True  # берёт ли значение форма с минусом («-pack» — нет)
    param: ParamSpec | None = None   # если аргумент рождён справочником
    help: str = ""            # описание; у параметров берётся из справочника

    def description(self) -> str:
        """Описание аргумента.

        У параметров сторон оно приходит из справочника — то же самое, что
        человек видит подсказкой в окне. У остальных лежит здесь, но всё равно
        через словарь: правка формулировки должна идти во все языки разом.
        """
        from .i18n import tr
        if self.param is not None:
            return self.param.tooltip()
        return tr(f"cli.arg.{self.name}", self.help)

    def placeholder(self) -> str:
        """Как назвать значение в справке.

        «+mod=A,B» объясняет форму сразу, «+mod=знач» заставляет читать
        описание. Слово стоит того, чтобы его подобрать.
        """
        from .i18n import tr
        if self.hint:
            return tr(f"cli.v.{self.name}", self.hint)
        return {
            "int": tr("cli.v.num", "N"),
            "list": tr("cli.v.list", "A,B"),
            "path": tr("cli.v.path", "путь"),
            "enum": "|".join(self.values),
        }.get(self.value, tr("cli.v.text", "текст"))

    def forms(self) -> str:
        """Как аргумент выглядит в справке: «+cFilePatching / -cFilePatching»."""
        out = []
        for sign, on in (("+", self.plus), ("-", self.minus)):
            if not on:
                continue
            if not self.value or (sign == "-" and not self.minus_value):
                tail = ""
            elif self.optional:
                tail = f"[={self.placeholder()}]"
            else:
                tail = f"={self.placeholder()}"
            out.append(f"{sign}{self.name}{tail}")
        return " / ".join(out)


def _cap(name: str) -> str:
    return name[:1].upper() + name[1:]


def _param_specs() -> list[ArgSpec]:
    """Аргументы сторон — из справочника.

    Параметр, применимый к обеим сторонам, даёт две формы с приставкой c/s:
    иначе непонятно, кому именно менять filePatching. Односторонний идёт без
    приставки: -storage бывает только у сервера, -window только у клиента,
    путать нечего, а лишняя буква — лишний повод ошибиться.
    """
    out: list[ArgSpec] = []
    for p in PARAMS:
        kind = "" if p.ptype in (FLAG, SWITCH) else ("int" if p.ptype == INT else "str")
        pairs = ([("c" + _cap(p.name), CLIENT), ("s" + _cap(p.name), SERVER)]
                 if p.target == BOTH else [(p.name, p.target)])
        for name, side in pairs:
            out.append(ArgSpec(
                name=name, group=G_PARAMS, value=kind, param=p, side=side,
                # У параметра со значением формы с плюсом нет: «добавить
                # -cpuCount=4» не значит ничего. У флага есть обе — в этом
                # весь смысл накладки поверх пресета.
                plus=(kind == ""), minus=True,
            ))
    return out


_STATIC: list[ArgSpec] = [
    ArgSpec("preset", G_BASIC, value="str", plus=False,
            hint="имя",
            help="Пресет, который берётся за основу запуска."),
    ArgSpec("server", G_BASIC,
            help="Поднимать сервер. Минус — не поднимать, даже если так в пресете."),
    ArgSpec("client", G_BASIC,
            help="Поднимать клиент. Минус — не поднимать, даже если так в пресете."),

    ArgSpec("hard", G_BASIC,
            help="Гасить принудительно, не дожидаясь корректного завершения. "
                 "Минус — наоборот, только по-хорошему. Без знака — как "
                 "настроено в программе."),

    ArgSpec("start", G_BASIC, minus=False,
            help="Поднять QTS, если он не запущен: окно не показывается, "
                 "программа уходит в трей."),

    ArgSpec("mod", G_MODS, value="list",
            help="Моды на клиент и сервер. Плюс добавляет к пресету, "
                 "минус заменяет список целиком."),
    ArgSpec("serverMod", G_MODS, value="list",
            help="То же, но только на сервер."),
    ArgSpec("src", G_MODS, value="path",
            help="Папка сорсов последнего мода. Плюс привязывает, минус снимает. "
                 "Явная форма: +src:@Мод=путь."),
    ArgSpec("forget", G_MODS, value="str", plus=False,
            hint="@Мод",
            help="Забыть запись о моде. Файлы не трогает никогда."),

    ArgSpec("pack", G_PACK, value="enum", values=PACK_MODES, optional=True,
            minus_value=False,
            help="Запаковать изменённые сорсы модов запуска. "
                 "Минус — не паковать вовсе."),
    ArgSpec("rebuild", G_PACK, minus=False,
            help="Пересобрать всё, а не только изменившееся."),

    ArgSpec("wait", G_OUTPUT, value="int", plus=False, optional=True,
            hint="сек",
            help="Ждать готовности, не дольше указанного числа секунд. "
                 "Для консоли включено по умолчанию."),
    ArgSpec("timeout", G_OUTPUT, value="int", plus=False,
            hint="сек",
            help="Общий потолок ожидания. Запаковка считается отдельно."),
    ArgSpec("detach", G_OUTPUT, minus=False,
            help="Вернуть управление сразу, не дожидаясь готовности."),
    ArgSpec("json", G_OUTPUT, value="", plus=False,
            help="Машинный отчёт вместо человеческого."),
    ArgSpec("help", G_OUTPUT, value="str", plus=False, optional=True,
            hint="раздел",
            help="Справка по разделу: commands, basic, mods, pack, params, "
                 "output, exit."),
]

# Сквозной проход. Держим отдельно от справочника: это не параметр DayZ, а
# способ передать любой будущий параметр, не выпуская новую версию QTS.
_EXTRA: list[ArgSpec] = [
    ArgSpec("cExtra", G_PARAMS, value="str", plus=False, side=CLIENT,
            hint="аргументы",
            help="Дописать клиенту произвольные аргументы как есть."),
    ArgSpec("sExtra", G_PARAMS, value="str", plus=False, side=SERVER,
            hint="аргументы",
            help="Дописать серверу произвольные аргументы как есть."),
]


_ALL: list[ArgSpec] = []
_INDEX: dict[str, ArgSpec] = {}


def all_specs() -> list[ArgSpec]:
    """Полный список аргументов. Собирается один раз: он статичен, а по нему
    строятся и справка, и ответ capabilities, и разбор."""
    global _ALL
    if not _ALL:
        _ALL = _STATIC + _EXTRA + _param_specs()
    return _ALL


def find(name: str) -> ArgSpec | None:
    """Поиск без учёта регистра: +cfilepatching и +cFilePatching — одно и то же.

    Человек пишет из головы, а не сверяясь со справочником; заставлять его
    помнить, где в имени большая буква, — верный способ получить ошибку на
    ровном месте.
    """
    global _INDEX
    if not _INDEX:
        _INDEX = {s.name.lower(): s for s in all_specs()}
    return _INDEX.get(name.lower())


@dataclass
class ModRef:
    """Мод в накладке: чем подключаем и что к нему привязываем.

    ref — либо имя из реестра («@KR_Test» или «KR_Test»), либо путь к папке
    мода. Путь нужен для третьего случая, когда мода в реестре ещё нет.
    """

    ref: str
    side: str = SIDE_BOTH
    add_sources: list[str] = field(default_factory=list)
    drop_sources: list[str] = field(default_factory=list)


@dataclass
class Overlay:
    """Накладка на пресет. None везде значит «как в пресете»."""

    preset: str = ""
    start: bool = False              # поднять QTS, если он не запущен
    hard: bool | None = None         # None — способ остановки из настроек
    server: bool | None = None
    client: bool | None = None
    params_client: dict = field(default_factory=dict)
    params_server: dict = field(default_factory=dict)
    extra_client: str = ""
    extra_server: str = ""
    mods_replace: list[str] | None = None
    server_mods_replace: list[str] | None = None
    mods: list[ModRef] = field(default_factory=list)
    forget: list[str] = field(default_factory=list)
    pack: str | None = None          # None — как настроено; "" — не паковать
    rebuild: bool = False


@dataclass
class Request:
    """Разобранный вызов целиком."""

    command: str = LAUNCH
    overlay: Overlay = field(default_factory=Overlay)
    wait: int | None = None
    timeout: int | None = None
    detach: bool = False
    as_json: bool = False
    help_topic: str = ""

    def wants(self, side: str) -> bool | None:
        return self.overlay.server if side == SERVER else self.overlay.client


def _split(token: str) -> tuple[str, str, str, str, bool]:
    """Разбирает «+src:@Мод=P:\\путь» на знак, имя, уточнение и значение.

    Двоеточие ищем только до первого «=»: в значении оно почти всегда есть —
    это буква диска, — и разбор по последнему двоеточию ломался бы на любом
    пути к сорсам.
    """
    sign, body = token[0], token[1:]
    name, _, value = body.partition("=")
    qualifier = ""
    if ":" in name:
        name, _, qualifier = name.partition(":")
    return sign, name, qualifier, value, "=" in body


def _as_list(value: str) -> list[str]:
    """Список через запятую. Точку с запятой принимаем молча.

    Показываем везде запятую: точка с запятой разрывает команду в PowerShell,
    и «скопировал из документации — не работает» мы себе позволить не можем.
    А в чужих скриптах она встретится, потому что так пишет сам DayZ.
    """
    parts = value.replace(";", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


def _int(spec: ArgSpec, raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        raise CliError(f"У -{spec.name} должно быть число, а не «{raw}».") from None


def _suggest(name: str) -> str:
    names = [s.name for s in all_specs()]
    near = difflib.get_close_matches(name, names, n=2, cutoff=0.6)
    if near:
        return "Похоже на " + " или ".join(f"«{n}»" for n in near) + "."
    return "Полный список: -help params."


def parse(argv: list[str]) -> Request:
    """Разбирает аргументы. Бросает CliError с готовым текстом для человека.

    Неизвестный аргумент — всегда ошибка, никогда не молчание: опечатка в
    «+cFilePathing» при молчаливом пропуске даст «тест прошёл» там, где
    проверялось совсем не то.
    """
    req = Request()
    ov = req.overlay
    last_mod: ModRef | None = None
    command_seen = False
    i = 0

    while i < len(argv):
        token = argv[i]
        i += 1
        if not token:
            continue

        if token[0] not in "+-":
            low = token.lower()
            if low in COMMANDS and not command_seen:
                req.command = low
                command_seen = True
                continue
            raise CliError(
                f"Не понял «{token}»: команда должна идти первой, "
                "а у аргументов есть знак.",
                "Команды: " + ", ".join(COMMANDS) + ". Справка: -help.")

        sign, name, qualifier, value, explicit = _split(token)
        if not name:
            raise CliError(f"Пустое имя аргумента в «{token}».")
        spec = find(name)
        if spec is None:
            raise CliError(f"Не знаю «{token}».", _suggest(name))

        plus = sign == "+"
        if plus and not spec.plus:
            raise CliError(f"У «{spec.name}» нет формы со знаком «+».",
                           f"Нужно: -{spec.name}"
                           f"{'=знач' if spec.value else ''}.")
        if not plus and not spec.minus:
            raise CliError(f"У «{spec.name}» нет формы со знаком «-».",
                           f"Нужно: +{spec.name}.")

        # Значение следующим словом: «-preset dev» человек напишет скорее,
        # чем «-preset=dev», и обе формы должны работать. Для enum эту вольность
        # не даём: «+pack stop» прочиталось бы как тип запаковки «stop».
        if spec.value and not explicit and spec.value != "enum":
            if i < len(argv) and argv[i][:1] not in "+-":
                value, explicit = argv[i], True
                i += 1
        # Пустое значение после «=» — осмысленно: «-cScrDef=» снимает параметр,
        # заданный в пресете, «-mod=» запускает вовсе без модов. А вот значение,
        # которое просто забыли написать, — ошибка, кроме тех аргументов, у
        # которых есть своё умолчание.
        if spec.value and not explicit and not spec.optional:
            raise CliError(f"У «{spec.name}» пропущено значение.",
                           f"Нужно: {sign}{spec.name}=знач.")

        key = spec.name

        if key == "preset":
            ov.preset = value
        elif key == "start":
            ov.start = True
        elif key == "hard":
            ov.hard = plus
        elif key == "server":
            ov.server = plus
        elif key == "client":
            ov.client = plus
        elif key in ("mod", "serverMod"):
            side = SIDE_BOTH if key == "mod" else SIDE_SERVER
            names = _as_list(value)
            if not plus:                    # «-mod=» без значения — без модов
                if side == SIDE_BOTH:
                    ov.mods_replace = names
                else:
                    ov.server_mods_replace = names
                last_mod = None
            else:
                for n in names:
                    last_mod = ModRef(ref=n, side=side)
                    ov.mods.append(last_mod)
        elif key == "src":
            target = last_mod
            if qualifier:
                target = next((m for m in ov.mods
                               if m.ref.lstrip("@").lower() == qualifier.lstrip("@").lower()),
                              None)
                if target is None:
                    raise CliError(
                        f"«{token}»: мод «{qualifier}» в этой команде не подключён.",
                        "Явная форма работает только для мода, который есть "
                        "в этой же команде.")
            if target is None:
                raise CliError(
                    f"«{token}» стоит раньше первого +mod.",
                    "Сорсы принадлежат моду: сначала +mod=..., потом +src=... "
                    "к нему. Либо явно: +src:@Мод=путь.")
            (target.add_sources if plus else target.drop_sources).append(value)
        elif key == "forget":
            ov.forget.extend(_as_list(value))
        elif key == "pack":
            ov.pack = "" if not plus else (value or PACK_DEFAULT)
            if ov.pack not in ("", PACK_DEFAULT) and ov.pack not in PACK_MODES:
                raise CliError(f"Не знаю тип запаковки «{value}».",
                               "Бывают: " + ", ".join(PACK_MODES) + ". "
                               "Без значения — как настроено в приложении.")
        elif key == "rebuild":
            ov.rebuild = True
        elif key == "wait":
            req.wait = _int(spec, value) if value else WAIT_DEFAULT
        elif key == "timeout":
            req.timeout = _int(spec, value)
        elif key == "detach":
            req.detach = True
        elif key == "json":
            req.as_json = True
        elif key == "help":
            req.command = HELP
            command_seen = True
            req.help_topic = value
        elif key in ("cExtra", "sExtra"):
            if key[0] == "c":
                ov.extra_client = value
            else:
                ov.extra_server = value
        elif spec.param is not None:
            bag = ov.params_client if spec.side == CLIENT else ov.params_server
            p = spec.param
            if p.ptype in (FLAG, SWITCH):
                bag[p.name] = plus
            elif not value:
                bag[p.name] = None      # снять параметр, заданный в пресете
            else:
                bag[p.name] = _int(spec, value) if p.ptype == INT else value
        else:                                   # pragma: no cover — недостижимо
            raise CliError(f"Аргумент «{spec.name}» разобран, но не применён.")

    if req.detach and req.wait is not None:
        raise CliError("+detach и -wait просят противоположного.",
                       "Оставь что-то одно.")
    return req
