"""Check first-run packing with either supported engine installed alone."""
from pathlib import Path
import sys
import tempfile
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.mods import ModRegistry
from core.preflight import run_checks
from core.presets import MODE_DIAG, ServerPreset
from core.settings import STABLE, Settings


class PreflightPacker(unittest.TestCase):
    def test_ui_keeps_full_repack_with_projectbuilder_alone(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from qfluentwidgets import ComboBox
        from ui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        engine, branches = ComboBox(), ComboBox()
        for value in ("", "normal", "full"):
            engine.addItem(value or "off", userData=value)
        branches.addItems(["stable", "experimental"])
        with tempfile.TemporaryDirectory() as temp:
            exe = Path(temp) / "ProjectBuilder.exe"
            exe.touch()
            settings = Settings(krbuild_exe=str(exe), mikero_tools="", dayz_tools="", pack_tool="krbuild")
            window = SimpleNamespace(settings=settings,
                                     launch_page=SimpleNamespace(pack_engine=engine, branch_combo=branches))
            engine.setCurrentIndex(2)
            MainWindow._update_branch_availability(window)
            self.assertEqual(engine.currentData(), "full")
            self.assertFalse(engine.toolTip())
            exe.unlink()
            MainWindow._update_branch_availability(window)
            self.assertEqual(engine.currentData(), "")
            self.assertIn("ProjectBuilder", engine.toolTip())
        engine.deleteLater()
        branches.deleteLater()
        app.processEvents()

    def test_only_the_selected_engine_can_satisfy_preflight(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "DayZDiag_x64.exe").touch()
            preset = ServerPreset(mode=MODE_DIAG, launch_server=False, launch_client=True)
            settings = Settings(client_stable=temp, krbuild_exe=temp, mikero_tools=temp,
                                repack_before_launch=True)
            stale = [(SimpleNamespace(name="@Example"), "example")]
            with patch("core.packer.stale_mods", return_value=stale):
                for chosen, installed, expected in (
                    ("krbuild", "ProjectBuilder.exe", True),
                    ("krbuild", "pboProject.exe", False),
                    ("pboproject", "ProjectBuilder.exe", False),
                    ("pboproject", "pboProject.exe", True),
                ):
                    with self.subTest(chosen=chosen, installed=installed):
                        exe = folder / installed
                        exe.touch()
                        settings.pack_tool = chosen
                        problems = run_checks(preset, settings, STABLE, ModRegistry(settings))
                        self.assertEqual(not any(p.check_id == "packer" for p in problems), expected)
                        exe.unlink()


if __name__ == "__main__":
    unittest.main()
