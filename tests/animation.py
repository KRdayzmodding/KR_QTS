"""Run with python tests/animation.py. All input and output is isolated."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import animation_tools as tools
from core.settings import Settings


class AnimationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.kit = self.root / "комплект с пробелом"
        (self.kit / "blender").mkdir(parents=True)
        for rel in ("AnmConverter.exe", "blender.exe", "blender/xob_cli.py"):
            (self.kit / rel).touch()
        self.settings = Settings(animation_toolkit=str(self.kit), animation_blender=str(self.kit / "blender.exe"))

    def execute(self, *argv):
        return tools.run(tools.arguments().parse_args(list(map(str, argv))), self.settings)

    def test_convert_runs_on_copy(self):
        source = self.root / "кадр.anm"
        source.write_bytes(b"input")
        output = self.root / "out" / "result.txa"

        def convert(command):
            exe, local = command
            self.assertEqual(exe, self.kit / "AnmConverter.exe")
            self.assertNotEqual(local.parent, source.parent)
            self.assertEqual(local.name, source.name)
            local.with_suffix(".txa").write_bytes(b"converted")
            return "converted"

        with patch.object(tools, "_invoke", convert):
            self.execute("convert", source, "-o", output)
            with self.assertRaises(ValueError):
                self.execute("convert", source, "-o", output)
        self.assertEqual(source.read_bytes(), b"input")
        self.assertEqual(output.read_bytes(), b"converted")
        self.assertFalse(source.with_suffix(".txa").exists())

    def test_scene_export_failure_keeps_previous_outputs(self):
        source = self.root / "character.blend"
        clip, model = self.root / "clip.anm", self.root / "mesh.xob"
        for path in (source, clip, model):
            path.write_bytes(b"original")

        def fail_second(command):
            if "export-anm" in command:
                Path(command[command.index("-o") + 1]).write_bytes(b"new animation")
                return ""
            raise ValueError("failed to export model")

        with patch.object(tools, "_invoke", fail_second), self.assertRaisesRegex(ValueError, "failed to export model"):
            self.execute("scene-export", source, "-o", clip, "--model-out", model, "--overwrite")
        for path in (source, clip, model):
            self.assertEqual(path.read_bytes(), b"original")
        self.assertFalse(list(self.root.glob(".kr-qts-*")))

    def test_rig_is_protected_even_with_overwrite(self):
        rig, clip = self.root / "rig.blend", self.root / "clip.anm"
        rig.write_bytes(b"rig")
        clip.write_bytes(b"clip")
        with self.assertRaises(ValueError):
            self.execute("scene-import", clip, "--rig", rig, "-o", rig, "--overwrite")
        self.assertEqual(rig.read_bytes(), b"rig")

    def test_publish_restores_prior_file_when_second_name_cannot_be_created(self):
        first, second = self.root / "first", self.root / "second"
        first.write_bytes(b"previous")
        ready = self.root / "stage"
        ready.write_bytes(b"updated")
        with self.assertRaises(OSError):
            tools._publish([ready, self.root / "missing"], [first, second], overwrite=True)
        self.assertEqual(first.read_bytes(), b"previous")
        self.assertFalse(second.exists())


if __name__ == "__main__":
    unittest.main()
