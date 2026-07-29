# KR Quick Test Server

**RU** | [EN below](#en)

**KR Quick Test Server** (KR QTS) — локальный тестовый сервер DayZ и сборка модов в одном окне, без батников.

## Возможности

**Запуск**
- Пресеты сервера и клиента: ветка Stable или Experimental, обычный dedicated или Diag-сборка
- Параметры запуска с подсказками по каждому, filePatching и прочее — без правки командных строк
- Предстартовая проверка: скажет, чего не хватает, до того как что-то не запустится
- Мини-окно и значок в трее, чтобы не держать большое окно на виду

**Моды**
- Моды из Steam Workshop и локальных папок, junction-ссылки создаются сами
- Метки с группировкой, зависимости, папки исходников
- Перепаковка изменённых модов через Mikero pboProject перед запуском — по сравнению дат, лишнего не пересобирает
- Логи запаковки отдельно по сборке PBO и по бинаризации

**Логи**
- Живые логи сервера и клиента с подсветкой и поиском по содержимому
- Скриптовая память по слоям (GameLib, Game, World, Mission) с цветовой шкалой и предупреждением у предела
- Счётчик ошибок из crash-лога, отдельно по клиенту и серверу, только за текущий запуск

**Сервер**
- Редактор `serverDZ.cfg` с подсказками, кодировка чинится сама (UTF-8 без BOM)
- Права админа для COT, VPPAdminTools и LBmaster по списку SteamID
- Каталог миссий с загрузкой прямо из приложения

**Прочее**
- Языки: русский, английский, немецкий
- Недостающие компоненты (DayZ Server, DayZ Tools) ставятся через Steam из самого приложения, путь подставляется сам

## Установка

Скачайте архив со [страницы релизов](https://github.com/KRdayzmodding/KR_QTS/releases/latest), распакуйте и запустите `KR_QTS.exe`. Установщик не нужен, Python не нужен.

Настройки лежат в `%APPDATA%\KR_QTS`. Если положить рядом с `KR_QTS.exe` папку `config`, программа перейдёт в портативный режим и будет держать всё там — так её можно носить на флешке или держать несколько независимых копий.

При первом запуске мастер сам найдёт пути к DayZ, серверу и Mikero Tools по реестру Steam.

## Требования

Windows 10 или 11. Для сборки модов — Mikero Tools (pboProject и сопутствующие) и DayZ Tools, для запуска — DayZ и DayZ Server; их приложение поможет установить.

## Обновления

Приложение проверяет версию при запуске и уведомляет, если вышла новая: в левой части основного окна появляется кнопка. Описание изменений видно в окне, контрольная сумма сверяется, установка и перезапуск проходят сами.

## Известные ограничения

- Установка в `Program Files` требует запуска от администратора, иначе обновление не сможет заменить файлы. Проще распаковать в обычную папку.
- Запущенный сервер не подхватывается новым экземпляром программы после её перезапуска.

## Запуск из исходников

Нужен, если хотите править код:

```
git clone https://github.com/KRdayzmodding/KR_QTS.git
cd KR_QTS
pip install -r requirements.txt
python main.py
```

Требуется Python 3.11+. Собрать свою версию — `python tools/build.py`, результат появится в `dist/`.

## Лицензия

GPLv3. Пользуйтесь бесплатно в любых целях, в том числе на серверах с монетизацией, форкайте и дорабатывайте. Любой форк обязан оставаться открытым и бесплатным для распространения.

---

<a name="en"></a>

## EN

**KR Quick Test Server** (KR QTS) — a local DayZ test server and mod packing in one window, no batch files.

## Features

**Launching**
- Server and client presets: Stable or Experimental branch, plain dedicated or a Diag build
- Launch parameters with a tooltip for each — filePatching and the rest, no command lines to edit
- Pre-launch checks: tells you what is missing before something fails to start
- Mini window and a tray icon, so the main window need not stay in the way

**Mods**
- Steam Workshop and local mods, junction links created automatically
- Labels with grouping, dependencies, source folders
- Repacking changed mods via Mikero pboProject before launch — by timestamps, nothing extra gets rebuilt
- Packing logs kept separately for PBO assembly and binarization

**Logs**
- Live server and client logs with highlighting and search by content
- Script memory per layer (GameLib, Game, World, Mission) on a colour scale, with a warning near the limit
- Error counter taken from the crash log, separately for client and server, current session only

**Server**
- `serverDZ.cfg` editor with tooltips; encoding is fixed automatically (UTF-8 without BOM)
- Admin rights for COT, VPPAdminTools and LBmaster from a list of SteamIDs
- Mission catalogue with downloads straight from the app

**Other**
- Languages: Russian, English, German
- Missing components (DayZ Server, DayZ Tools) install via Steam from within the app, the path fills itself in

## Install

Grab the archive from the [releases page](https://github.com/KRdayzmodding/KR_QTS/releases/latest), unpack it and run `KR_QTS.exe`. No installer, no Python needed.

Settings live in `%APPDATA%\KR_QTS`. Put a `config` folder next to `KR_QTS.exe` and the app switches to portable mode, keeping everything there — handy for a USB stick or several independent copies.

On first run a setup wizard auto-detects your DayZ, server and Mikero Tools paths from the Steam registry.

## Requirements

Windows 10 or 11. Mod packing needs Mikero Tools (pboProject and friends) and DayZ Tools; running needs DayZ and DayZ Server. The app can install them for you.

## Updates

The app checks its version at startup and tells you when a new one is out: a button appears in the left-hand navigation. Release notes are shown in-app, the checksum is verified, installing and restarting happen on their own.

## Known limitations

- Installing into `Program Files` requires running as administrator, otherwise the updater cannot replace the files. Unpacking into an ordinary folder is easier.
- A running server is not picked up by a new instance of the app after it restarts.

## Running from source

For those who want to hack on it:

```
git clone https://github.com/KRdayzmodding/KR_QTS.git
cd KR_QTS
pip install -r requirements.txt
python main.py
```

Requires Python 3.11+. To build your own package run `python tools/build.py`; the result lands in `dist/`.

## License

GPLv3. Free to use for any purpose, including monetized servers; fork and modify as you like. Any fork must stay open source and freely redistributable.
