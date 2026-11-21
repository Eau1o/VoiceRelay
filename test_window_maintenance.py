"""Windows-only regression tests. Run with python -m unittest test_window_maintenance."""
import unittest
from unittest.mock import patch

import window_maintenance as wm


class MaintenanceTests(unittest.TestCase):
    def test_closed_window_defers_during_recording_and_throttles_failed_activation(self):
        maintenance = wm.WindowMaintenance()
        with patch.object(wm, "main_windows", return_value=[]), patch.object(
                wm, "request_main_window", return_value=False) as request:
            self.assertFalse(maintenance.ensure_hidden(starting=False))
            self.assertFalse(maintenance.ensure_hidden(microphone_busy=lambda: True))
            request.assert_not_called()
            self.assertFalse(maintenance.ensure_hidden())
            self.assertFalse(maintenance.ensure_hidden())
            request.assert_called_once()

    def test_rebuild_waits_for_quota_before_hiding(self):
        maintenance = wm.WindowMaintenance()
        with patch.object(wm, "main_windows", side_effect=[[], [55], [55], [55]]), patch.object(
                wm, "request_main_window", return_value=True), patch.object(
                wm, "read", side_effect=[None, (123, 2000)]) as quota, patch.object(
                wm, "hide_restorable", return_value=True) as hide:
            self.assertEqual(maintenance.ensure_hidden(), "rebuilt")
            self.assertEqual(quota.call_count, 2)
            hide.assert_called_once_with(55)

    def test_hidden_window_remains_restorable(self):
        with patch.object(wm, "show") as show, patch.object(wm, "valid", return_value=True), \
                patch.object(wm, "visible", return_value=False):
            self.assertTrue(wm.hide_restorable(25))
            self.assertEqual([c.args for c in show.call_args_list], [(25, 7), (25, 0)])

if __name__ == "__main__":
    unittest.main()
