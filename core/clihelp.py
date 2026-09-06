"""Справка внешнего управления — собранная, а не написанная.

Источник один: список ArgSpec из cliargs, а у аргументов сторон описание
приходит из справочника core/params.py, то есть ровно то, которое человек видит
в окне. Поэтому справка не может устареть: её никто не пишет руками, и добавить
параметр, забыв про документацию, физически нельзя.

Два вида, один источник: render() — человеку, capabilities() — программе.
Второе и есть ответ на вопрос «что умеет вот этот QTS», который инструмент
задаёт вместо того, чтобы гадать по номеру версии.

Ни раскраски, ни рамок: вывод часто едет в панель редактора или в файл, и
управляющие последовательности там мусор.
"""
from __future__ import annotations

import textwrap

from . import cliargs, cliproto
from .i18n import tr
from .params import CLIENT, SERVER

WIDTH = 78
_PAD = "        "

TOPICS = (cliargs.G_BASIC, cliargs.G_MODS, cliargs.G_PACK,
          cliargs.G_PARAMS, cliargs.G_OUTPUT, "exit")

_TITLES = {
    cliargs.G_BASIC: ("cli.help.t_basic", "Что запускаем"),
    cliargs.G_MODS: ("cli.help.t_mods", "Моды и сорсы"),
    cliargs.G_PACK: ("cli.help.t_pack", "Запаковка"),
    cliargs.G_PARAMS: ("cli.help.t_params", "Параметры клиента и сервера"),
    cliargs.G_OUTPUT: ("cli.help.t_output", "Ожидание и вывод"),
    "exit": ("cli.help.t_exit", "Коды возврата"),
}

# Примеры идут первыми и не случайно: справку читают не чтобы изучить, а чтобы
# скопировать. Подпись переводится, команда — нет.
_EXAMPLES = [
    ("cli.help.ex_pack_server", "Собрать изменённое и поднять сервер",
     "qtsctl -preset dev +server +pack -wait"),
    ("cli.help.ex_filepatching", "Поднять сервер и клиент с файлпатчингом, не пересобирая",
     "qtsctl -preset dev +server +client +cFilePatching +sFilePatching -pack"),
    ("cli.help.ex_addmod", "Подключить мод сверх пресета",
     "qtsctl -preset dev +server +mod=@KR_Test +pack -wait"),
    ("cli.help.ex_newmod", "Собрать новый мод из сорсов и подключить",
     "qtsctl -preset dev +server +mod=F:\\Builds\\@KR_New +src=P:\\KR\\NewFeature"),
    ("cli.help.ex_stop", "Потушить", "qtsctl stop"),
]


def _wrap(text: str, indent: str = _PAD) -> str:
    return textwrap.fill(text, width=WIDTH, initial_indent=indent,
                         subsequent_indent=indent)


def _title(topic: str) -> str:
    key, default = _TITLES[topic]
    return tr(key, default)


def _entry(spec: cliargs.ArgSpec) -> str:
    head = f"  {spec.forms()}"
    if spec.param is not None and spec.param.diag_only:
        head += "   " + tr("cli.help.diag_only", "(только Diag)")
    return head + "\n" + _wrap(spec.description())


def _params_page() -> str:
    """Параметры — отдельной страницей и с разбивкой по сторонам.

    Их под три десятка, и плоский список из них не читается: человек ищет
    «что есть у клиента», а не «что есть вообще».
    """
    out = [_title(cliargs.G_PARAMS), ""]
    specs = [s for s in cliargs.all_specs() if s.group == cliargs.G_PARAMS]
    for side, key, default in ((CLIENT, "cli.help.side_client", "Клиент"),
                               (SERVER, "cli.help.side_server", "Сервер")):
        out.append(tr(key, default) + ":")
        for s in sorted((x for x in specs if x.side == side), key=lambda x: x.name.lower()):
            out.append(_entry(s))
        out.append("")
    out.append(_wrap(tr("cli.help.params_note",
                        "Пустое значение снимает параметр, заданный в пресете: "
                        "«-cScrDef=» означает «не передавать его вовсе»."), "  "))
    return "\n".join(out)


