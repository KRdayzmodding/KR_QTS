"""Проверка грамматики внешнего управления: python tests/cli.py

Ни Qt, ни запущенного приложения не требует — разбор аргументов обязан
работать сам по себе, в том числе внутри qtsctl на машине без QTS.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import cliargs
from core.cliargs import CliError, parse

_fails: list[str] = []


def check(cond: bool, what: str) -> None:
    if not cond:
        _fails.append(what)


def bad(argv: list[str], expect: str = "") -> None:
    """Команда обязана быть отвергнута, и сообщение — назвать причину."""
    try:
        parse(argv)
    except CliError as e:
        if expect and expect.lower() not in e.full().lower():
            _fails.append(f"{argv}: ошибка не про то — {e.full()!r}")
        return
    _fails.append(f"{argv}: разобрано, хотя должно быть отвергнуто")


def test_basic() -> None:
    r = parse(["-preset", "dev", "+server", "-client"])
    check(r.command == cliargs.LAUNCH, "запуск — команда по умолчанию")
    check(r.overlay.preset == "dev", "-preset значением следующим словом")
    check(r.overlay.server is True, "+server включает")
    check(r.overlay.client is False, "-client выключает")

    r = parse(["-preset=dev"])
    check(r.overlay.preset == "dev", "-preset= через равно")

    r = parse([])
    check(r.overlay.server is None and r.overlay.client is None,
          "без аргументов стороны берутся из пресета")

    for name in ("stop", "status", "show", "quit"):
        check(parse([name]).command == name, f"команда {name}")
    check(parse(["stop", "+server"]).overlay.server is True, "stop с уточнением")


def test_params() -> None:
    r = parse(["+cFilePatching", "-sFilePatching"])
    check(r.overlay.params_client == {"filePatching": True}, "+cFilePatching")
    check(r.overlay.params_server == {"filePatching": False}, "-sFilePatching")

    r = parse(["+CFILEPATCHING"])
    check(r.overlay.params_client == {"filePatching": True}, "регистр не важен")

    r = parse(["-cpuCount=4", "-limitFPS", "60"])
    check(r.overlay.params_server == {"cpuCount": 4, "limitFPS": 60},
          "односторонние параметры без приставки")

    r = parse(["-name=Тест", "-window"])
    check(r.overlay.params_client.get("name") == "Тест", "строковый параметр")
    check(r.overlay.params_client.get("window") is False, "флаг клиента минусом")

    r = parse(["-cScrDef="])
    check(r.overlay.params_client == {"scrDef": None},
          "пустое значение снимает параметр пресета")

    r = parse(["-cExtra=-world=empty -noSplash"])
    check(r.overlay.extra_client == "-world=empty -noSplash",
          "сквозной проход не режется по первому равно")

    bad(["-cpuCount=много"], "число")
    bad(["+cpuCount=4"], "нет формы")
    bad(["-cFilePathing"], "cFilePatching")       # опечатка называет похожее
    bad(["--server"], "не знаю")
    bad(["+preset=dev"], "нет формы")


def test_mods() -> None:
    r = parse(["-mod=A,B", "+mod=C"])
    check(r.overlay.mods_replace == ["A", "B"], "-mod заменяет список")
    check([m.ref for m in r.overlay.mods] == ["C"], "+mod добавляет")

    r = parse(["+mod=A;B"])
    check([m.ref for m in r.overlay.mods] == ["A", "B"],
          "точка с запятой принимается как запятая")

    r = parse(["+serverMod=@Adm"])
    check(r.overlay.mods[0].side == cliargs.SIDE_SERVER, "сторона задаётся ключом")

    r = parse(["+mod=@KR_Test", "+src=P:\\KR\\Scripts", "+src=P:\\KR\\GUI"])
    mod = r.overlay.mods[0]
    check(mod.add_sources == ["P:\\KR\\Scripts", "P:\\KR\\GUI"],
          "несколько папок сорсов у одного мода")

    r = parse(["+mod=@A", "+src=P:\\a", "+mod=@B", "+src=P:\\b"])
    check([m.add_sources for m in r.overlay.mods] == [["P:\\a"], ["P:\\b"]],
          "сорсы достаются последнему моду, а не первому")

    r = parse(["+mod=@A", "+mod=@B", "+src:@A=P:\\a"])
    check(r.overlay.mods[0].add_sources == ["P:\\a"], "явная форма адресует мод")
    check(not r.overlay.mods[1].add_sources, "явная форма не задела соседа")

    r = parse(["+mod=@A", "-src=P:\\old"])
    check(r.overlay.mods[0].drop_sources == ["P:\\old"], "-src снимает привязку")

    r = parse(["-forget=@Old,@Older"])
    check(r.overlay.forget == ["@Old", "@Older"], "-forget списком")

    r = parse(["+mod=F:\\Builds\\@New", "+src=P:\\KR\\New"])
    check(r.overlay.mods[0].ref == "F:\\Builds\\@New", "мод путём, а не именем")

    bad(["+src=P:\\a"], "раньше первого")
    bad(["+mod=@A", "+src:@B=P:\\b"], "не подключён")
    bad(["+forget=@A"], "нет формы")


def test_pack_and_wait() -> None:
    check(parse(["+pack"]).overlay.pack == cliargs.PACK_DEFAULT, "+pack как настроено")
    check(parse(["+pack=full"]).overlay.pack == "full", "+pack=full")
    check(parse(["-pack"]).overlay.pack == "", "-pack не паковать")
    check(parse([]).overlay.pack is None, "без -pack решает приложение")
    check(parse(["+rebuild"]).overlay.rebuild is True, "+rebuild")

    check(parse(["-wait"]).wait == cliargs.WAIT_DEFAULT, "-wait без числа")
    check(parse(["-wait=180"]).wait == 180, "-wait=180")
    check(parse(["-timeout", "300"]).timeout == 300, "-timeout следующим словом")
    check(parse(["+detach"]).detach is True, "+detach")
    check(parse(["-json"]).as_json is True, "-json")

    bad(["+pack=быстро"], "не знаю тип")
    bad(["+detach", "-wait=10"], "противоположного")


def test_help() -> None:
    r = parse(["-help"])
    check(r.command == cliargs.HELP and not r.help_topic, "-help без раздела")
    check(parse(["-help", "mods"]).help_topic == "mods", "-help с разделом")
    check(parse(["-help=params"]).help_topic == "params", "-help через равно")


def test_specs() -> None:
    """Справочник обязан оставаться согласованным: по нему строится справка."""
    specs = cliargs.all_specs()
    names = [s.name for s in specs]
    check(len(names) == len(set(names)), "имена аргументов не повторяются")
    check(all(s.plus or s.minus for s in specs), "у аргумента есть хоть одна форма")
    check(all(s.description() for s in specs), "у каждого аргумента есть описание")
    check(all(cliargs.find(s.name.upper()) is s for s in specs),
          "поиск без учёта регистра находит всё")

    from core.params import PARAMS, BOTH
    both = sum(1 for p in PARAMS if p.target == BOTH)
    from_params = [s for s in specs if s.param is not None]
    check(len(from_params) == len(PARAMS) + both,
          "у параметра обеих сторон две формы, у остальных одна")


class FakeRegistry:
    """Реестр на словаре: plan() читает только get() и mods, значит настоящее
    сканирование диска для проверки не нужно."""

    def __init__(self, mods: dict) -> None:
        self.mods = mods
        self.saved = False

    def get(self, name):
        from core.mods import as_folder
        return self.mods.get(as_folder(name).lower())

    def save_sources(self) -> None:
        self.saved = True


def _registry():
    from core.mods import ModInfo, SOURCE_LOCAL
    return FakeRegistry({
        "@kr_core": ModInfo(name="KR_Core", path=r"F:\mods\@KR_Core",
                            source=SOURCE_LOCAL, has_keys=True,
                            sources=[r"P:\KR\Core_Scripts"]),
        "@kr_test": ModInfo(name="KR_Test", path=r"F:\mods\@KR_Test",
                            source=SOURCE_LOCAL, has_keys=True),
    })


def _preset():
    from core.presets import ServerPreset
    return ServerPreset(name="dev", mods=["KR_Core"], server_mods=[],
                        params_client={"filePatching": False, "scrDef": "X"},
                        params_server={"cpuCount": 8})


def test_plan_three_cases() -> None:
    """Три случая из документа: мод со всем, мод без сорсов, мода нет нигде."""
    from core import overlay

    reg = _registry()
    p = overlay.plan(parse([r"+mod=@KR_Test"]).overlay, reg)
    check(p.add_mods == ["KR_Test"] and not p.register and not p.bind,
          "случай 1: мод в списке, сорсы привязаны — заводить нечего")

    p = overlay.plan(parse([r"+mod=@KR_Test", r"+src=P:\KR\Test"]).overlay, reg)
    check(p.bind == [("@kr_test", r"P:\KR\Test")] and not p.register,
          "случай 2: мод есть, сорсы привязываем")

    p = overlay.plan(parse([r"+mod=F:\Builds\@KR_New", r"+src=P:\KR\New"]).overlay, reg)
    check([r.key for r in p.register] == ["@kr_new"], "случай 3: мод заводится")
    check(p.register[0].name == "KR_New", "имя мода — по имени папки")
    check(p.bind == [("@kr_new", r"P:\KR\New")], "и сорсы к нему")
    check(p.add_mods == ["KR_New"], "новый мод уходит в запуск")
    check(any(n.kind == overlay.N_REGISTERED for n in p.notes),
          "о заведённом моде сказано в отчёте")

    p = overlay.plan(parse([r"+mod=@KR_Core", r"+src=P:\KR\Core_Scripts"]).overlay, reg)
    check(not p.bind, "повторная привязка той же папки ничего не делает")

    p = overlay.plan(parse([r"+mod=@A", r"+src=P:\x",
                            r"+mod=@B", r"+src=P:\x"]).overlay, reg)
    check(any(n.kind == overlay.N_SHARED_SOURCE for n in p.notes),
          "одна папка сорсов у двух модов — предупреждаем")

    p = overlay.plan(parse([r"-forget=@KR_Test"]).overlay, reg)
    check(p.forget == ["@kr_test"], "-forget по имени мода")


def test_apply() -> None:
    from core import overlay

    reg = _registry()
    ov = parse(["+server", "-client", "+cFilePatching", "-cScrDef=",
                "+mod=@KR_Test", "-cExtra=-world=empty"]).overlay
    got = overlay.apply(_preset(), ov, overlay.plan(ov, reg))

    check(got.launch_server is True and got.launch_client is False,
          "стороны из накладки")
    check(got.params_client.get("filePatching") is True, "флаг перебит накладкой")
    check("scrDef" not in got.params_client, "пустое значение снимает параметр")
    check(got.params_server == {"cpuCount": 8}, "чужая сторона не тронута")
    check(got.mods == ["KR_Core", "KR_Test"], "добавленный мод встаёт в конец")
    check(got.extra_client == "-world=empty", "сквозной проход")

    base = _preset()
    ov = parse(["-mod=Only"]).overlay
    got = overlay.apply(base, ov, overlay.plan(ov, reg))
    check(got.mods == ["Only"], "-mod заменяет список целиком")
    check(base.mods == ["KR_Core"], "исходный пресет не изменился")

    ov = parse(["+mod=KR_Core"]).overlay
    got = overlay.apply(_preset(), ov, overlay.plan(ov, reg))
    check(got.mods == ["KR_Core"], "повторное добавление не двоит мод")

    ov = parse([r"+serverMod=@KR_Test"]).overlay
    got = overlay.apply(_preset(), ov, overlay.plan(ov, reg))
    check(got.server_mods == ["KR_Test"] and got.mods == ["KR_Core"],
          "серверный мод не попадает клиенту")


def main() -> int:
    for fn in (test_basic, test_params, test_mods, test_pack_and_wait,
               test_help, test_specs, test_plan_three_cases, test_apply):
        fn()
    if _fails:
        print(f"НЕ ПРОШЛО ({len(_fails)}):")
        for f in _fails:
            print("  -", f)
        return 1
    print(f"грамматика: всё сошлось, аргументов в справочнике "
          f"{len(cliargs.all_specs())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
