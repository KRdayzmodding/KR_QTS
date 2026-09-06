"""Накладка на пресет: как аргументы командной строки превращаются в запуск.

Пресет — база, накладка уточняет один прогон. Поэтому здесь всё работает с
копией пресета: правка ради одного запуска, оставшаяся в файле навсегда, — та
самая мистика, которую потом ищут полчаса.

След накладка оставляет ровно в одном месте — привязки модов и сорсов
(см. plan/commit). Они по своей природе постоянные: указав их однажды, человек
превращает «мода нет нигде» в «мод в списке», и следующая команда снова
короткая.

Решение и его исполнение разделены намеренно: plan() ничего не трогает и потому
проверяется тестами, commit() пишет на диск.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

from .cliargs import Overlay, SIDE_SERVER
from .mods import ModInfo, SOURCE_LOCAL, as_folder
from .presets import ServerPreset

# Виды заметок в отчёте. Всё, что накладка сделала неочевидного, обязано быть
# названо: иначе «+mod=X из скрипта» и «+mod=X мышкой» дадут разный запуск, а
# человек об этом не узнает.
N_REGISTERED = "mod_registered"      # завели мод, которого не было
N_BOUND = "source_bound"             # привязали папку сорсов
N_UNBOUND = "source_unbound"
N_FORGOTTEN = "mod_forgotten"
N_DEPENDENCY = "dependency_added"    # подтянули зависимость
N_NO_KEY = "mod_without_key"         # нет .bikey — сервер с проверкой подписей не пустит
N_SHARED_SOURCE = "source_shared"    # одна папка сорсов у двух модов


@dataclass
class Note:
    kind: str
    mod: str = ""
    text: str = ""

    def as_dict(self) -> dict:
        out = {"kind": self.kind}
        if self.mod:
            out["mod"] = self.mod
        if self.text:
            out["text"] = self.text
        return out


@dataclass
class Registration:
    """Мод, которого в реестре нет: заводим по указанной папке."""

    key: str
    name: str
    path: str


@dataclass
class Plan:
    """Что накладка сделает с реестром и какие имена уйдут в запуск."""

    register: list[Registration] = field(default_factory=list)
    bind: list[tuple[str, str]] = field(default_factory=list)     # (ключ, папка)
    unbind: list[tuple[str, str]] = field(default_factory=list)
    forget: list[str] = field(default_factory=list)               # ключи
    add_mods: list[str] = field(default_factory=list)             # имена, обе стороны
    add_server_mods: list[str] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)


def _key(ref: str) -> str:
    """Ключ реестра по ссылке из командной строки.

    Ссылка бывает именем («KR_Test», «@KR_Test») и путём («F:\\Builds\\@KR_New»).
    В обоих случаях опознаём мод по имени папки: именно им он подключается к
    игре, и именно оно лежит ключом в реестре.
    """
    name = Path(ref).name if ("\\" in ref or "/" in ref) else ref
    return as_folder(name).lower()


def _is_path(ref: str) -> bool:
    return "\\" in ref or "/" in ref


def _display(ref: str) -> str:
    r"""Имя мода так, как его писали: «F:\Builds\@KR_New» -> «KR_New»."""
    name = Path(ref).name if _is_path(ref) else ref
    return name.lstrip("@")


def plan(ov: Overlay, registry) -> Plan:
    """Что делать с модами накладки. Ничего не меняет — только решает.

    Реестр нужен только на чтение: get() и mods. Поэтому в тестах на его месте
    стоит пара словарей, а не настоящее сканирование диска.
    """
    out = Plan()
    seen_sources: dict[str, str] = {}

    for ref in ov.forget:
        key = _key(ref)
        out.forget.append(key)
        out.notes.append(Note(N_FORGOTTEN, mod=key))

    for m in ov.mods:
        key = _key(m.ref)
        mod = registry.get(key)
        if mod is None and _is_path(m.ref):
            # Третий случай: мода нет нигде. Заводим по указанной папке — один
            # раз, дальше он обычный мод из реестра.
            name = Path(m.ref).name.lstrip("@")
            out.register.append(Registration(key=key, name=name, path=str(Path(m.ref))))
            out.notes.append(Note(N_REGISTERED, mod=key, text=str(Path(m.ref))))
        elif mod is not None and not mod.has_keys:
            # Самая вероятная засада: свежесобранный мод без .bikey, а сервер
            # проверяет подписи — клиент не войдёт, и причина ниоткуда не видна.
            out.notes.append(Note(N_NO_KEY, mod=key))

        for src in m.add_sources:
            src = str(Path(src))
            owner = seen_sources.get(src.lower())
            if owner and owner != key:
                out.notes.append(Note(N_SHARED_SOURCE, mod=key, text=src))
            seen_sources[src.lower()] = key
            if mod is None or src not in mod.sources:
                out.bind.append((key, src))
                out.notes.append(Note(N_BOUND, mod=key, text=src))
        for src in m.drop_sources:
            src = str(Path(src))
            out.unbind.append((key, src))
            out.notes.append(Note(N_UNBOUND, mod=key, text=src))

        target = out.add_server_mods if m.side == SIDE_SERVER else out.add_mods
        # Имя берём из реестра, а не из ключа: ключ приведён к нижнему регистру
        # для сравнения, а в командную строку игры уходит настоящее имя папки.
        name = mod.name if mod is not None else _display(m.ref)
        if name not in target:
            target.append(name)
    return out


def commit(p: Plan, registry, settings) -> None:
    """Исполняет план: заводит моды и запоминает привязки.

    «Забыть» — это только про наши записи: ни папку мода, ни сорсы не трогаем
    никогда. Удаление чужих файлов из скрипта однажды сотрёт чью-то работу.
    """
    changed = False
    for reg in p.register:
        path = Path(reg.path)
        registry.mods[reg.key] = ModInfo(
            name=reg.name, path=str(path), source=SOURCE_LOCAL,
            group=path.parent.name,
            has_keys=(path / "keys").is_dir() or (path / "Keys").is_dir(),
        )
        # Чтобы мод пережил следующее сканирование, его папка должна быть в
        # списке своих: иначе реестр забудет его при первом же обновлении.
        folder = str(path)
        if folder not in settings.local_mods_dirs:
            settings.local_mods_dirs.append(folder)
            changed = True

    for key, src in p.bind:
        mod = registry.mods.get(key)
        if mod is not None and src not in mod.sources:
            mod.sources.append(src)
    for key, src in p.unbind:
        mod = registry.mods.get(key)
        if mod is not None and src in mod.sources:
            mod.sources.remove(src)

    for key in p.forget:
        mod = registry.mods.pop(key, None)
        if mod is not None and mod.path in settings.local_mods_dirs:
            settings.local_mods_dirs.remove(mod.path)
            changed = True

    if p.bind or p.unbind or p.forget or p.register:
        registry.save_sources()
    if changed:
        settings.save()


def apply(preset: ServerPreset, ov: Overlay, p: Plan) -> ServerPreset:
    """Копия пресета с наложенными аргументами. Сам пресет не меняется."""
    mods = list(preset.mods) if ov.mods_replace is None else list(ov.mods_replace)
    server_mods = (list(preset.server_mods) if ov.server_mods_replace is None
                   else list(ov.server_mods_replace))
    # Добавленные встают в конец: порядок в списке есть порядок загрузки, и
    # вставлять чужое в середину — менять поведение молча.
    for name in p.add_mods:
        if name not in mods:
            mods.append(name)
    for name in p.add_server_mods:
        if name not in server_mods:
            server_mods.append(name)

    params_client = _merge(preset.params_client, ov.params_client)
    params_server = _merge(preset.params_server, ov.params_server)

    return dataclasses.replace(
        preset,
        launch_server=preset.launch_server if ov.server is None else ov.server,
        launch_client=preset.launch_client if ov.client is None else ov.client,
        params_client=params_client,
        params_server=params_server,
        extra_client=ov.extra_client or preset.extra_client,
        extra_server=ov.extra_server or preset.extra_server,
        mods=mods,
        server_mods=server_mods,
    )


def _merge(base: dict, over: dict) -> dict:
    """Параметры пресета плюс накладка. None снимает параметр целиком.

    Снять — не то же самое, что выключить: «-cScrDef=» означает «не передавать
    вовсе», а «-cFilePatching» означает «передать со значением 0». Для SWITCH
    это разные командные строки и разное поведение игры.
    """
    out = dict(base)
    for name, value in over.items():
        if value is None:
            out.pop(name, None)
        else:
            out[name] = value
    return out
