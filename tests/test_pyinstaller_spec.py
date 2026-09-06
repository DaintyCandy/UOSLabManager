import unittest
from pathlib import Path


class PyInstallerSpecTests(unittest.TestCase):
    def test_dynamic_plugin_dependencies_are_explicitly_collected(self):
        spec = Path("UOSLabManager.spec").read_text(encoding="utf-8")

        self.assertIn("collect_submodules('serial')", spec)

    def test_plugins_remain_external_to_internal_datas(self):
        spec = Path("UOSLabManager.spec").read_text(encoding="utf-8")

        self.assertNotIn("Tree('plugins'", spec)
        self.assertIn("external_plugin_dir", spec)


if __name__ == "__main__":
    unittest.main()
