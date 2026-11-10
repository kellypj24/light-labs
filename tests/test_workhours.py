import unittest
from datetime import datetime

from light_labs.core.workhours import working

TUE = datetime(2026, 11, 10)


class WorkingTest(unittest.TestCase):
    def test_weekdays_inside_the_window(self):
        self.assertTrue(working("08:00-17:00", TUE.replace(hour=8)))
        self.assertTrue(working("08:00-17:00", TUE.replace(hour=16, minute=59)))
        self.assertFalse(working("08:00-17:00", TUE.replace(hour=17)))
        self.assertFalse(working("08:00-17:00", TUE.replace(hour=7, minute=59)))

    def test_weekends_and_empty_are_off(self):
        self.assertFalse(working("08:00-17:00", datetime(2026, 11, 14, 10)))
        self.assertFalse(working("", TUE.replace(hour=10)))
