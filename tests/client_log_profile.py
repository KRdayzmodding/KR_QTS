"""Run with python tests/client_log_profile.py."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.launcher import build_client_command
from core.logsource import client_log_dir
from core.mods import ModRegistry
from core.presets import MODE_DIAG, ServerPreset
from core.settings import STABLE, Settings


class ClientLogProfile(unittest.TestCase):
    def test_profile_logs_use_same_path_as_client(self):
        root = Path.cwd()
        settings = Settings(client_stable=str(root))
        for folder in (str(root / "my logs"), "my logs"):
            with self.subTest(folder=folder):
                preset = ServerPreset(mode=MODE_DIAG, extra_client=f'-profiles=older -PROFILES="{folder}"')
                _, args, _ = build_client_command(preset, settings, STABLE, ModRegistry(settings))
                self.assertIn(f"-PROFILES={folder}", args)
                self.assertIn(f"-connect=127.0.0.1:{preset.port}", args)
                self.assertEqual(client_log_dir(STABLE, preset, settings), root / "my logs")

    def test_no_explicit_profile_keeps_default(self):
        self.assertEqual(client_log_dir(STABLE, ServerPreset(), Settings()), client_log_dir(STABLE))


if __name__ == "__main__":
    unittest.main()
