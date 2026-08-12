import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from core.plugin_manager import (
    _seed_plugins, export_experiment_plugin, import_experiment_plugin,
    load_experiment_plugins,
)


class TestUserExperimentPlugins(unittest.TestCase):
    @staticmethod
    def _write_portable_plugin(root, plugin_id="portable"):
        plugin_dir = root / plugin_id
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.json").write_text(json.dumps({
            "id": plugin_id,
            "type": "experiment",
            "entrypoint": "plugin.py:plugin",
            "enabled": True,
        }), encoding="utf-8")
        (plugin_dir / "plugin.py").write_text(
            "from core.plugin_manager import ExperimentPlugin\n"
            f"plugin = ExperimentPlugin(experiment_id={plugin_id!r}, "
            "display_name='Portable')\n",
            encoding="utf-8",
        )
        return plugin_dir

    def test_plugin_export_and_import_round_trip(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._write_portable_plugin(root / "source")
            archive = export_experiment_plugin(source, root / "portable.uosplugin")
            destination = import_experiment_plugin(
                archive, root / "installed" / "experiments"
            )

            self.assertEqual(destination.name, "portable")
            self.assertEqual(
                (destination / "plugin.py").read_text(encoding="utf-8"),
                (source / "plugin.py").read_text(encoding="utf-8"),
            )
            self.assertIn("portable", load_experiment_plugins(root / "installed"))

    def test_plugin_import_requires_explicit_replace(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._write_portable_plugin(root / "source")
            archive = export_experiment_plugin(source, root / "portable.uosplugin")
            import_experiment_plugin(archive, root / "installed")
            with self.assertRaises(FileExistsError):
                import_experiment_plugin(archive, root / "installed")

    def test_packaged_plugins_are_seeded_without_overwriting_user_edits(self):
        with TemporaryDirectory() as source_directory, TemporaryDirectory() as destination_directory:
            source = Path(source_directory)
            destination = Path(destination_directory)
            plugin_source = source / "experiments" / "sample"
            plugin_source.mkdir(parents=True)
            (plugin_source / "plugin.py").write_text("packaged", encoding="utf-8")
            plugin_target = destination / "experiments" / "sample"
            plugin_target.mkdir(parents=True)
            (plugin_target / "plugin.py").write_text("user edit", encoding="utf-8")
            (plugin_source / "plugin.json").write_text("{}", encoding="utf-8")

            _seed_plugins(source, destination)

            self.assertEqual(
                (plugin_target / "plugin.py").read_text(encoding="utf-8"),
                "user edit",
            )
            self.assertTrue((plugin_target / "plugin.json").is_file())

    def test_repository_user_experiments_are_discovered(self):
        plugins = load_experiment_plugins()

        self.assertIn("heating_control", plugins)
        self.assertIn("line_profile", plugins)
        self.assertNotIn("temperature_sweep", plugins)
        self.assertNotIn("iv_sweep", plugins)
        self.assertIsNotNone(plugins["heating_control"].panel_factory)
        commands = {
            command.key: command
            for command in plugins["heating_control"].sequence_commands
        }
        self.assertEqual(commands["ramp_to_setpoint"].unit, "°C")
        self.assertFalse(commands["stop_heating"].requires_value)

    def test_manifest_id_must_match_exported_plugin(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            plugin_dir = root / "experiments" / "wrong_id"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(json.dumps({
                "id": "wrong_id",
                "type": "experiment",
                "entrypoint": "plugin.py:plugin",
                "enabled": True,
            }), encoding="utf-8")
            (plugin_dir / "plugin.py").write_text(
                "from core.plugin_manager import ExperimentPlugin\n"
                "plugin = ExperimentPlugin(experiment_id='actual_id', display_name='Test')\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "does not match"):
                load_experiment_plugins(root)

            plugins = load_experiment_plugins(root, strict=False)
            self.assertNotIn("wrong_id", plugins)

    def test_uppercase_plugin_id_is_supported(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            plugin_dir = root / "experiments" / "My_Experiment2"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(json.dumps({
                "id": "My_Experiment2",
                "type": "experiment",
                "entrypoint": "plugin.py:plugin",
                "enabled": True,
            }), encoding="utf-8")
            (plugin_dir / "plugin.py").write_text(
                "from core.plugin_manager import ExperimentPlugin\n"
                "plugin = ExperimentPlugin(experiment_id='My_Experiment2', "
                "display_name='Test')\n",
                encoding="utf-8",
            )

            plugins = load_experiment_plugins(root)
            self.assertIn("My_Experiment2", plugins)


if __name__ == "__main__":
    unittest.main()
