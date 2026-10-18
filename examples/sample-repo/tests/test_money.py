import unittest

from tinyutils.money import format_cents, split_amount


class TestMoney(unittest.TestCase):
    def test_split_preserves_total(self):
        for total, parts in [(100, 3), (1, 4), (999, 7), (0, 2)]:
            shares = split_amount(total, parts)
            self.assertEqual(sum(shares), total)
            self.assertLessEqual(max(shares) - min(shares), 1)

    def test_split_order(self):
        self.assertEqual(split_amount(100, 3), [34, 33, 33])

    def test_format(self):
        self.assertEqual(format_cents(123456), "$1,234.56")
        self.assertEqual(format_cents(-5), "-$0.05")


if __name__ == "__main__":
    unittest.main()
