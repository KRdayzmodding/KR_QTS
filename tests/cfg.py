"""Проверка правки serverDZ.cfg: python tests/cfg.py

Файл конфига люди правят руками и держат в нём свои пометки. Поэтому проверяем
не только «значение поменялось», но и «всё остальное осталось на месте»:
комментарии, порядок строк, чужие ключи, вложенные блоки.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import servercfg
from core.servercfg import ServerCfg

_fails: list[str] = []

SAMPLE = """// комментарий сверху
hostname = "Test";                 // название
maxPlayers = 10;
verifySignatures = 0;

class Missions
{
    class DayZ
    {
        template = "dayzOffline.chernarusplus";
    };
};

disableBanlist = false;
ownCustomKey = 42;                 // чужой ключ, не наш
"""


def check(cond: bool, what: str) -> None:
    if not cond:
        _fails.append(what)


def cfg_from(text: str) -> ServerCfg:
    tmp = Path(tempfile.mkdtemp()) / "serverDZ.cfg"
    tmp.write_text(text, encoding="utf-8")
    return ServerCfg(tmp)


def test_specs() -> None:
    names = [s.name for s in servercfg.SPECS]
    check(len(names) == len(set(names)), "имена ключей не повторяются")
    check(all(s.group in servercfg.GROUPS for s in servercfg.SPECS),
          "у каждого ключа известная группа")
    check(all(s.hint for s in servercfg.SPECS), "у каждого ключа есть пояснение")
    check(all(s.choices for s in servercfg.SPECS if s.kind == servercfg.CHOICE),
          "у ключа с выбором перечислены варианты")
    check(servercfg.BY_NAME["hostname"].quoted, "строка пишется в кавычках")
    check(not servercfg.BY_NAME["maxPlayers"].quoted, "число пишется без кавычек")


def test_read() -> None:
    cfg = cfg_from(SAMPLE)
    got = cfg.values()
    check(got.get("hostname") == "Test", "строковое значение читается без кавычек")
    check(got.get("maxPlayers") == "10", "числовое значение читается")
    check(got.get("template") == "dayzOffline.chernarusplus",
          "ключ внутри class-блока тоже виден")
    check(got.get("ownCustomKey") == "42", "чужой ключ читается")
    check(not servercfg.BY_NAME.get("ownCustomKey"), "чужой ключ не считается известным")


def test_change() -> None:
    cfg = cfg_from(SAMPLE)
    cfg.set_values({"hostname": "KR", "maxPlayers": "60"})
    check('hostname = "KR";' in cfg.text, "строка меняется вместе с кавычками")
    check("maxPlayers = 60;" in cfg.text, "число меняется без кавычек")
    check("// название" in cfg.text, "комментарий на строке остался")
    check("// комментарий сверху" in cfg.text, "комментарий сверху остался")


def test_add() -> None:
    cfg = cfg_from(SAMPLE)
    cfg.add("instanceId", "1")
    cfg.add("logFile", "server_console.log")
    check("instanceId = 1;" in cfg.text, "новый числовой ключ дописан")
    check('logFile = "server_console.log";' in cfg.text,
          "новый строковый ключ дописан в кавычках")
    # дописывать надо на верхний уровень, а не внутрь class-блока
    before_class = cfg.text.split("class Missions")[0]
    after_class = cfg.text.split("};")[-1]
    check("instanceId" in before_class or "instanceId" in after_class,
          "новый ключ не попал внутрь class-блока")
    check(cfg.values().get("instanceId") == "1", "дописанный ключ читается обратно")


def test_add_line_endings() -> None:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "serverDZ.cfg"
        for original, expected in (
            (b"", b"maxPlayers = 42;\n"),
            (b"// note", b"// note\nmaxPlayers = 42;\n"),
            (b'hostname = "KR";', b'hostname = "KR";\nmaxPlayers = 42;\n'),
            (b'hostname = "KR"; // note', b'hostname = "KR"; // note\nmaxPlayers = 42;\n'),
            (b'// note\r\nhostname = "KR";', b'// note\r\nhostname = "KR";\r\nmaxPlayers = 42;\r\n'),
            (b'hostname = "KR";\r\n// note', b'hostname = "KR";\r\nmaxPlayers = 42;\r\n// note'),
            (b'hostname = "KR";\n// note', b'hostname = "KR";\nmaxPlayers = 42;\n// note'),
        ):
            path.write_bytes(original)
            cfg = ServerCfg(path)
            cfg.apply({"maxPlayers": "42"})
            cfg.save()
            check(path.read_bytes() == expected, f"перенос строки при добавлении в {original!r}")
            check(ServerCfg(path).values().get("maxPlayers") == "42",
                  f"после открытия виден добавленный ключ в {original!r}")


def test_remove() -> None:
    cfg = cfg_from(SAMPLE)
    gone = cfg.remove(["maxPlayers", "disableBanlist"])
    check(gone == 2, "убрано столько строк, сколько просили")
    check("maxPlayers" not in cfg.text, "ключ убран целиком")
    check("ownCustomKey = 42;" in cfg.text, "чужие ключи не тронуты")
    check("class Missions" in cfg.text, "блоки не тронуты")


def test_apply() -> None:
    cfg = cfg_from(SAMPLE)
    cfg.apply({
        "hostname": "KR",            # поменять
        "maxPlayers": None,          # убрать
        "instanceId": "3",           # дописать
        "verifySignatures": "0",     # оставить как есть
    })
    got = cfg.values()
    check(got.get("hostname") == "KR", "apply меняет")
    check("maxPlayers" not in got, "apply убирает")
    check(got.get("instanceId") == "3", "apply дописывает")
    check(got.get("verifySignatures") == "0", "apply не портит неизменившееся")
    check(got.get("ownCustomKey") == "42", "apply не трогает чужое")
    check(got.get("template") == "dayzOffline.chernarusplus",
          "apply не трогает содержимое блоков")

    # повторный вызов с тем же состоянием ничего не меняет
    before = cfg.text
    cfg.apply({"hostname": "KR", "instanceId": "3"})
    check(cfg.text == before, "повторное применение не переписывает файл")


def main() -> int:
    for fn in (test_specs, test_read, test_change, test_add, test_add_line_endings,
               test_remove, test_apply):
        fn()
    if _fails:
        print(f"НЕ ПРОШЛО ({len(_fails)}):")
        for f in _fails:
            print("  -", f)
        return 1
    print(f"конфиг: всё сошлось, известных ключей {len(servercfg.SPECS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
