import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from core.plugin_manager import get_plugin_root


class PackagedPluginPathTests(unittest.TestCase):
    def test_frozen_build_uses_plugins_beside_executable(self):
        executable = Path("C:/Portable/UOSLabManager/UOSLabManager.exe")
        environment = dict(os.environ)
        environment.pop("UOSLAB_PLUGIN_DIR", None)
        environment.pop("UOSLAB_USER_PLUGIN_DIR", None)
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(executable)),
            patch.dict(os.environ, environment, clear=True),
        ):
            self.assertEqual(
                get_plugin_root(), executable.parent / "plugins"
            )


if __name__ == "__main__":
    unittest.main()
