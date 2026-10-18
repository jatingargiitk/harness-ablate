import unittest

from tinyutils.textstats import average_word_length, word_count


class TestTextStats(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(word_count("one two three"), 3)

    def test_whitespace(self):
        self.assertEqual(word_count("  one   two\nthree\tfour  "), 4)
        self.assertEqual(word_count(""), 0)
        self.assertEqual(word_count("   \n "), 0)

    def test_average(self):
        self.assertEqual(average_word_length("ab abcd"), 3.0)


if __name__ == "__main__":
    unittest.main()
