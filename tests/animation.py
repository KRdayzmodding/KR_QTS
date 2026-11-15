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
        for rel in ("AnmConverter.exe", "blender.exe", "blender/xob_cli.py", "blender/model_studio.py"):
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
            if local.suffix == ".anm":
                self.assertEqual(local.name, source.name)
                self.assertEqual(local.read_bytes(), b"input")
                local.with_suffix(".txa").write_bytes(b"converted")
            else:
                self.assertEqual(local.suffix, ".txa")
                self.assertEqual(local.read_bytes(), b"converted")
                local.with_suffix(".anm").write_bytes(b"input")
            return "converted"

        with patch.object(tools, "_invoke", convert):
            self.execute("convert", source, "-o", output)
            with self.assertRaises(ValueError):
                self.execute("convert", source, "-o", output)
        self.assertEqual(source.read_bytes(), b"input")
        self.assertEqual(output.read_bytes(), b"converted")
        self.assertFalse(source.with_suffix(".txa").exists())

    def test_lossy_txa_is_refused_before_replacing_existing_result(self):
        source, target = self.root / "clip.anm", self.root / "clip.txa"
        source.write_bytes(b"clip with unknown chunk")
        target.write_bytes(b"previous")

        def lossy(command):
            path = command[-1]
            suffix = ".anm" if path.suffix == ".txa" else ".txa"
            path.with_suffix(suffix).write_bytes(b"clip")
            return ""

        with patch.object(tools, "_invoke", lossy), self.assertRaisesRegex(ValueError, "scene-import"):
            self.execute("convert", source, "-o", target, "--overwrite")
        self.assertEqual(target.read_bytes(), b"previous")
        self.assertEqual(source.read_bytes(), b"clip with unknown chunk")

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

    def test_xob_imports_forward_resource_roots_and_keep_blender_materials(self):
        model, clip = self.root / "actor.xob", self.root / "idle.anm"
        saved = self.root / "rig.blend"
        model.touch()
        clip.touch()
        saved.touch()
        roots = [self.root / "library A", self.root / "библиотека B"]
        for root in roots:
            root.mkdir()
        self.settings.animation_assets_root = str(roots[1])
        sent = []

        def blender(argv):
            sent.append([argv[i + 1] for i, arg in enumerate(argv) if arg == "--assets-root"])
            Path(argv[argv.index("-o") + 1]).write_bytes(b"scene")
            return "resource report from Blender"

        roots_cli = ["--assets-root", roots[0], "--assets-root", roots[1]]
        with patch.object(tools, "_invoke", blender):
            log = self.execute("model-import", model, "-o", self.root / "one.blend", *roots_cli)
            self.assertIn("resource report from Blender", log)
            self.execute("scene-import", clip, "--rig", model, "-o", self.root / "two.blend", *roots_cli)
            self.execute("model-import", model, "-o", self.root / "three.blend")
            self.execute("scene-import", clip, "--rig", saved, "-o", self.root / "four.blend", *roots_cli)
            with self.assertRaises(ValueError):
                self.execute("model-import", model, "-o", self.root / "missing.blend",
                             "--assets-root", self.root / "missing library")
        self.assertEqual(sent, [roots, roots, roots[1:], []])
        self.assertFalse((self.root / "missing.blend").exists())

    def test_entire_library_uses_studio_backend_for_import_and_export(self):
        source, scene = self.root / "wolf.xob", self.root / "wolf.blend"
        visual = self.root / "wolf.p3d"
        for path in (source, scene, visual):
            path.touch()
        anims = self.root / "anims with spaces"
        anims.mkdir()
        folder = self.root / "results"
        with patch.object(tools, "_invoke", return_value="Studio report") as invoke:
            report = self.execute("library-import", source, "-o", scene, "--animations", anims,
                                  "--visual", visual, "--assets-root", self.kit, "--overwrite")
            self.assertEqual(report, "Studio report")
            command = invoke.call_args.args[0]
            self.assertEqual(command[command.index("--python") + 1], self.kit / "blender/model_studio.py")
            self.assertEqual(command[command.index("--") + 1:],
                             ["import", source, "-o", scene, "--assets-root", self.kit,
                              "--animations", anims, "--visual", visual, "--overwrite"])
            self.execute("library-export", scene, "-o", folder)
            command = invoke.call_args.args[0]
            self.assertEqual(command[command.index("--") + 1:], ["export", scene, "-o", folder])
        self.assertFalse(folder.exists())

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
