import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.plugin_manager import (
    export_plugin, import_plugin, load_device_plugins,
    resolve_plugin_python_path, validate_plugin_id,
)


class DevicePluginPackageTests(unittest.TestCase):
    @staticmethod
    def write_device(root, plugin_id="COMPOSITE_TEST", profile="composite"):
        plugin_dir = root / plugin_id
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.json").write_text(json.dumps({
            "schema_version": 1,
            "api_version": "1",
            "type": "device",
            "profile": profile,
            "id": plugin_id,
            "name": "Composite Test",
            "version": "0.2.0",
            "entrypoint": "plugin.py:plugin",
            "enabled": True,
        }), encoding="utf-8")
        (plugin_dir / "driver.py").write_text(
            "class Driver:\n"
            "    def __init__(self, connection): self.connection = connection\n"
            "    def read_all(self): return {'value': 1.0}\n"
            "    def close(self): pass\n",
            encoding="utf-8",
        )
        (plugin_dir / "plugin.py").write_text(
            "from core.plugin_manager import DataColumn, DevicePlugin\n"
            "class TestPlugin(DevicePlugin):\n"
            f"    device_id = {plugin_id!r}\n"
            "    display_name = 'Composite Test'\n"
            "    columns = (DataColumn('value', 'test_value'),)\n"
            "    def connect(self, connection):\n"
            "        from .driver import Driver\n"
            "        return Driver(connection)\n"
            "plugin = TestPlugin()\n",
            encoding="utf-8",
        )
        services = plugin_dir / "services"
        services.mkdir()
        (services / "camera.py").write_text(
            "def frame_source(): return 'mock-frame'\n", encoding="utf-8"
        )
        return plugin_dir

    def test_manifest_device_is_loaded_with_profile_and_relative_imports(self):
        with TemporaryDirectory() as directory:
            devices = Path(directory) / "devices"
            plugin_dir = self.write_device(devices)
            plugins = load_device_plugins(devices)

            plugin = plugins["COMPOSITE_TEST"]
            self.assertEqual(plugin.profile, "composite")
            self.assertEqual(plugin.version, "0.2.0")
            driver = plugin.connect("mock")
            self.assertEqual(driver.read_all(), {"value": 1.0})
            self.assertTrue((plugin_dir / "services" / "camera.py").is_file())

    def test_manifest_id_must_match_device_plugin(self):
        with TemporaryDirectory() as directory:
            devices = Path(directory) / "devices"
            plugin_dir = self.write_device(devices)
            manifest_path = plugin_dir / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["id"] = "DIFFERENT_ID"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "does not match"):
                load_device_plugins(devices)

    def test_composite_package_export_import_preserves_extra_python_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_device(root / "source")
            archive = export_plugin(source, root / "composite.uosplugin")
            destination = import_plugin(archive, root / "installed")

            self.assertEqual(destination.parent.name, "devices")
            self.assertTrue((destination / "services" / "camera.py").is_file())
            self.assertIn(
                "COMPOSITE_TEST",
                load_device_plugins(root / "installed" / "devices"),
            )

    def test_composite_python_paths_are_confined_and_importable(self):
        with TemporaryDirectory() as directory:
            plugin_dir = Path(directory) / "device"
            plugin_dir.mkdir()
            self.assertEqual(
                resolve_plugin_python_path(
                    plugin_dir, "services/camera_worker.py"
                ),
                plugin_dir / "services" / "camera_worker.py",
            )
            for invalid in (
                "../outside.py", "/absolute.py", "bad-name.py",
                "services/not_python.txt",
            ):
                with self.subTest(invalid=invalid):
                    with self.assertRaises(ValueError):
                        resolve_plugin_python_path(plugin_dir, invalid)

    def test_plugin_id_rules_are_portable_and_bounded(self):
        for valid in ("A", "CTVIDEO3M", "heating_control", "Device_2"):
            with self.subTest(valid=valid):
                self.assertEqual(validate_plugin_id(valid), valid)

        invalid = (
            "", "2DEVICE", "device-name", "한글장비", "class", "CON",
            "A" * 65,
        )
        for plugin_id in invalid:
            with self.subTest(invalid=plugin_id):
                with self.assertRaises(ValueError):
                    validate_plugin_id(plugin_id)

    def test_import_rejects_case_only_id_collision(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.write_device(root / "source_a", plugin_id="DeviceOne")
            second = self.write_device(root / "source_b", plugin_id="deviceone")
            first_archive = export_plugin(first, root / "first.uosplugin")
            second_archive = export_plugin(second, root / "second.uosplugin")
            import_plugin(first_archive, root / "installed")

            with self.assertRaises(FileExistsError):
                import_plugin(second_archive, root / "installed")


if __name__ == "__main__":
    unittest.main()
