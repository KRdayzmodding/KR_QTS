"""Переезд файлов приложения при смене настроенных путей.

Пути (конфиги, профили, миссии, ссылки на моды) задаются относительно корня
клиента или сервера и меняются человеком в настройках. Само по себе изменение
настройки оставило бы все пресеты смотреть в пустоту: файлы остались бы на
старом месте, а приложение искало бы их на новом.

Поэтому переезд, а не просто запись значения. Правила, выведенные из обсуждения
и из проверок:

* переносим **по списку** — конфиг, профиль и миссия каждого пресета поимённо,
  а не папку целиком. Тогда новый путь может лежать внутри старого
  (KR_Debug -> KR_Debug\\test\\Servers) и никакой рекурсии не возникает;
* ссылки на моды **не переносим, а пересоздаём**: перенос ссылки может утащить
  содержимое цели. Цель при этом никуда не едет — она в папке загрузок;
* удаляем **только перенесённое, поимённо**. Не «старую папку целиком»: ею мог
  быть корень игры, и снос уничтожил бы установку;
* настройка записывается **после** успешного переезда. Сорвалось — старые файлы
  на месте, приложение работает по-прежнему;
* копируем, потом удаляем отдельным шагом и с подтверждением. Диск тот же, но
  копия временно занимает место дважды — зато обрыв ничего не теряет.
"""
from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .layout import CONFIG, MISSIONS, MODS, PATH_FIELDS, PROFILE
from .presets import ServerPreset
from .settings import Settings, EXPERIMENTAL, STABLE

# Символы, недопустимые в именах Windows. Разделители путей сюда не входят:
# путь из нескольких частей — законный ввод.
_BAD_CHARS = '<>:"|?*'

_REPARSE = 0x400        # FILE_ATTRIBUTE_REPARSE_POINT — признак junction


def validate(value: str) -> str:
    """Пустая строка — путь годится; иначе текст проблемы.

    Пустой ввод допустим и означает сам корень игры.
    """
    from .i18n import tr
    v = (value or "").strip()
    if not v:
        return ""
    if Path(v).is_absolute() or ":" in v:
        return tr("paths.err_absolute",
                  "Путь должен быть относительным — без буквы диска.")
    if any(c in v for c in _BAD_CHARS):
        return tr("paths.err_chars", "Недопустимые символы: {c}", c=_BAD_CHARS)
    if any(part == ".." for part in Path(v).parts):
        return tr("paths.err_updir",
                  "Выход за пределы корня («..») не поддерживается: путь запуска "
                  "обязан оставаться относительным.")
    return ""


def dir_for(root: str, rel: str) -> Path:
    """Папка вида файлов внутри корня. Пустой rel — сам корень."""
    rel = (rel or "").strip()
    return Path(root) / rel if rel else Path(root)


def roots(settings: Settings) -> list[tuple[str, str]]:
    """Все корни, где приложение может держать файлы: (название, путь).

    Ненастроенные и несуществующие отсеиваем — переезжать там нечему.
    """
    out = []
    for label, path in (
        ("DayZ", settings.client_root(STABLE)),
        ("DayZ Server", settings.server_root(STABLE)),
        ("DayZ Exp", settings.client_root(EXPERIMENTAL)),
        ("DayZ Server Exp", settings.server_root(EXPERIMENTAL)),
    ):
        if path and Path(path).is_dir():
            out.append((label, path))
    return out


@dataclass
class Item:
    """Одна единица переезда."""
    root_label: str
    kind: str
    src: Path
    dst: Path

    @property
    def name(self) -> str:
        return self.src.name


@dataclass
class Plan:
    items: list[Item] = field(default_factory=list)
    links: list[tuple[str, Path, Path, Path]] = field(default_factory=list)
    # (название корня, старая ссылка, новая ссылка, цель)
    skipped: list[str] = field(default_factory=list)
    # (опустевшая папка, корень) — что подчистить после удаления файлов
    old_dirs: list[tuple[Path, Path]] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.items and not self.links

    def by_root(self) -> dict[str, tuple[int, int]]:
        """Сколько файлов и ссылок приходится на каждый корень.

        Общее число ничего не говорит: у человека может быть четыре установки,
        и важно видеть, где переезд состоялся, а где переносить было нечего.
        """
        out: dict[str, tuple[int, int]] = {}
        for it in self.items:
            files, links = out.get(it.root_label, (0, 0))
            out[it.root_label] = (files + 1, links)
        for label, *_rest in self.links:
            files, links = out.get(label, (0, 0))
            out[label] = (files, links + 1)
        return out


def _is_junction(p: Path) -> bool:
    try:
        return bool(os.lstat(p).st_file_attributes & _REPARSE)
    except (OSError, AttributeError):
        return False


def _link_target(p: Path) -> Path | None:
    """Цель junction. Windows отдаёт её с префиксом \\\\?\\ — снимаем."""
    try:
        t = os.readlink(p)
    except OSError:
        return None
    return Path(t[4:] if t.startswith("\\\\?\\") else t)