def _exit_page() -> str:
    out = [_title("exit"), ""]
    for code in sorted(cliproto.EXIT_NAMES):
        out.append(f"  {code}   {cliproto.EXIT_NAMES[code]}")
    out += ["", _wrap(tr("cli.help.exit_note",
                         "Ошибки скриптов на код возврата не влияют никогда — "
                         "они идут в отчёте отдельным списком, и что с ними "
                         "делать, решает тот, кто запускал."), "  ")]
    return "\n".join(out)


def _group_page(topic: str) -> str:
    out = [_title(topic), ""]
    for s in cliargs.all_specs():
        if s.group == topic:
            out.append(_entry(s))
    return "\n".join(out)


def _general() -> str:
    out = [tr("cli.help.title", "KR QTS — внешнее управление"), ""]

    out.append(tr("cli.help.usage", "Использование") + ":")
    out.append("  qtsctl [" + tr("cli.help.command", "команда") + "] ["
               + tr("cli.help.args", "аргументы") + "]")
    out.append("")

    out.append(tr("cli.help.rule", "Правило знаков") + ":")
    out.append(_wrap(tr("cli.help.rule_minus",
                        "«-» — ровно это: задать значение, заменить список, "
                        "выключить флаг."), "  "))
    out.append(_wrap(tr("cli.help.rule_plus",
                        "«+» — сверх того, что есть: добавить к списку, "
                        "включить флаг."), "  "))
    out.append(_wrap(tr("cli.help.rule_base",
                        "Пресет — база, аргументы — накладка на один запуск: "
                        "в пресет они не записываются."), "  "))
    out.append("")

    out.append(tr("cli.help.examples", "Примеры") + ":")
    for key, caption, cmd in _EXAMPLES:
        out.append(f"  {tr(key, caption)}:")
        out.append(f"    {cmd}")
    out.append("")

    out.append(tr("cli.help.commands", "Команды") + ":")
    out.append("  " + ", ".join(cliargs.COMMANDS) + "   "
               + tr("cli.help.launch_default",
                    "(без команды — запуск)"))
    out.append("")

    out.append(tr("cli.help.topics", "Разделы справки") + ":")
    for topic in TOPICS:
        out.append(f"  -help {topic:<8} {_title(topic)}")
    out.append("")
    out.append(_wrap(tr("cli.help.json_note",
                        "«-help -json» отдаёт то же самое машине: список команд "
                        "и аргументов с типами."), "  "))
    return "\n".join(out)


def render(topic: str = "") -> str:
    """Справка человеку. Пустая тема — общая страница."""
    topic = (topic or "").strip().lower()
    if not topic:
        return _general()
    if topic == cliargs.G_PARAMS:
        return _params_page()
    if topic == "exit":
        return _exit_page()
    if topic in _TITLES:
        return _group_page(topic)
    known = ", ".join(TOPICS)
    return (tr("cli.help.no_topic", "Не знаю раздела «{topic}».").format(topic=topic)
            + "\n" + tr("cli.help.topics", "Разделы справки") + ": " + known)


def capabilities() -> dict:
    """То же самое программе: что умеет именно этот QTS.

    Инструмент спрашивает возможности, а не выводит их из номера версии —
    иначе каждая новая команда требовала бы обновления всех инструментов.
    """
    args = []
    for s in cliargs.all_specs():
        item = {"name": s.name, "group": s.group, "forms": s.forms(),
                "value": s.value, "plus": s.plus, "minus": s.minus,
                "description": s.description()}
        if s.values:
            item["values"] = list(s.values)
        if s.side:
            item["side"] = s.side
        if s.optional:
            item["optional"] = True
        if s.param is not None and s.param.diag_only:
            item["diag_only"] = True
        args.append(item)
    return {"v": cliproto.API,
            "commands": list(cliargs.COMMANDS),
            "args": args,
            "exit_codes": {str(k): v for k, v in cliproto.EXIT_NAMES.items()}}


