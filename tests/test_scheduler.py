import unittest
from datetime import datetime, timedelta

from awtrix_gpt.scheduler import UpdateScheduler


class UpdateSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.s = UpdateScheduler.from_config({"active_hours": {"start": 7, "end": 23}, "update_interval": 1800})

    def test_from_config(self):
        self.assertEqual((self.s.start_hour, self.s.end_hour, self.s.interval), (7, 23, timedelta(minutes=30)))

    def test_outside_active_hours_never_due(self):
        self.assertFalse(self.s.is_due(None, datetime(2026, 10, 10, 3, 0)))

    def test_due_when_never_updated(self):
        self.assertTrue(self.s.is_due(None, datetime(2026, 10, 10, 9, 0)))

    def test_interval(self):
        last = datetime(2026, 10, 10, 9, 0)
        self.assertFalse(self.s.is_due(last, last + timedelta(minutes=29)))
        self.assertTrue(self.s.is_due(last, last + timedelta(minutes=30)))

    def test_bounds_inclusive(self):
        self.assertTrue(self.s.in_active_hours(datetime(2026, 1, 1, 7, 0)))
        self.assertTrue(self.s.in_active_hours(datetime(2026, 1, 1, 23, 59)))
        self.assertFalse(self.s.in_active_hours(datetime(2026, 1, 1, 6, 59)))

    def test_defaults(self):
        s = UpdateScheduler.from_config({})
        self.assertEqual((s.start_hour, s.end_hour, s.interval), (0, 23, timedelta(seconds=1800)))


if __name__ == "__main__":
    unittest.main()
