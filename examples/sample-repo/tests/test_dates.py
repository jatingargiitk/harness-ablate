import unittest
from datetime import date

from tinyutils.dates import add_months, days_in_month, is_leap_year


class TestDates(unittest.TestCase):
    def test_leap_years(self):
        self.assertTrue(is_leap_year(2024))
        self.assertTrue(is_leap_year(2000))
        self.assertFalse(is_leap_year(1900))
        self.assertFalse(is_leap_year(2023))

    def test_february(self):
        self.assertEqual(days_in_month(2100, 2), 28)
        self.assertEqual(days_in_month(2400, 2), 29)

    def test_add_months_clamps(self):
        self.assertEqual(add_months(date(2024, 1, 31), 1), date(2024, 2, 29))
        self.assertEqual(add_months(date(1900, 1, 31), 1), date(1900, 2, 28))
        self.assertEqual(add_months(date(2023, 11, 15), 3), date(2024, 2, 15))


if __name__ == "__main__":
    unittest.main()
