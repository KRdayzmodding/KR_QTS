"""Сверяет lang/ru.json с исходниками: собирает все tr("ключ", "текст").

    python tools/extract_strings.py            показать расхождения
    python tools/extract_strings.py --write    дописать недостающее

Русские строки — эталон: значения по умолчанию заданы прямо в коде, en.json и
de.json переводятся от них.

Инструмент **дописывает, но не удаляет**. Раньше он переписывал файл целиком, и
это стоило 67 ключей за один запуск: часть ключей собирается не из литералов, а
из справочников (параметры запуска, ключи конфига, аргументы командной строки),
и всё, до чего разбор не дотянулся, молча исчезало вместе с переводами.
Поэтому теперь лишнее только называется, а решение принимает человек.
"""
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

strings: dict[str, str] = {}

FILES = (list((ROOT / "core").glob("*.py")) + list((ROOT / "ui").glob("*.py"))
         + [ROOT / "main.py", ROOT / "qtsctl.py"])

for py in FILES:
    if not py.is_file():
        continue
    tree = ast.parse(py.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "tr" and len(node.args) >= 2
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[1], ast.Constant)):
            strings[node.args[0].value] = node.args[1].value

# Ключи, которые собираются из справочников, а не написаны литералами. Разбор
# кода до них не дотягивается — берём прямо у источника.
from core.params import _TOOLTIPS_RU              # noqa: E402
for name, text in _TOOLTIPS_RU.items():
    strings[f"param.{name}"] = text

from core.servercfg import SPECS                  # noqa: E402
for spec in SPECS:
    strings[f"cfgvar.{spec.name}"] = spec.hint

from core.cliargs import all_specs                # noqa: E402
for spec in all_specs():
    if spec.param is None:
        strings[f"cli.arg.{spec.name}"] = spec.help
    if spec.hint:
        strings[f"cli.v.{spec.name}"] = spec.hint

from core.clihelp import COMMANDS_HELP            # noqa: E402
for _name, key, default in COMMANDS_HELP:
    strings[key] = default

path = ROOT / "lang" / "ru.json"
current = json.loads(path.read_text(encoding="utf-8"))

missing = {k: v for k, v in strings.items() if k not in current}
stale = [k for k in current if k not in strings]

print(f"в коде найдено: {len(strings)}, в словаре: {len(current)}")
if missing:
    print(f"\nнет в словаре ({len(missing)}):")
    for k, v in sorted(missing.items()):
        print(f"  {k} = {v[:70]}")
if stale:
    # Не удаляем: ключ мог собираться там, куда разбор не дотянулся. Список —
    # повод проверить руками, а не команда на удаление.
    print(f"\nне нашлись в коде ({len(stale)}) — проверить руками:")
    for k in sorted(stale):
        print(f"  {k}")

if "--write" in sys.argv and missing:
    current.update(missing)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"\nдописано в ru.json: {len(missing)}; переведите их в en.json и de.json")
elif missing:
    print("\nзапустите с --write, чтобы дописать")
