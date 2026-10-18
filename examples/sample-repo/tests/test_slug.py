import unittest

from tinyutils.slug import slugify


class TestSlug(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")

    def test_collapses_and_trims_separators(self):
        self.assertEqual(slugify("  Already--slugged  "), "already-slugged")
        self.assertEqual(slugify("C++ & Rust: a comparison"), "c-rust-a-comparison")

    def test_accents(self):
        self.assertEqual(slugify("Crème Brûlée"), "creme-brulee")


if __name__ == "__main__":
    unittest.main()
