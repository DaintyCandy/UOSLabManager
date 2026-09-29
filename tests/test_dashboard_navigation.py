import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QListView

from gui.panel_dashboard import DashboardPanel


class DashboardNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.connected = set()
        self.manager = SimpleNamespace(
            get_device=lambda name: object() if name in self.connected else None,
            get_metrics=lambda _name: {},
        )
        self.devices = {f"d{i}": SimpleNamespace(display_name=f"Device {i}") for i in range(18)}
        self.experiments = {
            f"e{i}": SimpleNamespace(display_name=f"Experiment {i}", description=f"Description {i}")
            for i in range(4)
        }
        self.open_device = Mock()
        self.open_experiment = Mock()
        self.panel = DashboardPanel(
            self.manager, self.devices, self.experiments,
            self.open_device, self.open_experiment,
        )
        self.panel.resize(1360, 280)
        self.panel.show()
        QTest.qWait(50)

    def tearDown(self):
        self.panel.refresh_timer.stop()
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()

    def test_lists_flow_horizontally_and_wrap_in_a_narrow_window(self):
        for plugin_list in (self.panel.device_list, self.panel.experiment_list):
            self.assertEqual(plugin_list.flow(), QListView.Flow.LeftToRight)
            self.assertTrue(plugin_list.isWrapping())
            self.assertEqual(plugin_list.movement(), QListView.Movement.Static)
            first = plugin_list.visualItemRect(plugin_list.item(0))
            second = plugin_list.visualItemRect(plugin_list.item(1))
            self.assertEqual(first.top(), second.top())
            self.assertLess(first.left(), second.left())
        self.panel.resize(640, 280)
        QTest.qWait(50)
        plugin_list = self.panel.device_list
        self.assertGreater(plugin_list.visualItemRect(plugin_list.item(5)).top(),
                           plugin_list.visualItemRect(plugin_list.item(0)).top())
        self.assertLessEqual(plugin_list.height(), 100)
        self.assertEqual(plugin_list.horizontalScrollBar().maximum(), 0)
        self.assertGreater(plugin_list.verticalScrollBar().maximum(), 0)

    def test_activation_preserves_ids_and_callbacks(self):
        item = self.panel.device_items["d2"]
        self.panel.device_list.itemActivated.emit(item)
        self.open_device.assert_called_once_with("d2")
        item = self.panel.experiment_items["e1"]
        self.panel.experiment_list.itemActivated.emit(item)
        self.open_experiment.assert_called_once_with("e1")

    def test_wide_mode_reflows_existing_items_vertically(self):
        items = [self.panel.device_list.item(i) for i in range(self.panel.device_list.count())]
        self.panel.set_layout_mode("wide")
        self.panel.resize(240, 800)
        QTest.qWait(50)
        for plugin_list in (self.panel.device_list, self.panel.experiment_list):
            self.assertEqual(plugin_list.flow(), QListView.Flow.TopToBottom)
            self.assertFalse(plugin_list.isWrapping())
            first = plugin_list.visualItemRect(plugin_list.item(0))
            second = plugin_list.visualItemRect(plugin_list.item(1))
            self.assertEqual(first.left(), second.left())
            self.assertLess(first.top(), second.top())
        self.assertGreater(self.panel.device_list.height(), 100)
        self.panel.set_layout_mode("compact")
        self.panel.resize(1360, 280)
        QTest.qWait(50)
        self.assertEqual(items, [self.panel.device_list.item(i) for i in range(len(items))])
        self.assertEqual(self.panel.device_list.flow(), QListView.Flow.LeftToRight)

    def test_status_and_reload_still_update_horizontal_items(self):
        self.connected.add("d1")
        self.panel.refresh_devices()
        self.assertTrue(self.panel.device_items["d1"].text().startswith("●"))
        self.panel.set_active_experiment("e2")
        self.assertTrue(self.panel.experiment_items["e2"].text().startswith("●"))
        self.panel.set_device_plugins({"new": SimpleNamespace(display_name="New Device")})
        self.panel.set_experiment_plugins({
            "new_exp": SimpleNamespace(display_name="New Experiment", description="New description"),
        })
        QTest.qWait(50)
        self.assertEqual(self.panel.device_list.count(), 1)
        self.assertEqual(self.panel.experiment_list.count(), 1)
        self.assertEqual(self.panel.device_list.item(0).data(Qt.ItemDataRole.UserRole), "new")
        self.assertEqual(self.panel.experiment_list.item(0).toolTip(), "New description")
        self.assertEqual(self.panel.active_experiment_id, None)


if __name__ == "__main__":
    unittest.main()
