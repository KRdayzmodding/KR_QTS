"""Run with python tests/client_mission.py."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.launcher import build_client_command
from core.mods import ModRegistry
from core.presets import MODE_DEDICATED, MODE_DIAG, ServerPreset
from core.settings import STABLE, Settings


class ClientMission(unittest.TestCase):
    def args(self, mode, extra):
        settings = Settings(client_stable=r"C:\DayZ")
        preset = ServerPreset(mode=mode, port=2302, extra_client=extra)
        return build_client_command(preset, settings, STABLE, ModRegistry(settings))[1]

    def test_diag_solo_mission(self):
        args = self.args(MODE_DIAG, r'-mission="F:\local test\solo.chernarusplus" -window')
        self.assertEqual(args, [r"-mission=F:\local test\solo.chernarusplus", "-window"])

    def test_network_clients_keep_default_connection(self):
        for mode, extra in ((MODE_DIAG, ""), (MODE_DIAG, "-mission="),
                            (MODE_DEDICATED, "-mission=solo")):
            self.assertIn("-connect=127.0.0.1:2302", self.args(mode, extra))


if __name__ == "__main__":
    unittest.main()
