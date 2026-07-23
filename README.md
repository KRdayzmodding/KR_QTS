# KR Server Manager

**RU** | [EN below](#en)

**KR Server Manager** — инструмент для DayZ-мододелов и владельцев серверов, который собирает весь цикл локальной разработки в одно окно:

- пресеты запуска сервера (dedicated или Diag) и клиента, ветки Stable/Experimental;
- подключение модов из Steam Workshop и локальных папок с автоматическими junction-ссылками;
- перепаковка изменённых модов через Mikero pboProject с проверкой актуальности по таймштампам;
- редактор `serverDZ.cfg` (с автоисправлением кодировки в UTF-8 без BOM);
- предстартовая проверка конфигурации;
- два окна живых логов (сервер и клиент) с подсветкой ошибок и поиском.

Никаких батников: настроил пресет один раз — дальше одна кнопка «Запустить».

### Установка

```
git clone https://github.com/KRdayzmodding/KR_ServerManager.git
cd KR_ServerManager
pip install -r requirements.txt
python main.py
```

Требуется Python 3.11+ и Windows. При первом запуске мастер настройки сам найдёт пути к DayZ, серверу и Mikero Tools.

### Лицензия

GPLv3 — простыми словами: пользуйтесь бесплатно в любых целях (в том числе на серверах с монетизацией), форкайте и дорабатывайте на здоровье, но любой форк обязан оставаться открытым и бесплатным для распространения. Продавать эти тулзы или их модификации не выйдет: исходники форка обязаны быть открыты, и любой вправе раздавать их бесплатно.

---

<a name="en"></a>

## EN

**KR Server Manager** — an all-in-one tool for DayZ modders and server owners that puts the whole local development cycle in one window:

- launch presets for server (dedicated or Diag) and client, Stable/Experimental branches;
- mod management for Steam Workshop and local mods with automatic junction links;
- repacking changed mods via Mikero pboProject with timestamp-based staleness detection;
- `serverDZ.cfg` editor (auto-fixes encoding to UTF-8 without BOM);
- pre-launch configuration checks;
- two live log windows (server and client) with error highlighting and search.

No more .bat files: set up a preset once — then it's a single "Launch" button.

### Install

```
git clone https://github.com/KRdayzmodding/KR_ServerManager.git
cd KR_ServerManager
pip install -r requirements.txt
python main.py
```

Requires Python 3.11+ and Windows. On first run a setup wizard auto-detects your DayZ, server and Mikero Tools paths.

### License

GPLv3 — in plain words: free to use for any purpose (including monetized servers), fork and modify as you like, but any fork must stay open source and freely redistributable. Selling these tools or their modifications is pointless by design: fork sources must be open, and anyone may share them for free.