def _side_line(key: str, title: str, data: dict) -> str:
    """Строка про одну сторону. Стороны разбираем порознь: «сервер поднялся,
    клиент нет» — обычное дело, и общей строкой это не сказать."""
    if not data or not data.get("requested"):
        return f"{title}: " + tr("cli.rep.skip", "не запрашивался")
    if data.get("ready"):
        state = tr("cli.rep.ready", "готов")
    elif data.get("started"):
        state = tr("cli.rep.started", "запущен, готовность не подтверждена")
    else:
        state = tr("cli.rep.down", "не поднялся")
    if data.get("seconds"):
        state += " " + tr("cli.rep.secs", "за {n} c").format(n=data["seconds"])
    bits = [state]
    if data.get("pid"):
        bits.append(f"PID {data['pid']}")
    if data.get("port"):
        bits.append(tr("cli.rep.port", "порт {p}").format(p=data["port"]))
    return f"{title}: " + ", ".join(bits)


def render_report(report: dict) -> str:
    """Отчёт человеку. Печатаем только то, что в отчёте есть: у status и launch
    он разной полноты, а два отдельных вывода разошлись бы через месяц."""
    if not report:
        return tr("cli.rep.empty", "Отчёта нет.")
    out = []
    if report.get("preset"):
        out.append(tr("cli.rep.preset", "Пресет") + ": " + str(report["preset"]))

    pack = report.get("pack") or {}
    items = pack.get("items") or []
    if items:
        # Состав объявляется целиком, а исход — по каждому PBO: приложение
        # выясняет, что паковать, и отчитывается за каждый; разбираться с
        # ошибкой будет тот, кто запускал.
        out.append("")
        out.append(tr("cli.rep.pack", "Запаковка") + f" ({len(items)}):")
        width = max(len(str(i.get("pbo", ""))) for i in items)
        for item in items:
            state = {"ok": tr("cli.rep.pack_ok", "ок"),
                     "fail": tr("cli.rep.pack_fail", "ошибка"),
                     "packing": tr("cli.rep.pack_now", "идёт"),
                     "wait": tr("cli.rep.pack_wait", "в очереди"),
                     }.get(item.get("status", ""), item.get("status", ""))
            line = f"  {str(item.get('pbo', '')):<{width}}  {state}"
            if item.get("ms"):
                line += tr("cli.rep.pack_secs", "   {n} c").format(
                    n=round(item["ms"] / 1000, 1))
            counts = []
            if item.get("errors"):
                counts.append(tr("cli.rep.pack_errors", "ошибок {n}").format(
                    n=item["errors"]))
            if item.get("warnings"):
                counts.append(tr("cli.rep.pack_warnings", "предупреждений {n}").format(
                    n=item["warnings"]))
            if counts:
                line += "   " + ", ".join(counts)
            out.append(line)

    if report.get("error"):
        out.append("")
        out.append(str(report["error"]))

    if report.get("server") or report.get("client"):
        out.append("")
        out.append(_side_line("server", tr("cli.help.side_server", "Сервер"),
                              report.get("server") or {}))
        out.append(_side_line("client", tr("cli.help.side_client", "Клиент"),
                              report.get("client") or {}))

    problems = report.get("problems") or []
    if problems:
        out.append("")
        out.append(tr("cli.rep.problems", "Проблемы") + f" ({len(problems)}):")
        for p in problems:
            where = p.get("side", "")
            line = p.get("line")
            head = f"  {where}" + (f", {line}" if line else "") + ": "
            out.append(head + str(p.get("text", "")).strip())

    logs = []
    for side in ("server", "client"):
        for name, path in (report.get(side, {}).get("logs") or {}).items():
            if path:
                logs.append(f"  {side} {name:<8} {path}")
    if logs:
        out.append("")
        out.append(tr("cli.rep.logs", "Логи") + ":")
        out += logs
    return "\n".join(out)
