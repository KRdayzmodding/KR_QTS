"""BattlEye RCon: разговор с работающим сервером DayZ.

Своего RCON у DayZ нет — есть BattlEye RCon, который поднимает сам BE внутри
серверного процесса. Отсюда два следствия, определяющие всё остальное:

* работает он только там, где BattlEye включён, то есть на обычном сервере;
  в diag-режиме мы передаём -battleye=0, и подключаться не к чему;
* настраивается он не через serverDZ.cfg, а файлом BEServer_x64.cfg в папке
  BattlEye — её положение считает be_dir(), см. комментарий у него.

Протокол простой и недокументированный официально: UDP, в заголовке CRC32,
ответы на длинные команды приходят несколькими пакетами. Разбор — ниже,
по шагам.
"""
from __future__ import annotations

import secrets
import socket
import zlib
from pathlib import Path

# Заголовок каждого пакета: 'B','E', затем CRC32 полезной части.
_MAGIC = b"BE"
_PREFIX = 0xFF          # с него начинается полезная часть

LOGIN, COMMAND, MESSAGE = 0x00, 0x01, 0x02

CFG_NAME = "BEServer_x64.cfg"
DEFAULT_PORT = 2305     # порт по умолчанию для RCon; свой, не игровой


class RconError(Exception):
    """Не удалось поговорить с сервером: нет ответа, отказ входа, обрыв."""


def _packet(kind: int, payload: bytes) -> bytes:
    body = bytes([_PREFIX, kind]) + payload
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return _MAGIC + crc.to_bytes(4, "little") + body


def _parse(data: bytes) -> tuple[int, bytes]:
    """(тип, полезная часть). RconError — если пакет не наш или битый."""
    if len(data) < 9 or not data.startswith(_MAGIC):
        raise RconError("чужой пакет")
    body = data[6:]
    if body[0] != _PREFIX:
        raise RconError("испорченный пакет")
    want = int.from_bytes(data[2:6], "little")
    if (zlib.crc32(body) & 0xFFFFFFFF) != want:
        raise RconError("не сошлась контрольная сумма")
    return body[1], body[2:]


# --------------------------------------------------------------- конфигурация

def be_dir(profiles: str, be_path: str = "") -> Path:
    """Папка, из которой BattlEye читает свой конфиг.

    Проверено по четырём запускам: без -BEpath это ровно <профиль>\\BattlEye,
    а значение параметра дописывается к ней (не к корню сервера, как можно
    было бы подумать). Оттого при -BEpath=battleye появляется вложенная
    BattlEye\\battleye — папка живая, именно в ней BE и держит свои файлы.
    """
    base = Path(profiles) / "BattlEye"
    rel = (be_path or "").strip().strip("\\/")
    return base / rel if rel else base


def new_password(length: int = 12) -> str:
    """Пароль RCon. Хранится открытым текстом — так его читает BattlEye.

    Поэтому он должен быть случайным и одноразовым: это пароль к локальному
    тестовому серверу, а не к чему-то, что стоит беречь. Символы — только
    буквы и цифры: BE разбирает конфиг построчно, и пробел или кавычка в
    пароле ломают разбор молча.
    """
    abc = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(abc) for _ in range(length))


def read_config(directory: Path) -> dict[str, str]:
    """Что сейчас написано в BEServer_x64.cfg (пусто, если файла нет)."""
    path = Path(directory) / CFG_NAME
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        key, _, value = line.partition(" ")
        out[key.strip()] = value.strip()
    return out


def ensure_config(directory: Path, password: str, port: int = DEFAULT_PORT) -> tuple[bool, str]:
    """Прописывает RCon в BEServer_x64.cfg. (успех, ошибка).

    Чужие строки сохраняем: в этот же файл пишут настройки античита, и
    переписать файл целиком значило бы молча снести чужие правила.
    """
    directory = Path(directory)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, str(e)
    path = directory / CFG_NAME
    keep: list[str] = []
    if path.is_file():
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                key = line.strip().partition(" ")[0]
                if key not in ("RConPassword", "RConPort", "RestrictRCon"):
                    keep.append(line.rstrip())
        except OSError as e:
            return False, str(e)
    lines = [f"RConPassword {password}", f"RConPort {port}",
             # 0 — доступны все команды; сервер локальный и слушает только
             # петлю, ограничивать самих себя незачем
             "RestrictRCon 0", *keep]
    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as e:
        return False, str(e)
    return True, ""


# ------------------------------------------------------------------- разговор

class Rcon:
    """Одно соединение с BE RCon. Живёт недолго: подключились, сказали, ушли.

    Постоянное соединение потребовало бы keepalive раз в 30–45 секунд и
    переподключений; для команд вроде «выключись» и «скажи игрокам» дешевле
    каждый раз подключаться заново — сервер это позволяет.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 password: str = "", timeout: float = 3.0):
        self.host, self.port, self.password = host, port, password
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._seq = 0

    # ------------------------------------------------------------ соединение

    def __enter__(self) -> Rcon:
        self.connect()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def connect(self) -> None:
        """Открывает сокет и входит по паролю. RconError — если не пустили."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect((self.host, self.port))
            sock.send(_packet(LOGIN, self.password.encode("ascii", "ignore")))
            kind, payload = _parse(self._recv(sock))
        except (OSError, RconError) as e:
            sock.close()
            raise RconError(str(e)) from e
        if kind != LOGIN or not payload or payload[0] != 1:
            sock.close()
            raise RconError("сервер не принял пароль")
        self._sock = sock

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def _recv(self, sock: socket.socket) -> bytes:
        try:
            return sock.recv(4096)
        except socket.timeout as e:
            raise RconError("сервер не ответил") from e

    # --------------------------------------------------------------- команды

    def command(self, text: str) -> str:
        """Выполняет команду и возвращает ответ сервера (может быть пустым).

        Длинные ответы (список игроков) приходят пачкой пакетов: в каждом
        сказано, сколько их всего и какой это по счёту. Собираем по порядку,
        а не по времени прихода — UDP не обещает порядка.
        """
        if self._sock is None:
            raise RconError("нет соединения")
        seq = self._seq & 0xFF
        self._seq += 1
        try:
            self._sock.send(_packet(COMMAND, bytes([seq]) + text.encode("utf-8", "replace")))
        except OSError as e:
            raise RconError(str(e)) from e

        parts: dict[int, bytes] = {}
        total = 1
        while True:
            kind, payload = _parse(self._recv(self._sock))
            if kind == MESSAGE:
                # Сервер попутно рассказывает о своих событиях; на такие
                # пакеты положено отвечать, иначе он повторяет их и в конце
                # концов считает нас отвалившимися.
                if payload:
                    self._sock.send(_packet(MESSAGE, payload[:1]))
                continue
            if kind != COMMAND or not payload or payload[0] != seq:
                continue          # ответ на чужую команду — ждём свой
            rest = payload[1:]
            if len(rest) >= 3 and rest[0] == 0x00:
                total, index = rest[1], rest[2]
                parts[index] = rest[3:]
            else:
                parts[0] = rest
            if len(parts) >= total:
                break
        return b"".join(parts[i] for i in sorted(parts)).decode("utf-8", "replace")


def send(host: str, port: int, password: str, text: str, timeout: float = 3.0) -> str:
    """Подключиться, сказать одну команду, отключиться."""
    with Rcon(host, port, password, timeout) as r:
        return r.command(text)


def alive(host: str, port: int, password: str, timeout: float = 2.0) -> bool:
    """Отвечает ли RCon — вход прошёл, значит сервер жив и слушает."""
    try:
        with Rcon(host, port, password, timeout):
            return True
    except RconError:
        return False
