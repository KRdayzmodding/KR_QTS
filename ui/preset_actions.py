"""Служебные действия над выбранным пресетом: БД миссии и папка профиля.

Эти четыре кнопки стояли в редакторе пресета — то есть за карандашом, в окне,
которое открывают, чтобы что-то настроить. Но чистят БД не при настройке, а
между прогонами: это действие, а не настройка, и место ему на странице
запуска. Рядом с «Запустить» их ставить нельзя — две из четырёх необратимы,
поэтому все собраны в одно меню, как библиотечные команды у модов.

Работают по самому пресету, а не по полям формы: редактор пишет изменения
сразу, так что в пресете всегда лежит то же, что видно на экране.
"""
from __future__ import annotations

from pathlib import Path

from qfluentwidgets import (
    Action, FluentIcon as FIF, InfoBar, InfoBarPosition, MessageBox, RoundMenu,
)

from core.i18n import tr
from core.presets import ServerPreset
from core.settings import Settings


def show_menu(button, win, settings: Settings, preset: ServerPreset,
              branch: str) -> None:
    """Открывает меню под кнопкой."""
    menu = build_menu(button, win, settings, preset, branch)
    menu.exec(button.mapToGlobal(button.rect().bottomLeft()))


def build_menu(button, win, settings: Settings, preset: ServerPreset,
               branch: str) -> RoundMenu:
    """Собирает меню: необратимое — внизу, за разделителем.

    Сборка отделена от показа, чтобы её могла проверить автоматика: exec()
    останавливает поток до закрытия меню, и в прогоне это выглядит как
    зависший тест.
    """
    menu = RoundMenu(parent=button)
    menu.addAction(Action(FIF.FOLDER, tr("preset.open_prof", "Открыть папку профиля"),
                          triggered=lambda: open_profile(win, settings, preset, branch)))
    menu.addAction(Action(FIF.PEOPLE, tr("preset.admin_sync", "Права админок"),
                          triggered=lambda: sync_admin_tools(win, settings, preset, branch)))
    menu.addSeparator()
    menu.addAction(Action(FIF.DELETE, tr("preset.clear_db", "Очистить БД"),
                          triggered=lambda: clear_storage(win, settings, preset, branch)))
    menu.addAction(Action(FIF.BROOM, tr("preset.clear_prof", "Очистить профайл"),
                          triggered=lambda: clear_profile(win, settings, preset, branch)))
    return menu


def profile_dir(settings: Settings, preset: ServerPreset, branch: str) -> str:
    """Абсолютный путь папки профиля этого пресета."""
    from core.layout import preset_base_name, resolve_profiles
    profiles = preset.profiles or preset_base_name(preset.name, preset.mission)
    return resolve_profiles(profiles, settings, branch, preset.mode)


def _busy(win) -> bool:
    """Сервер запущен — чистить нельзя, и человек должен знать почему."""
    from core.launcher import dayz_running
    if not dayz_running():
        return False
    InfoBar.warning(title=tr("preset.busy_title", "Сервер запущен"),
                    content=tr("preset.busy_body",
                               "Остановите сервер — он держит файлы профиля открытыми "
                               "и перезапишет их при выходе."),
                    parent=win, duration=6000, position=InfoBarPosition.TOP_RIGHT)
    return True


def clear_storage(win, settings: Settings, preset: ServerPreset, branch: str) -> None:
    """Удаляет storage_* в миссии пресета — обнуление персистентности."""
    from core.layout import clear_mission_storage
    # Та же проверка, что у профиля: запущенный сервер держит БД открытой и
    # допишет её при выходе — вычищенная наполовину персистентность хуже
    # нетронутой. В редакторе этого вопроса не возникало, потому что его
    # открывали между прогонами; на странице запуска сервер часто жив.
    if _busy(win):
        return
    box = MessageBox(tr("preset.clear_db", "Очистить БД"),
                     tr("preset.clear_db_confirm",
                        "Удалить storage_* в миссии «{m}»?\nЛут, персонажи и постройки "
                        "будут сброшены.", m=preset.mission or "?"), win)
    if not box.exec():
        return
    n = clear_mission_storage(settings, branch, preset.mode, preset.mission)
    InfoBar.success(title=tr("preset.cleared_db", "Удалено storage-папок: {n}", n=n),
                    content="", parent=win, duration=3000,
                    position=InfoBarPosition.TOP_RIGHT)


def clear_profile(win, settings: Settings, preset: ServerPreset, branch: str) -> None:
    """Полностью чистит папку профиля сервера (логи, настройки модов)."""
    from core.layout import clear_profile as wipe
    from core.layout import preset_base_name
    if _busy(win):
        return
    profiles = preset.profiles or preset_base_name(preset.name, preset.mission)
    box = MessageBox(tr("preset.clear_prof", "Очистить профайл"),
                     tr("preset.clear_prof_confirm",
                        "Полностью очистить папку профиля «{p}»?", p=profiles or "?"),
                     win)
    if not box.exec():
        return
    n = wipe(settings, branch, preset.mode, profiles)
    InfoBar.success(title=tr("preset.cleared_prof", "Удалено элементов: {n}", n=n),
                    content="", parent=win, duration=3000,
                    position=InfoBarPosition.TOP_RIGHT)


def open_profile(win, settings: Settings, preset: ServerPreset, branch: str) -> None:
    """Открывает папку профиля в проводнике."""
    import os
    path = profile_dir(settings, preset, branch)
    if not path or not Path(path).is_dir():
        InfoBar.warning(title=tr("preset.no_profile",
                                 "Папки профиля ещё нет — она создастся при запуске."),
                        content=path or "", parent=win, duration=5000,
                        position=InfoBarPosition.TOP_RIGHT)
        return
    os.startfile(path)  # noqa: S606 — открытие проводника по своей же папке


def sync_admin_tools(win, settings: Settings, preset: ServerPreset, branch: str) -> None:
    """Перезаписывает в профиле списки админов и пароль VPP из «Настроек»."""
    from core.admin_tools import apply as apply_admin_rights
    if not settings.admin_steamids and not settings.admin_password.strip():
        InfoBar.warning(title=tr("preset.admin_sync_empty",
                                 "В настройках не заданы ни SteamID админов, ни пароль."),
                        content="", parent=win, duration=5000,
                        position=InfoBarPosition.TOP_RIGHT)
        return
    # mods=None — обновляем обе админки: какая из них подключена к пресету,
    # тут неважно, лишние файлы никому не мешают
    done = apply_admin_rights(profile_dir(settings, preset, branch), None,
                              settings.admin_steamids, settings.admin_password)
    InfoBar.success(title=tr("preset.admin_synced", "Обновлено админок: {n}", n=len(done)),
                    content=", ".join(t.title for t, _ in done),
                    parent=win, duration=4000, position=InfoBarPosition.TOP_RIGHT)