def build(settings: Settings, new_paths: dict[str, str]) -> Plan:
    """Что и куда переедет при переходе на new_paths.

    Пресеты хранят голые имена; переносим ровно те файлы, что реально лежат на
    старом месте. Совпадающие пути пропускаем — переезжать некуда.
    """
    plan = Plan()
    presets = ServerPreset.load_all()
    old = {k: (getattr(settings, f, "") or "").strip() for k, f in PATH_FIELDS.items()}
    new = {k: (new_paths.get(k, "") or "").strip() for k in PATH_FIELDS}

    def bare(v: str) -> bool:
        return bool(v) and len(Path(v).parts) == 1

    for label, root in roots(settings):
        for kind, values in (
            (CONFIG, [p.server_config for p in presets]),
            (PROFILE, [p.profiles for p in presets]),
            (MISSIONS, [p.mission for p in presets]),
        ):
            if old[kind] == new[kind]:
                continue
            src_dir, dst_dir = dir_for(root, old[kind]), dir_for(root, new[kind])
            for value in values:
                if not bare(value) or value.startswith("actual."):
                    continue        # легаси-путь или шаблон карты — не наше
                src, dst = src_dir / value, dst_dir / value
                if not src.exists():
                    continue
                if dst.exists():
                    plan.skipped.append(f"{label}: {value} — на новом месте уже есть")
                    continue
                # единственный опасный случай: цель внутри источника
                try:
                    dst.relative_to(src)
                    plan.skipped.append(f"{label}: {value} — новый путь внутри старого")
                    continue
                except ValueError:
                    pass
                plan.items.append(Item(label, kind, src, dst))

        # ссылки на моды: пересоздаём, а не переносим
        if old[MODS] != new[MODS]:
            src_dir, dst_dir = dir_for(root, old[MODS]), dir_for(root, new[MODS])
            if src_dir.is_dir():
                for entry in sorted(src_dir.iterdir()):
                    if not _is_junction(entry):
                        continue
                    target = _link_target(entry)
                    if target is None:
                        plan.skipped.append(f"{label}: {entry.name} — цель ссылки не прочиталась")
                        continue
                    plan.links.append((label, entry, dst_dir / entry.name, target))

        # Опустевшие папки после переезда тоже надо убрать — иначе останется
        # скелет старой раскладки. Запоминаем их вместе с корнем: подниматься
        # вверх можно только до него, сам корень не трогаем никогда.
        for kind in PATH_FIELDS:
            if old[kind] == new[kind] or not old[kind]:
                continue        # путь не менялся либо это сам корень
            plan.old_dirs.append((dir_for(root, old[kind]), Path(root)))
    return plan


def _prune_empty(start: Path, root: Path) -> list[Path]:
    """Убирает опустевшие папки вверх до корня. Корень остаётся всегда.

    Останавливаемся на первой непустой: там лежит чужое, и трогать его нельзя.
    """
    removed: list[Path] = []
    try:
        cur, root = start.resolve(), root.resolve()
    except OSError:
        return removed
    while cur != root and root in cur.parents:
        try:
            if any(cur.iterdir()):
                break           # не пусто — дальше вверх идти незачем
            cur.rmdir()
            removed.append(cur)
            cur = cur.parent
        except OSError:
            break
    return removed


def apply(plan: Plan, on_step=None, cancelled=None) -> list[str]:
    """Выполняет переезд копированием. Возвращает список ошибок.

    on_step(сделано, всего, что делаем) — для показа хода.
    cancelled() -> bool — прервать между пунктами.
    """
    from . import junction
    from .i18n import tr
    errors: list[str] = []
    total = len(plan.items) + len(plan.links)
    done = 0

    for item in plan.items:
        if cancelled and cancelled():
            return errors
        if on_step:
            on_step(done, total, item.name)
        try:
            item.dst.parent.mkdir(parents=True, exist_ok=True)
            if item.src.is_dir():
                shutil.copytree(item.src, item.dst)
            else:
                shutil.copy2(item.src, item.dst)
        except OSError as e:
            errors.append(f"{item.root_label}: {item.name} — {e}")
        done += 1

    for label, old_link, new_link, target in plan.links:
        if cancelled and cancelled():
            return errors
        if on_step:
            on_step(done, total, new_link.name)
        try:
            new_link.parent.mkdir(parents=True, exist_ok=True)
            if not new_link.exists():
                err = junction.create(new_link, target)
                if err:
                    errors.append(f"{label}: {new_link.name} — {err}")
        except OSError as e:
            errors.append(f"{label}: {new_link.name} — {e}")
        done += 1

    if on_step:
        on_step(total, total, tr("paths.step_done", "готово"))
    return errors


def cleanup(plan: Plan) -> tuple[int, list[str]]:
    """Удаляет перенесённое со старого места. (сколько убрано, ошибки).

    Только то, что действительно скопировалось, и только поимённо: папку
    целиком не трогаем никогда — ею мог быть корень игры.
    """
    removed, errors = 0, []
    for item in plan.items:
        if not item.dst.exists():
            continue        # не скопировалось — старое трогать нельзя
        try:
            if item.src.is_dir():
                shutil.rmtree(item.src, onerror=_force_remove)
            elif item.src.is_file():
                item.src.unlink()
            removed += 1
        except OSError as e:
            errors.append(f"{item.root_label}: {item.name} — {e}")
    for label, old_link, new_link, _target in plan.links:
        if not new_link.exists():
            continue
        try:
            if _is_junction(old_link):
                old_link.rmdir()    # цель не затрагивается, проверено
                removed += 1
        except OSError as e:
            errors.append(f"{label}: {old_link.name} — {e}")

    # Папки убираем последними: пока в них лежали файлы, пустыми они не были.
    # Порядок от длинных путей к коротким, чтобы вложенные уходили раньше
    # родительских.
    for old_dir, root in sorted(plan.old_dirs, key=lambda p: len(str(p[0])), reverse=True):
        removed += len(_prune_empty(old_dir, root))
    return removed, errors


def _force_remove(func, path, _exc):
    """Снимает «только для чтения» и повторяет — иначе rmtree спотыкается."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass
